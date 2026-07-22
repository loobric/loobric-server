# How to Build a Loobric Client

Loobric has no privileged client. The server is one public REST API, and every
tool that connects to it — FreeCAD, LinuxCNC, the `loobric` CLI, and anything you
write — is just a client of that API with no special access. This guide is what
you need to build your own.

It is deliberately practical. For the full data model and rationale see
[ARCHITECTURE.md](./ARCHITECTURE.md), [TOOL_SCHEMA.md](./TOOL_SCHEMA.md),
[CONCEPTS.md](./CONCEPTS.md), and [AUTHENTICATION.md](./AUTHENTICATION.md). The
machine-readable contract is always the OpenAPI spec (below) — when this document
and the spec disagree, the spec wins.

---

## 1. The mental model

- **The server is the source of truth.** A client holds its own representation of
  some tools (a FreeCAD `.fctb` library, a LinuxCNC `.tbl`, a spreadsheet) and
  *syncs* it to the server. The server reconciles, keeps provenance, and never
  guesses.
- **Everything is the public API.** There is exactly one read/write path:
  `/api/v1`. There is no back door, not even for first-party clients.
- **Records have three sections.** Every syncable record is one JSON document
  with three lanes:

  ```jsonc
  {
    "internal":  { "id": "…", "version": 7, "created_at": "…", "updated_at": "…" },
    "canonical": { /* the shared, provenance-tagged truth */ },
    "clients":   { "<your-client-name>": { "data": { /* your native payload */ } } }
  }
  ```

  - `internal` — server-owned identity/versioning. **Read-only** to clients.
  - `canonical` — the agreed-upon facts (name, geometry, status, …). Each leaf is
    provenance-tagged: `{ "value": …, "source": "…", "unit": "mm" }`. Written
    only through the **assert** and **observe** doors; the **server** stamps
    `source` — a client never sends provenance.
  - `clients.<name>` — *your* private section. Put whatever you need to round-trip
    your native format here. Written only through the **sync** door. You can only
    ever write your own section; you physically cannot touch another client's.

This separation is the whole safety story: a buggy or hostile client can corrupt
only its own `clients.<name>` section, never the canonical record or another
client's data.

### Provenance

Every canonical value carries a `source` describing how it came to be:

- `observed:<who>@<where>` — a machine measured it (e.g. `observed:linuxcnc@mill01`).
- `asserted:<who>` — a human or client declared it (e.g. `asserted:human@inbox`).
- `derived` — computed from other values.

You never write `source` yourself — you call the right door and the server
composes it.

---

## 2. Authentication

Send an API key as a Bearer token on every request:

```bash
curl -H "Authorization: Bearer $LOOBRIC_API_KEY" \
  https://api.loobric.com/api/v1/tool-instance-records
```

Get a key from your server in one of two ways:

- **Web UI** — sign in, open the **Account** tab, **New key**, copy it (shown once).
- **CLI** — `pip install loobric-cli`, then `loobric register` / `loobric login`
  / `loobric create-key mytool --scopes "read write"`.

Keys are scoped (`read`, `write:<entity>`, `delete:<entity>`, `admin:*`, …). Ask
for the least you need; `read write` is the usual full-client set. See
[AUTHENTICATION.md](./AUTHENTICATION.md) for the scope grammar. All data is
isolated per account — a key only ever sees its owner's data.

---

## 3. The API surface

Base URL: `https://<server>/api/v1`. JSON in, JSON out. The resources a client
cares about:

| Resource | Path | What it is |
|---|---|---|
| Machines | `/machine-records` | A CNC machine (identity, controller type, definition) |
| Catalog records | `/tool-catalog-records` | Reusable tool *types* (manufacturer, product code, nominal geometry) |
| Tool instances | `/tool-instance-records` | Physical tools — the primary syncable resource |
| Tool-table entries | `/tool-table-entry-records` | One machine tool-table row (number, offsets, binding) |
| Tool sets | `/tool-set-records` | A named, ordered collection of tools |
| Inbox | `/instance-inbox` | Server-proposed bindings and frozen conflicts awaiting a human |
| Audit log | `/audit-logs` | Who changed what, when |

> Some other paths exist for the retiring v1 substrate (`/tool-instances`,
> `/tool-items`, `/tool-presets`, …). They are excluded from the OpenAPI schema
> and **deprecated — do not build on them.** Use the `*-records` resources.

### The doors (how you write)

| Door | Call | Use it for |
|---|---|---|
| **read** | `GET /<resource>` and `GET /<resource>/{id}` | Listing and inspecting |
| **create** | `POST /<resource>` | Minting a new record |
| **assert** | `POST /<resource>/{id}/assert` — `{path, value, unit?, actor}` | Declaring a canonical value (a human/client decision) |
| **observe** | `POST /<resource>/{id}/observe` — `{path, value, unit?, client, machine}` | A machine reporting a measured value |
| **sync** | `PUT /<resource>/{id}/clients/{client}` — `{client_version, client_item_id, data}` | Writing your own client section |

Canonical changes go through **assert**/**observe**, never through **create** —
create makes a blank record, then you assert its fields. (The catalog create is
the one exception: it takes nominal fields in a single atomic call.)

### The sync loop, briefly

The controller side of a machine pushes its tool table:

```
POST /api/v1/tool-table-entry-records/sync
{ "machine_id": "…", "client": "linuxcnc", "machine_name": "mill01",
  "mode": "merge", "entries": [ { "tool_number": 1, "description": "1/4 endmill",
  "offsets": { "diameter": 6.35, "diameter_unit": "mm" } } ] }
```

The server may then **propose** binding an entry to an existing tool instance.
Proposals land in the **inbox**; a human confirms or rejects them:

```
GET  /api/v1/instance-inbox
POST /api/v1/instance-inbox/{id}/confirm     # bind — never overwrites
POST /api/v1/instance-inbox/{id}/reject
```

The golden rule: **sync never prompts, blocks, or guesses.** When two sides
disagree, you surface it and leave it unsynced — you do not silently overwrite.

---

## 4. Explore it live

Point a browser at a running server (the hosted sandbox shown):

- **Swagger UI** (interactive): <https://api.loobric.com/api/v1/docs>
- **ReDoc** (reference): <https://api.loobric.com/api/v1/redoc>
- **OpenAPI spec** (machine-readable): <https://api.loobric.com/api/v1/openapi.json>

A self-hosted server exposes the same three at its own address. The fastest way
to get a feel for the loop is the [sandbox quickstart](https://github.com/loobric/loobric-cli/blob/master/docs/SANDBOX.md).

---

## 5. Recommended approach

1. **Start from the reference client.** [`loobric-cli`](https://github.com/loobric/loobric-cli)
   is standard-library Python, full API coverage, and written to be read. Copy its
   transport and record-handling patterns even if you target another language.
2. **Or generate from OpenAPI.** Feed `openapi.json` to your language's client
   generator for a typed stub, then build sync logic on top.
3. **Model the sync as preview → apply.** Compute a diff (in sync / changed here /
   changed on server / new / conflict), let the user choose per item, then apply.
   This is the pattern every first-party client uses; it keeps the human in control.
4. **Preserve the raw native payload** in `clients.<name>.data` so nothing your
   format expresses is lost in translation.

---

## 6. Build it with an AI agent

The API is small and fully described by its OpenAPI spec, which makes it a good
fit for an AI coding agent. Paste a prompt like this (fill in the brackets):

```text
You are building a Loobric client for [APPLICATION OR CONTROLLER, e.g. "Fusion 360"].

Loobric is a CNC tool-data sync server with a single public REST API.

Contract you must follow:
- Base URL: [BASE_URL]/api/v1 . Authenticate EVERY request with the header
  `Authorization: Bearer [API_KEY]`. JSON in, JSON out.
- Treat the OpenAPI spec at [BASE_URL]/api/v1/openapi.json as the source of
  truth — fetch it first and derive endpoints and schemas from it.
- Records have three sections: `internal` (read-only), `canonical`
  (provenance-tagged shared truth), and `clients.<name>` (your private section).
- Lane discipline: write your native data ONLY into `clients.<name>` via
  `PUT /<resource>/{id}/clients/<name>`. Write canonical values only via the
  `assert`/`observe` doors, and NEVER send a `source`/provenance field — the
  server stamps it. Never write `internal` or another client's section.
- Sync must never overwrite silently: compute a diff, show it, apply only the
  items the user chose; leave conflicts unsynced and surface them.

Task:
1. Read the OpenAPI spec.
2. Implement, in [LANGUAGE], a client that can: authenticate; list/read
   machines, tool instances, catalog records, tool sets, and tool-table entries;
   map [APPLICATION]'s native tool format to and from the Loobric schema; and sync
   both directions with a preview-then-apply flow.
3. Preserve the raw native payload in `clients.<name>.data`.
4. Confirm/reject binding proposals from `/instance-inbox` instead of guessing.
5. Ship a README with install + "connect to a server" (URL + API key) steps and
   one worked example.

Use https://github.com/loobric/loobric-cli as a reference implementation.
Keep dependencies minimal.
```

Always review generated code against the live Swagger UI before trusting it.

---

## 7. Get your client listed on loobric.com

We feature community clients on the [Clients page](https://loobric.com/clients).
To be listed, a client should:

- **Speak only the public API** (no dependency on server internals).
- **Have a README** with install steps and how to connect (server URL + API key).
- **Carry a clear open-source license.** MIT is recommended for clients, matching
  the first-party ones — but listing is about being open, documented, and
  installable, not about who owns it.
- **Work against the current API version.**

Then submit it either way:

- **Open an issue** on [loobric-server](https://github.com/loobric/loobric-server/issues)
  titled `Client listing: <name>`, **or**
- **Email** [hello@loobric.com](mailto:hello@loobric.com).

Include:

- Client name and a one-line description
- Repository URL
- What it integrates (CAM app, controller, ERP, presetter, …)
- License
- Optional: a logo (SVG or PNG) and a maintainer contact

We'll do a quick review that it uses the API as intended and meets the bar above,
then add it to the website. Found a gap in the API while building? Open an issue —
client authors are exactly who the public API is for.

---

## License

The core server is AGPL-3.0; the first-party clients are MIT. Your client is
yours — license it however you like.
