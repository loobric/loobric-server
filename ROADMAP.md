# Roadmap

Planned and aspirational work, kept out of the README so feature claims there always
match the code. Sequencing follows the v2 milestones; epics track the detail:

## Milestone 1 — the sync loop (in progress)

The wear-offset round trip: a tool touched off at the machine shows up in CAM, with
provenance and an audit trail.

- Public API (`ToolInstanceRecord`, `ToolCatalogRecord`, `Machine`, `ToolTableEntry`, `ToolSet`) — #3, #4
- Identity binding between controller tool tables and tool records, with a review inbox — #5, #6
- A read-only view of which tool-set members are not yet present on the linked machine — #18 (clients: #19, freecad#8). Pulled from M1 scope in the 2026-06 reboot; it returns only if it re-earns a place in the ubiquitous language (see `docs/UBIQUITOUS_LANGUAGE.md`).
- Conflict freeze and resolution (no silent overwrites) — #7
- Docker packaging (x86 + ARM) and a sub-30-minute quickstart — #8
- **Schema migration spine** — so a `docker pull` + restart upgrades a populated database
  safely instead of crashing on a changed table. ✅ **Done**: ledger + forward-only runner +
  baseline, and self-describing backups that refuse a newer-than-head restore. Design:
  [`docs/MIGRATIONS.md`](docs/MIGRATIONS.md).

## Milestone 2 — importers (epic #11)

User-side importers for the formats hobbyists already have, including feeds & speeds
where the source carries them:

- Vectric tool databases (`.tool` / `.vtdb`)
- Fusion 360 `.tools` libraries
- Carbide Create CSV

## Milestone 3 — cutting parameters & sharing (epic #12)

- Feeds & speeds preset records (engineering values: surface speed, chipload — aligned
  with FreeCAD's F&S architecture)
- Preset sync via `.fctb`
- Community library publishing
- Public sandbox + invite-gated hosted instances

## Milestone 4 — small-shop phase (epic #13)

- ISO 13399 / GTC catalog import (pragmatic P21 property subset)
- FreeCAD F&S resolver provider backed by Loobric
- Manufacturer catalog publishing
- Hosted offering general availability

## Exploratory / unscheduled

- STEP-NC and MTConnect alignment
- Webhook/event system for external integrations
- Rate limiting and hardening for public-facing deployments
- PostgreSQL as a supported production backend
- **Auth hardening — session cookie `Secure` flag.** The login session cookie is set
  HttpOnly + SameSite=Lax but **without `Secure`** (`loobric_server/api/auth.py:381-386`), so it can
  ride plain HTTP despite the docstring claiming otherwise. Set `Secure` (conditionally on a
  production/HTTPS setting) so session IDs are never sent in clear text.
- **Auth hardening — gate user registration.** `register()` (`loobric_server/api/auth.py:281`) has no
  auth dependency, so registration is unconditionally open: the first user becomes admin, but
  any anonymous caller can then create more accounts. Non-first-user registration should
  require admin auth. Two tests already assert this and currently fail against the open
  behavior — `tests/integration/test_registration_security.py::{test_second_user_registration_requires_auth,test_non_admin_cannot_register_users}`;
  closing the gap makes them pass.

## Deferred (considered, not pursued)

- **Solo → multi-user data adoption.** A solo-mode instance owns all its data as the built-in
  solo user, whose password is generated and never disclosed; switching the server to
  multi-user (`LOOBRIC_SOLO` unset) therefore strands that data under an unreachable account.
  The fix *would have been* an admin-gated operation (e.g. `POST /api/v1/account/<verb>` + a
  `loobric` CLI verb) that reassigns every tool-data row owned by `solo@localhost.loobric_server` to a
  real account, run once after promotion. **Deferred as concept drift:** it only matters if a
  single-user instance later goes multi-user, which is not a path we are building for now. If
  revived, it needs a verb that clears the language gate (note: `adopt` is a retired term) and
  a glossary entry with founder sign-off.
