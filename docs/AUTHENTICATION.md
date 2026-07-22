# Authentication

Loobric Core protects your tool data while staying easy to integrate with machines
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

1. Log in to the Loobric Core web UI
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

### Scopes

Scopes follow a simple `action:entity` pattern, with wildcards:

- `read` — read access to all resources
- `write:<entity>` — create/update a resource kind (e.g. `write:instances`)
- `delete:<entity>` — delete a resource kind
- `admin:<entity>` — administrative actions on a resource kind
- `write:*` — any write action (action wildcard)
- `admin:*` — full access; **bypasses scope and tag checks**

A key with no scopes is denied. `admin:*` grants everything; the `read` scope
covers all read operations.

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
- **Scope + tag enforcement** is wired on the internal tool resources
  (tool items, assemblies, instances, presets).
- **Per-client scope enforcement for the public sectioned-record API**
  (`tool-instance-records` et al.) is the planned per-client scope manifest
  described in [TOOL_SCHEMA.md](./TOOL_SCHEMA.md) §10 — **not yet enforced**.
  Those endpoints currently rely on authentication and per-user isolation. Treat
  the scope/tag model above as the access-control design; do not assume
  fine-grained scope rejection on the records API until §10 lands.

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

Loobric Core also supports a **solo mode** that runs as a single built-in user
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
