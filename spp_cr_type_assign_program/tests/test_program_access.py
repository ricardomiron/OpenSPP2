"""Security regression: the assign-program detail must reject a program the
selecting user cannot access.

The detail's ``program_id`` Many2one ``domain`` only constrains the UI; a raw
ORM/RPC write can point it at an arbitrary program. On apply the strategy runs
under ``sudo`` (`spp.change.request._do_apply`), so program record rules and the
global multi-company rule on ``spp.program`` would be bypassed — assigning a
registrant to a hidden/cross-company program and leaking its name via preview.
An ``@api.constrains`` on the detail enforces, in the writing user's own
context, that the selected program is actually visible to them.
"""

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.spp_change_request_v2.tests.common import CRTestCase

ASSIGN_PROGRAM_CR_TYPE_DEFS = {
    "name": "Assign to Program",
    "target_type": "both",
    "detail_model": "spp.cr.detail.assign_program",
    "apply_strategy": "custom",
    "apply_model": "spp.cr.apply.assign_program",
}


@tagged("post_install", "-at_install")
class TestAssignProgramAccess(CRTestCase):
    """A CR user must not be able to target a program they cannot access."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Program = cls.env["spp.program"]

        cls.cr_type = cls.CRType.search([("code", "=", "assign_program")], limit=1)
        if not cls.cr_type:
            cls.cr_type = cls.CRType.create({"code": "assign_program", **ASSIGN_PROGRAM_CR_TYPE_DEFS})

        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "CR Access Test Company B"})

        # A program the test user CAN see (their own company).
        cls.program_visible = cls.Program.create(
            {
                "name": "Company A Individual Program",
                "target_type": "individual",
                "company_id": cls.company_a.id,
            }
        )
        # A program in another company — hidden by the global multi-company rule
        # spp_programs.rule_spp_program_company for a company-A-only user.
        cls.program_cross_company = cls.Program.create(
            {
                "name": "Company B Individual Program",
                "target_type": "individual",
                "company_id": cls.company_b.id,
            }
        )

        # A CR user scoped to company A only: can write assign-program details
        # (group_cr_user) and read programs (group_programs_viewer), but the
        # multi-company rule keeps company-B programs out of their reach.
        cls.cr_user = cls.env["res.users"].create(
            {
                "name": "CR User (Company A)",
                "login": "cr_user_company_a",
                "company_id": cls.company_a.id,
                "company_ids": [(6, 0, [cls.company_a.id])],
                "group_ids": [
                    (
                        4,
                        cls.env.ref("spp_change_request_v2.group_cr_user").id,
                    ),
                    (
                        4,
                        cls.env.ref("spp_programs.group_programs_viewer").id,
                    ),
                ],
            }
        )
        # Make the cr_user's own partner a registrant so change requests can be
        # created with it. Using it as the registrant models "the CR user's own
        # change request" and keeps these tests robust to detail-ownership record
        # rules (PR #261) that scope detail write to CRs the user owns/created.
        cls.cr_user_registrant = cls.cr_user.partner_id
        cls.cr_user_registrant.write({"is_registrant": True, "is_group": False})

    def _cr_user_env(self, model):
        """`model` in the cr_user's env, scoped to company A only — mirroring a
        real company-A session, whose allowed companies are limited to the ones
        the user belongs to."""
        return self.env[model].with_user(self.cr_user).with_context(allowed_company_ids=[self.company_a.id])

    def _make_cr(self):
        """Create a CR as admin (CR-name sequence generation needs privileged
        access) with the cr_user's own partner as registrant, so a detail write
        as cr_user is allowed both today and once PR #261's ownership rule lands.
        Returns the CR (admin env)."""
        return self.CR.create({"request_type_id": self.cr_type.id, "registrant_id": self.cr_user_registrant.id})

    def _make_cr_and_detail(self):
        """Return (cr, detail) with the detail bound to the cr_user's context —
        the program_id write (what the constraint guards) then runs as cr_user."""
        cr = self._make_cr()
        detail = cr.get_detail()
        return cr, detail.with_user(self.cr_user).with_context(allowed_company_ids=[self.company_a.id])

    def test_reject_cross_company_program(self):
        _cr, detail = self._make_cr_and_detail()
        with self.assertRaises(ValidationError):
            detail.write({"program_id": self.program_cross_company.id})

    def test_reject_cross_company_program_on_create(self):
        # The constraint must also fire when the program is set at create time.
        # Details are created lazily, so create one directly (do not call
        # get_detail first, which would auto-create the single detail).
        cr = self._make_cr()
        with self.assertRaises(ValidationError):
            self._cr_user_env("spp.cr.detail.assign_program").create(
                {
                    "change_request_id": cr.id,
                    "program_id": self.program_cross_company.id,
                }
            )

    def test_allow_visible_program(self):
        _cr, detail = self._make_cr_and_detail()
        detail.write({"program_id": self.program_visible.id})
        self.assertEqual(detail.program_id, self.program_visible)

    def test_allow_shared_program(self):
        # A company-shared program (company_id = False) is in no company's
        # exclusive scope and must remain selectable.
        shared = self.Program.create(
            {"name": "Shared Individual Program", "target_type": "individual", "company_id": False}
        )
        _cr, detail = self._make_cr_and_detail()
        detail.write({"program_id": shared.id})
        self.assertEqual(detail.program_id, shared)
