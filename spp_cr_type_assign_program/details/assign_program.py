from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SPPCRDetailAssignProgram(models.Model):
    """Detail model for the assign-to-program CR type."""

    _name = "spp.cr.detail.assign_program"
    _description = "CR Detail: Assign to Program"
    _inherit = ["spp.cr.detail.base", "mail.thread"]

    program_id = fields.Many2one(
        "spp.program",
        string="Program",
        tracking=True,
        domain="[('id', 'in', allowed_program_ids)]",
        help=(
            "Active programs whose target type matches this beneficiary. "
            "On apply, a Draft membership is created — a Program Manager "
            "activates it from there."
        ),
    )
    allowed_program_ids = fields.Many2many(
        "spp.program",
        string="Allowed Programs",
        compute="_compute_allowed_program_ids",
    )
    registrant_target_type = fields.Selection(
        [("group", "Group"), ("individual", "Individual")],
        compute="_compute_registrant_target_type",
        store=True,
    )
    created_membership_id = fields.Many2one(
        "spp.program.membership",
        string="Created Membership",
        readonly=True,
    )

    @api.constrains("program_id")
    def _check_program_access(self):
        """Reject a program the selecting user cannot access.

        The `program_id` domain only constrains the UI; a raw ORM/RPC write can
        point it at an arbitrary program. Since the apply strategy runs under
        `sudo` (spp.change.request._do_apply), an inaccessible program would
        otherwise be assigned - and its name leaked via preview - bypassing
        program record rules and multi-company scope. Enforce access here, in
        the writing user's own context, so the stored value can only ever be a
        program that user may target.

        Two checks, because neither alone is sufficient:
        - `search()` applies the user's record rules (area/registrant scope,
          etc.), so a program hidden by those rules returns empty and is
          rejected.
        - an explicit `company_id in env.companies` guard enforces multi-company
          scope directly, independent of whether the global company `ir.rule` is
          evaluated in the current write context (it is not always), so a
          cross-company program is rejected deterministically.
        """
        for rec in self:
            program = rec.program_id
            if not program:
                continue
            # `or` short-circuits: if the record is not visible, program.company_id
            # is not read (avoids an AccessError on a rule-hidden record).
            if not self.env["spp.program"].search([("id", "=", program.id)]) or (
                program.company_id and program.company_id not in self.env.companies
            ):
                raise ValidationError(_("You do not have access to the selected program."))

    @api.depends("registrant_id", "registrant_id.is_group")
    def _compute_registrant_target_type(self):
        for rec in self:
            if not rec.registrant_id:
                rec.registrant_target_type = False
                continue
            rec.registrant_target_type = "group" if rec.registrant_id.is_group else "individual"

    @api.depends(
        "registrant_target_type",
        "registrant_id.program_membership_ids.program_id",
    )
    def _compute_allowed_program_ids(self):
        Program = self.env["spp.program"]
        # target_type only has two distinct values; cache the per-type
        # active-program search so a recordset of N details runs at most
        # 2 queries against spp.program. The per-registrant exclusion of
        # already-enrolled programs is then applied in Python via set
        # subtraction.
        # Note: the result can become stale if a program transitions
        # active <-> ended while a CR form is open. Acceptable: the apply
        # strategy revalidates `state == 'active'` at apply time, so
        # staleness is a UI-only concern.
        cache = {}
        for rec in self:
            tt = rec.registrant_target_type
            if not tt:
                rec.allowed_program_ids = False
                continue
            if tt not in cache:
                cache[tt] = Program.search(
                    [
                        ("state", "=", "active"),
                        ("target_type", "=", tt),
                    ]
                )
            already_in = rec.registrant_id.program_membership_ids.program_id
            rec.allowed_program_ids = cache[tt] - already_in
