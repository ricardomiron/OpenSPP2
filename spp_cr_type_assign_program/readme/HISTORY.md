## 19.0.1.0.3 (2026-07-23)

### Fixed

- security: validate server-side that the user selecting a program on
  `spp.cr.detail.assign_program` can actually access it. The `program_id`
  domain only constrained the UI, so a raw RPC write could target a
  hidden or cross-company program; on apply the strategy runs under `sudo`,
  which would assign the membership and leak the program name via preview
  while bypassing program record rules and multi-company scope. An
  `@api.constrains` now rejects a program the writing user cannot see
  (record rules) or that is outside their company scope.

## 19.0.1.0.0 (2026-05-04)

### Added

- New module `spp_cr_type_assign_program` with the `assign_program` change
  request type.
- Detail model `spp.cr.detail.assign_program` with live program-domain
  filtering based on the registrant's target type.
- Apply strategy `spp.cr.apply.assign_program` that creates a draft
  `spp.program.membership` record on apply.
- Conflict rule that blocks duplicate in-flight assignments to the same
  `(registrant, program)` pair.
