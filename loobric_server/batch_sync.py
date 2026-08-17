# GNU Affero General Public License v3.0 only
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""The batch sync doors (docs/BATCH_SYNC.md, grilled 2026-08-17).

`POST /tool-instance-records/sync` and `POST /tool-catalog-records/sync`:
batch-shaped composition of the existing doors, because sync workloads are
batch-shaped and SQLite's single writer makes one-transaction-per-batch the
only real speedup (327-tool import: ~2,600 requests -> 2-3).

Lane discipline is composition, never blur:
- an item's `data` writes only the client's own section and NEVER influences
  canonical;
- `asserts` run the assert door's shared code path (`assert_guards` +
  `is_same_value_noop` below are the SAME functions the single-record doors
  call), so every guard rides along;
- `presets` run the contribution door's path (floor, replace-own).

Failure model: validation problems are per-item results (`result: "error"`)
and the batch proceeds; DB-level failures abort the whole batch (500,
rolled back — the upsert is idempotent, retrying is safe).
"""
import copy
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict

from loobric_server.audit import create_audit_log
from loobric_server.auth.doors import effective_doors
from loobric_server.contract import Provenance

# One transaction per batch holds SQLite's write lock for the duration; the
# cap keeps a batch from starving a concurrently syncing machine while
# keeping per-item cost sub-millisecond (grill amendment A5).
MAX_ITEMS = 200

INSTANCE = "tool_instance_record"
CATALOG = "tool_catalog_record"


# ---------------------------------------------------------------------------
# Request/response shapes
# ---------------------------------------------------------------------------

class AssertEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    value: Any = None
    unit: Optional[str] = None


class PresetEntry(BaseModel):
    """Mirrors the contribution door's body minus `actor` (the batch-level
    actor transcribes every entry)."""
    model_config = ConfigDict(extra="forbid")

    origin: str
    label: str
    material: dict
    op_type: Optional[str] = None
    vc: Optional[dict] = None
    fz: Optional[dict] = None
    ratio: Optional[dict] = None
    extras: Optional[dict] = None
    machine_id: Optional[str] = None

    def payload(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class BatchItem(BaseModel):
    """`extra="forbid"` IS the lane discipline: an item that smuggles a
    `canonical`/`internal`/`source` key fails validation outright."""
    model_config = ConfigDict(extra="forbid")

    id: Optional[str] = None              # targets a record directly
    client_item_id: Optional[str] = None  # upsert identity otherwise
    data: dict = {}
    asserts: List[AssertEntry] = []
    presets: List[PresetEntry] = []


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client: str
    client_version: str = ""
    actor: Optional[str] = None           # defaults to `client`; NEVER falls
                                          # back to the account identity (#48)
    items: List[BatchItem] = []


class ItemError(Exception):
    """A validation-class problem with ONE item: reported per-item, the
    batch proceeds."""


# ---------------------------------------------------------------------------
# The shared assert path (single doors call these too)
# ---------------------------------------------------------------------------

def assert_guards(entity_type: str, path: str, value: Any,
                  status_values=frozenset()) -> None:
    """Every path rule the assert door enforces, in one place. Raises
    HTTPException(400) with the door's own messages."""
    if entity_type == INSTANCE:
        if path == "usage" or path.startswith("usage."):
            raise HTTPException(
                status_code=400,
                detail="usage is derived from the usage ledger; no door "
                       "writes it directly")
        if path == "status" and value is not None \
                and value not in status_values:
            raise HTTPException(
                status_code=400,
                detail="status must be one of %s (or null to clear it) — "
                       "the vocabulary is ratified, not accreted"
                       % sorted(status_values))
    if path == "presets" or path.startswith("presets."):
        raise HTTPException(
            status_code=400,
            detail="presets is a derived union; contribute through "
                   "POST /%ss/{id}/presets instead"
                   % entity_type.replace("_", "-"))


def leaf_at(canonical: dict, path: str) -> Optional[dict]:
    node = canonical
    parts = path.split(".")
    for p in parts[:-1]:
        node = node.get(p)
        if not isinstance(node, dict):
            return None
    leaf = node.get(parts[-1])
    return leaf if isinstance(leaf, dict) else None


def is_same_value_noop(canonical: dict, path: str, value: Any,
                       unit: Optional[str], actor: str) -> bool:
    """The ratified same-value rule (BATCH_SYNC.md §2.4): an assert whose
    value, unit AND actor all match the stored leaf is a no-op — idempotent
    re-syncs. A different actor asserting the same value still applies:
    corroboration is a provenance claim and stays recorded."""
    leaf = leaf_at(canonical, path)
    return (leaf is not None
            and leaf.get("value") == value
            and leaf.get("unit") == unit
            and leaf.get("source") == Provenance.asserted(actor))


def holds_assert(request: Request) -> bool:
    """Whether this request's credential may exercise the assert lane.
    Session/solo always may; an API key needs the scope."""
    if getattr(request.state, "auth_channel", None) != "api-key":
        return True
    return "assert" in effective_doors(getattr(request.state, "scopes", []))


# ---------------------------------------------------------------------------
# Engine helpers
# ---------------------------------------------------------------------------

def _blank_result(item: BatchItem) -> dict:
    return {"client_item_id": item.client_item_id, "id": item.id,
            "result": "error", "asserts_applied": 0, "asserts_blocked": 0,
            "presets_contributed": 0, "presets_skipped": 0}


def _apply_asserts(api, row, item, actor: str, can_assert: bool,
                   entity_type: str, db, user, out: dict) -> int:
    """Run an item's asserts through the shared path against `row`. Returns
    the number actually applied (same-value no-ops count as neither applied
    nor blocked)."""
    if not item.asserts:
        return 0
    if not can_assert:
        out["asserts_blocked"] = len(item.asserts)
        return 0
    status_values = getattr(api, "STATUS_VALUES", frozenset())
    canonical = row.canonical
    applied = 0
    for entry in item.asserts:
        assert_guards(entity_type, entry.path, entry.value, status_values)
        if is_same_value_noop(canonical, entry.path, entry.value,
                              entry.unit, actor):
            continue
        field = {"value": entry.value, "source": Provenance.asserted(actor)}
        if entry.unit is not None:
            field["unit"] = entry.unit
        canonical = api._set_path(canonical, entry.path, field)
        api._validate_canonical(canonical)
        create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                         entity_type=entity_type, entity_id=row.id,
                         changes={"path": entry.path,
                                  "source": field["source"]})
        applied += 1
        if entity_type == INSTANCE and entry.path == "catalog_type_id":
            row.catalog_type_id = entry.value
    if applied:
        row.canonical = canonical
    out["asserts_applied"] = applied
    return applied


def _contribute_presets(row, item, actor: str, can_assert: bool, kind,
                        db, user, out: dict) -> None:
    """Run an item's preset contributions through the contribution door's
    path. Below-floor entries are honest skips, never errors."""
    if not item.presets:
        return
    from loobric_server import presets as presets_mod
    contributed = skipped = 0
    for entry in item.presets:
        if not can_assert:
            skipped += 1
            continue
        try:
            presets_mod.contribute(db, user, kind, row.id, entry.payload(),
                                   actor=actor)
            contributed += 1
        except presets_mod.PresetError:
            skipped += 1
    if contributed:
        presets_mod.materialize(db, user, row, kind)
    out["presets_contributed"] = contributed
    out["presets_skipped"] = skipped


def _write_section(api, row, req: BatchRequest, item: BatchItem, db, user,
                   entity_type: str) -> bool:
    """Write the client's own section (the sync lane), or refresh metadata
    in place when `data` is JSON-equal (server-authoritative `unchanged`).
    Returns True when data actually changed."""
    clients = copy.deepcopy(row.clients)
    existing = clients.get(req.client)
    if existing is not None \
            and (existing.get("data") or {}) == (item.data or {}):
        # unchanged: client_version/client_item_id refresh without counting
        # as a change — no version bump, no audit row.
        if existing.get("client_version") != req.client_version \
                or existing.get("client_item_id") != item.client_item_id:
            existing["client_version"] = req.client_version
            existing["client_item_id"] = item.client_item_id
            row.clients = clients
        return False
    clients[req.client] = {
        "client_version": req.client_version,
        "client_item_id": item.client_item_id,
        "created_at": (existing or {}).get("created_at") or api._now(),
        "updated_at": api._now(),
        "data": item.data or {},
    }
    row.clients = clients
    create_audit_log(session=db, user_id=user.id, operation="SYNC",
                     entity_type=entity_type, entity_id=row.id,
                     changes={"client": req.client})
    return True


def _batch_audit(db, user, entity_type: str, req: BatchRequest, actor: str,
                 results: List[dict]) -> None:
    counts = Counter(r["result"] for r in results)
    create_audit_log(session=db, user_id=user.id, operation="SYNC_BATCH",
                     entity_type=entity_type, entity_id=req.client,
                     changes={"client": req.client, "actor": actor,
                              "items": len(results), **dict(counts)})


# ---------------------------------------------------------------------------
# Instance batch
# ---------------------------------------------------------------------------

def run_instance_batch(db, user, req: BatchRequest, can_assert: bool,
                       include_records: bool) -> dict:
    from loobric_server.api import tool_instance_records as api
    from loobric_server import presets as presets_mod
    from loobric_server.database.schema import ToolInstanceRecord as Row

    actor = (req.actor or req.client).strip()
    rows = db.query(Row).filter(Row.user_id == user.id).all()
    by_id: Dict[str, Any] = {r.id: r for r in rows}
    by_item: Dict[str, list] = {}
    for r in rows:
        cid = (r.clients.get(req.client) or {}).get("client_item_id")
        if cid:
            by_item.setdefault(cid, []).append(r)

    results = []
    for item in req.items:
        out = _blank_result(item)
        try:
            if item.id:
                row = by_id.get(item.id)
                if row is None:
                    raise ItemError("unknown id %r" % item.id)
            elif item.client_item_id:
                matches = by_item.get(item.client_item_id, [])
                if len(matches) > 1:
                    raise ItemError(
                        "ambiguous_item_id: %d records carry %r for client "
                        "%r — target one with `id`"
                        % (len(matches), item.client_item_id, req.client))
                row = matches[0] if matches else None
            else:
                raise ItemError("item needs `id` or `client_item_id`")

            # Pre-flight the assert guards BEFORE any write, so a guard
            # violation leaves the item wholly untouched.
            for entry in item.asserts:
                assert_guards(INSTANCE, entry.path, entry.value,
                              api.STATUS_VALUES)

            if row is None:
                if not can_assert:
                    raise ItemError(
                        "blocked: creating records requires the assert "
                        "scope (this key holds only sync)")
                row = Row(canonical=api._blank_canonical(),
                          clients={req.client: {
                              "client_version": req.client_version,
                              "client_item_id": item.client_item_id,
                              "created_at": api._now(),
                              "updated_at": api._now(),
                              "data": item.data or {}}},
                          catalog_type_id=None, user_id=user.id,
                          created_by=user.id, updated_by=user.id)
                db.add(row)
                db.flush()
                create_audit_log(session=db, user_id=user.id,
                                 operation="CREATE",
                                 entity_type=INSTANCE, entity_id=row.id)
                by_id[row.id] = row
                if item.client_item_id:
                    by_item.setdefault(item.client_item_id, []).append(row)
                out["result"] = "created"
                changed = True
            else:
                changed = _write_section(api, row, req, item, db, user,
                                         INSTANCE)
                out["result"] = "updated" if changed else "unchanged"

            applied = _apply_asserts(api, row, item, actor, can_assert,
                                     INSTANCE, db, user, out)
            if changed or applied:
                row.version += 1
                row.updated_by = user.id
            _contribute_presets(row, item, actor, can_assert,
                                presets_mod.KIND_INSTANCE, db, user, out)
            out["id"] = row.id
            if include_records:
                out["record"] = api._response(row)
        except ItemError as exc:
            out["error"] = str(exc)
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise
            out["error"] = str(exc.detail)
        results.append(out)

    _batch_audit(db, user, INSTANCE, req, actor, results)
    db.commit()
    return {"items": results}


# ---------------------------------------------------------------------------
# Catalog batch
# ---------------------------------------------------------------------------

_IDENTITY_PATHS = ("name", "manufacturer", "product_code")


def run_catalog_batch(db, user, req: BatchRequest, can_assert: bool,
                      include_records: bool) -> dict:
    from loobric_server.api import tool_catalog_records as api
    from loobric_server import presets as presets_mod
    from loobric_server.database.schema import ToolCatalogRecord as Row

    actor = (req.actor or req.client).strip()
    rows = db.query(Row).filter(Row.user_id == user.id).all()
    by_natural: Dict[tuple, Any] = {
        (r.manufacturer_norm, r.product_code_norm): r for r in rows}

    results = []
    for item in req.items:
        out = _blank_result(item)
        try:
            identity = {}
            for entry in item.asserts:
                assert_guards(CATALOG, entry.path, entry.value)
                if entry.path in _IDENTITY_PATHS:
                    identity[entry.path] = entry
            missing = [p for p in _IDENTITY_PATHS
                       if identity.get(p) is None
                       or identity[p].value is None]
            if missing:
                raise ItemError(
                    "identity floor: asserts must carry name, manufacturer "
                    "and product_code (missing: %s)" % ", ".join(missing))
            key = (api._norm(identity["manufacturer"].value),
                   api._norm(identity["product_code"].value))

            row = by_natural.get(key)
            if row is not None:
                # `exists`: no create, no canonical writes — but the
                # client's OWN section still syncs (your lane is always
                # yours; a newer vendor file keeps the raw current).
                _write_section(api, row, req, item, db, user, CATALOG)
                row.updated_by = user.id
                out["result"] = "exists"
                out["id"] = row.id
                if include_records:
                    out["record"] = api._response(row)
                results.append(out)
                continue

            if not can_assert:
                raise ItemError(
                    "blocked: creating records requires the assert scope "
                    "(this key holds only sync)")

            # Seeded create, mirroring the single create door: every assert
            # becomes a canonical leaf stamped asserted:<actor>; ONE CREATE
            # audit row (the seeded-create precedent).
            canonical: dict = {"geometry": {}}
            for entry in item.asserts:
                field = {"value": entry.value,
                         "source": Provenance.asserted(actor)}
                if entry.unit is not None:
                    field["unit"] = entry.unit
                canonical = api._set_path(canonical, entry.path, field)
            api._validate_canonical(canonical)
            row = Row(canonical=canonical,
                      clients={req.client: {
                          "client_version": req.client_version,
                          "client_item_id": item.client_item_id,
                          "created_at": api._now(),
                          "updated_at": api._now(),
                          "data": item.data or {}}},
                      user_id=user.id, created_by=user.id,
                      updated_by=user.id)
            api._stamp_natural_key(row, canonical)
            db.add(row)
            db.flush()   # a cross-request race on the unique index is a
            #              DB-level failure: whole batch rolls back, retry
            #              is safe (in-batch duplicates never get here —
            #              by_natural already holds the first item's row)
            create_audit_log(session=db, user_id=user.id,
                             operation="CREATE", entity_type=CATALOG,
                             entity_id=row.id)
            by_natural[key] = row
            out["result"] = "created"
            _contribute_presets(row, item, actor, can_assert,
                                presets_mod.KIND_CATALOG, db, user, out)
            out["id"] = row.id
            if include_records:
                out["record"] = api._response(row)
        except ItemError as exc:
            out["error"] = str(exc)
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise
            out["error"] = str(exc.detail)
        results.append(out)

    _batch_audit(db, user, CATALOG, req, actor, results)
    db.commit()
    return {"items": results}
