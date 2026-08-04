# Security Assumptions — and the tests that prove them

> **The rule (the vocabulary-gate pattern, applied to security):** every
> security assumption lives in this table with the test that proves it, and
> a new assumption lands **with its row and its test in the same commit**.
> An assumption without a test is a hope; a mechanism without an enforcement
> test is decoration. We know, because we shipped both: scopes were stored,
> displayed, and unit-tested for a month while **no endpoint checked them**
> (fixed 0.6.0 — see the post-mortem at the bottom).

Run the whole security surface:

```bash
pytest tests/contract/test_key_scopes.py \
       tests/contract/test_cross_account_isolation.py \
       tests/contract/test_backup_authz.py \
       tests/contract/test_resolver_page.py \
       tests/integration/test_registration_security.py \
       tests/integration/test_session_cookie.py
```

## The assumptions

| # | Assumption | Enforced where | Proven by |
|---|---|---|---|
| 1 | A key's writes are gated by the **door scopes** it holds (`read sync observe assert bind delete admin`); the 403 names the missing scope | `auth/doors.py` → `door()` on every v2 endpoint | `test_key_scopes.py` |
| 2 | The **agent key** (`read sync assert`) can never observe, delete, bind, or touch the Inbox — even through a raw client that bypasses the MCP surface | same | `test_key_scopes.py` (observe/delete/bind/inbox refusals) |
| 3 | An assert key can't smuggle measured values: `qa` on create-instance requires `observe`; tool-table-entry create/push is the observe door | `tool_catalog_records.py` composite check; entry routes | `test_key_scopes.py` |
| 4 | **Legacy keys** (pre-0.6.0 scope strings) degrade to **read-only**, with their own 403 message | `doors.effective_doors()` | `test_key_scopes.py` |
| 5 | Creating a key requires explicit, valid door scopes (400 otherwise) | `api/auth.py` create_key | `test_key_scopes.py` |
| 6 | **A key can never create or revoke keys or change the password** (no self-escalation); key management is session/solo territory | `doors.session_or_solo_only()` | `test_key_scopes.py` |
| 7 | Admin surface needs the admin **role** AND (for keys) the `admin` **scope** — a full-preset key cannot wipe/reset/export | `require_admin` + `door("admin")` | `test_key_scopes.py`, `test_backup_authz.py` |
| 8 | **Cross-account isolation**: user B — session or fully-scoped key — gets 404s and empty listings for user A's records, on every entity | `_owned()` filters in every router | `test_cross_account_isolation.py` |
| 9 | Every audit row records the **true acting credential** (`channel`, `api_key_id`) — the declared actor is client-supplied; these are server truth, so a spoofed actor is detectable | `audit.py` via `Session.info` | `test_key_scopes.py` |
| 10 | **Registration is closed by default**: after the first user, only an admin creates accounts (`LOOBRIC_OPEN_REGISTRATION=1` opts out — the sandbox does) | `api/auth.py` register | `test_registration_security.py` |
| 11 | The session cookie is HttpOnly, SameSite=Lax, and **Secure** when forced or auto-detected (`LOOBRIC_COOKIE_SECURE`) | `api/auth.py` login | `test_session_cookie.py` |
| 12 | Backup export/import require an authenticated **administrator** | `backup_api.require_admin` | `test_backup_authz.py` |
| 13 | Sessions and **solo mode** are unscoped — a signed-in human may use every door; solo bypasses auth entirely and only ever reaches the solo user's data | `doors.check_doors` channel check | `test_key_scopes.py` (session/solo tests) |
| 14 | Agents **assert, never observe**, and no delete/bind/credential tool exists on the MCP channel; asserts over `observed` values are refused client-side | loobric-cli `loobric/mcp/tools.py` | loobric-cli `tests/test_mcp_tools.py` |
| 15 | Passwords and API keys are stored only as bcrypt hashes; the plain key is shown once | `auth/password.py`, `auth/apikey.py` | `tests/unit/test_auth_apikey.py` |
| 16 | **Labels are owner-private**: only the generating account can see a label or put it on a record; cross-account (and someone else's blank code) is 404, never 403 | `api/labels.py` `_owned()`, `tool_instance_records.py` label/unlabel code lookup filtered by `user_id` | `test_cross_account_isolation.py` (label tests) |
| 17 | **Label codes are enumerable-but-safe**: `secrets`-random over 32^8 (sparse keyspace, no rate limiting — see Known NOT covered #1), and the resolver's response for an unknown code vs someone else's blank code is indistinguishable, so probing reveals nothing | `label_codes.py` generation; `api/resolver.py` identical landing responses | `test_resolver_page.py` (indistinguishability test) |
| 18 | **The anonymous public page never identifies the owner** — no email, user/record UUIDs, machine names, client names, or client sections; provenance sources reduced to their kind (the one full source shown is `derived:usage-ledger`, non-identifying by construction). Usage: the derived total is public, its per-machine decomposition is not — publish the sum, never the ledger. Built by allowlist construction, so new private fields can't leak by default | `public_view.py` (construction, never filtering) | `test_public_page.py` (leak canary + usage tests), `tests/unit/test_public_view.py` |
| 19 | The resolver's server-rendered HTML **autoescapes record-supplied strings** — a hostile tool name cannot inject markup into the public page | `web/templating.py` (Jinja2 autoescape, on for everything) | `test_public_page.py` (XSS test) |

## Known NOT covered (ranked; each needs a decision or a test, not silence)

1. **Rate limiting** — does not exist. The sandbox is on the public internet
   with open registration; abuse control is currently Cloudflare and hope.
   Decision needed before promoting the sandbox harder.
2. **CSRF** — the API relies on `SameSite=Lax` alone; there is no token and
   no test. State-changing endpoints accept the session cookie.
3. **Web UI output escaping** — `esc()` is used throughout the static page,
   but nothing tests that record-supplied strings can't inject markup.
   (The server-rendered resolver pages ARE tested — row 19; this item now
   covers only the static `/ui` page.)
4. **Session-store properties** — in-memory, no rotation-on-login test, no
   fixation test; sessions vanish on restart (documented, untested).
5. **Actor↔key binding** — deliberately deferred (SCOPES_PLAN Q8): spoofed
   actors are *detectable* (row 9), not *preventable*. Revisit with
   multi-user teams.

## Post-mortem: how unenforced scopes shipped (2026-07, condensed)

Four compounding causes — each now has a countermeasure:

1. **Fixture monoculture**: 14 of 16 contract files use `solo_client`, which
   bypasses auth by construction — credential bugs were invisible to the
   suite. *Countermeasure*: the security files above run multi-user with
   real registered accounts and real keys.
2. **Positive-path bias**: auth tests proved features work, never that
   forbidden things fail. *Countermeasure*: the tests above are refusal
   tests first.
3. **Orphaned mechanism**: the v1 scope machinery's unit tests stayed green
   after the reboot deleted its only call sites — green tests of a mechanism
   nothing called. *Countermeasure*: assumptions here are proven **through
   HTTP**, at the enforcement point, not by unit-testing the helper.
4. **No enumeration**: nothing forced a test per assumption.
   *Countermeasure*: this file, and the same-commit rule at the top.
