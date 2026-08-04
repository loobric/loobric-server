# Authentication

Loobric Server protects your tool data while staying easy to integrate with machines
and applications. Every API endpoint requires authentication (unless auth is
explicitly disabled — see below), and all data is isolated per user account.

## Two Ways to Authenticate

### 1. User accounts (Web UI)
- Email + password login
- Session-cookie based
- For managing tools and data, and for creating API keys

### 2. API keys (machine / client access)
- For CNC controllers, scripts, and applications
- Created by users through the web UI
- Optionally scoped, tagged, and given an expiration

## API Keys

### Creating an API key

1. Log in to the Loobric Server web UI
2. Open **Settings → API Keys**
3. Click **Create New Key** and set:
   - **Name** — a label (e.g. "Mill #3", "Backup Script")
   - **Scopes** — what the key may do (see [Scopes](#scopes))
   - **Tags** — optional labels that narrow which resources the key can act on
   - **Expiration** — optional expiry date
4. **Copy the key immediately — it is shown only once.**

The key is a random URL-safe token (32 bytes of entropy, no fixed prefix). Only a
bcrypt hash is stored server-side; the plaintext is never persisted and cannot be
recovered — revoke and reissue if it is lost.

### Using an API key

Send the key as a Bearer token in the `Authorization` header:

```bash
curl -H "Authorization: Bearer <your-api-key>" \
  https://api.loobric.com/api/v1/tool-instance-records
```

The public API is served under `/api/v1/`. The primary resources are
`tool-instance-records`, `tool-catalog-records`, `tool-table-entry-records`,
`tool-set-records`, and `machine-records` (see [ARCHITECTURE.md](./ARCHITECTURE.md)
and [TOOL_SCHEMA.md](./TOOL_SCHEMA.md)).

### Scopes (0.6.0 — door-aligned, ENFORCED)

An API key's scopes are the **doors** it may use (SCOPES_PLAN.md, grilled
2026-07-27). The seven scope names ARE the canonical door vocabulary:

| Scope | Grants | Typical holder |
|---|---|---|
| `read` | every GET (records, changes, audit, media) | everyone |
| `sync` | writing the client's own section | CAM/controller clients |
| `observe` | the observe door + tool-table-entry create/push, and the `qa` payload on create-instance | machines / deterministic pipelines only |
| `assert` | the assert door, seeded creates, tool-set membership, media attach | humans, agents |
| `bind` | bind / unbind / Inbox confirm & reject | humans |
| `delete` | record and media-reference deletes | humans |
| `admin` | wipe, account reset, seed-demo, backups, user roster | admins (the key needs the scope AND the account the role) |

The canonical **AI-agent key is `read sync assert`** — it cannot observe,
bind, or delete, which makes "agents assert, never observe" a property of the
credential rather than a convention.

Rules:

- Creating a key **requires** explicit scopes drawn from the seven names —
  anything else is a 400. Presets: `loobric create-key --preset agent`
  (`controller` / `cam` / `full`), or the Web UI preset buttons.
- **Legacy keys** (created before 0.6.0, e.g. `["read", "write"]`) degrade to
  **read-only**; their writes 403 with a message saying to create a new key.
- **Sessions are unscoped** — a signed-in human may use every door (admin
  endpoints still require the admin role). Solo mode likewise.
- **API keys cannot manage keys or change passwords** — key creation and
  revocation require a session (or solo mode), so a key can never create
  itself a stronger key.
- Every audit row records the acting credential: `channel`
  (`session` / `api-key` / `solo`) and `api_key_id`. The declared actor is
  client-supplied; these columns are server truth, so a spoofed actor string
  is detectable.

### Introspecting a key (`GET /api/v1/auth/key`)

A client can ask the server what the credential it just presented may do —
**before** attempting a write — with `GET /api/v1/auth/key`. The endpoint
requires nothing beyond a valid credential (a read-only key must be able to
learn it is read-only; a revoked or expired key gets the normal 401), and the
response contains no secrets:

```json
{
  "channel": "api-key",
  "api_key_id": "b4f2…",
  "name": "shop-freecad",
  "scopes": ["read", "sync", "assert"],
  "read_only": false,
  "legacy": false,
  "user_id": "…",
  "email": "owner@shop.example"
}
```

- `channel` + `api_key_id` are the key's audit identity — exactly what audit
  rows record for its writes.
- `scopes` are the **effective** door scopes (what enforcement honors), not
  the stored list: a legacy key reports `["read"]` with `legacy: true`.
- `read_only` is true iff the key holds no door beyond `read` — true for
  legacy keys and equally for a deliberately created `["read"]` key.
- On a session (or solo mode) the same endpoint answers with
  `channel: "session"` / `"solo"` and **no `scopes` field at all** — sessions
  are unscoped by doctrine, which is different from holding an empty list.

This is what lets loobric-freecad's asset-store mode activate read-only UI
for a read-only key instead of discovering a 403 after an edit already
happened, and what `loobric status` uses to describe the configured key.

### Tags

Tags provide coarse, resource-level access control on top of scopes:

```json
{
  "name": "Mill #3 API Key",
  "scopes": ["read", "write:instances"],
  "tags": ["mill-3", "production"]
}
```

**How tags work:** a tagged key may only act on resources sharing at least one of
its tags. Access is granted when **any** key tag matches **any** resource tag.

- **Key has no tags** — no tag restriction (access governed by scopes alone)
- **Resource has no tags** — reachable by any key with the right scopes
- **Session login** — bypasses tag checks (a user owns all their own resources)
- **`admin:*` scope** — bypasses tag checks

**Use cases:** machine-specific keys (`mill-3`, `lathe-1`), location-based access
(`shop-floor`, `office`), purpose grouping (`backup`, `monitoring`), or
environment isolation (`production`, `staging`).

## What Is Enforced Today

- **Authentication** is required on every endpoint (session cookie or API key),
  unless auth is disabled (below).
- **Per-user data isolation** applies everywhere: each user sees only their own
  data; an admin sees all of it. API keys inherit their owner's access.
- **Door-scope enforcement** (0.6.0): every public sectioned-record endpoint
  checks the calling key's scopes per the table above. The 403 names the
  missing scope. Tag-based access (below) predates the reboot and is **not**
  enforced on the v2 surface; treat tags as informational metadata.

## Security

### Passwords
- Hashed with bcrypt (never stored in plaintext)
- 8-character minimum recommended

### API keys
- 32-byte cryptographically random tokens
- Stored only as a bcrypt hash
- Shown once at creation
- Can be revoked at any time; support an optional expiration

### Sessions
- Server-side session store is **in-memory** (single process). It is not shared
  across replicas and is cleared on server restart — you will need to log in again
  after a restart. Production deployments should back it with Redis or the
  database.
- The session cookie is **HttpOnly** and **SameSite=Lax**, with a **24-hour**
  lifetime (`max_age`).

## Disabling Authentication

For testing or trusted single-user deployments:

```bash
export AUTH_ENABLED=false
```

With auth disabled, all endpoints act as a built-in test user and become publicly
accessible — only use this in a trusted environment.

Loobric Server also supports a **solo mode** that runs as a single built-in user
without login ceremony, intended for local single-operator setups.

## Multi-Tenancy

All data is isolated by user account:
- Each user sees only their own tools, sets, machines, and related records
- API keys inherit their owner's data access
- Queries are filtered by `user_id` (admins are exempt and see all data)

## Troubleshooting

**"Invalid API key"**
- The key may be expired, revoked, or mistyped
- Confirm it is still active under Settings → API Keys

**"Insufficient permissions"**
- The key lacks the scope (or matching tag) required for the operation
- Issue a new key with the appropriate scopes/tags

**"Session expired" / logged out unexpectedly**
- Log in again through the web UI
- The session cookie lasts 24 hours; you are also logged out if the server
  restarts (in-memory session store)
