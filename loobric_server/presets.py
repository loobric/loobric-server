# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Cutting data presets (docs/PRESETS.md, grilled 2026-08-16): contributions
→ a derived, normalized, source-preserved union.

A preset is a RECOMMENDATION WITH A SOURCE, never a fact about the tool. The
server never reconciles: FreeCAD's conservative chipload and a manufacturer's
aggressive chart for the same material are both correct in their contexts, so
both live in the union and consumers filter/rank. Identical values from two
origins are corroboration, kept as two entries.

Rules (all ratified):
- Normal form is preset_schema 1: the G5 engineering values (Vc, Fz,
  vertical-feed ratio, material verbatim, ratified op_type) plus a verbatim
  extras bag. Raw feed/RPM are never persisted.
- Floor: material + at least ONE engineering value. Below it, a contribution
  is refused (the caller keeps its native form client-section-side).
- Identity is (origin, label); a same-origin re-contribution REPLACES its
  predecessor (replace-own). Deleting is a separate deliberate act gated by
  the delete door — agent presets don't hold it.
- `origin` is the recommender (manufacturer, freecad, user, an agent);
  the provenance source records the transcriber (asserted:<actor>) — the
  manufacturer-QA-door split.
- The record's canonical `presets` is MATERIALIZED from its contribution
  rows with source `derived:preset-union`; no door writes it directly.

Assumptions:
- Callers commit; this module only mutates in-session and appends audit rows
  via create_audit_log (the usage-ledger discipline).
- An instance's full union (own + linked catalog entries) is composed at
  READ time by union_for_instance — materializing catalog entries onto the
  instance would go stale when the catalog changes.
"""
from typing import Optional

from sqlalchemy.orm import Session

from loobric_server.audit import create_audit_log
from loobric_server.contract.models import OP_TYPES, PRESET_SCHEMA, PresetEntry
from loobric_server.database.schema import PresetContribution, User

DERIVED_SOURCE = "derived:preset-union"

KIND_CATALOG = "catalog"
KIND_INSTANCE = "instance"


class PresetError(ValueError):
    """A contribution the preset door refuses (floor, vocabulary, shape)."""


def _clean_value_unit(name: str, leaf) -> Optional[dict]:
    """Validate a {value[, unit]} engineering leaf; None passes through."""
    if leaf is None:
        return None
    if not isinstance(leaf, dict) or "value" not in leaf:
        raise PresetError("%s must be a {value[, unit]} object" % name)
    value = leaf["value"]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PresetError("%s value must be a number" % name)
    if value <= 0:
        raise PresetError("%s value must be > 0" % name)
    out = {"value": value}
    unit = leaf.get("unit")
    if unit is not None:
        if not isinstance(unit, str) or not unit.strip():
            raise PresetError("%s unit must be a non-empty string" % name)
        out["unit"] = unit.strip()
    extra = set(leaf) - {"value", "unit"}
    if extra:
        raise PresetError("%s has unknown keys %s" % (name, sorted(extra)))
    return out


def normalize_contribution(payload: dict) -> dict:
    """Validate one contribution against the ratified rules; returns the
    normalized {origin, label, op_type, machine_id, data} shape. Raises
    PresetError with a user-fixable message."""
    if not isinstance(payload, dict):
        raise PresetError("contribution must be an object")

    origin = str(payload.get("origin") or "").strip()
    label = str(payload.get("label") or "").strip()
    if not origin:
        raise PresetError("origin is required — the recommender this preset "
                          "comes from (e.g. 'manufacturer', 'user', a client)")
    if not label:
        raise PresetError("label is required — identity is (origin, label)")

    material = payload.get("material")
    if not isinstance(material, dict) or \
            not str(material.get("name") or "").strip():
        raise PresetError("material {name[, uuid]} is required — verbatim as "
                          "the source states it")
    mat = {"name": str(material["name"]).strip()}
    if material.get("uuid") is not None:
        mat["uuid"] = str(material["uuid"]).strip()
    extra = set(material) - {"name", "uuid"}
    if extra:
        raise PresetError("material has unknown keys %s" % sorted(extra))

    op_type = payload.get("op_type")
    if op_type is not None:
        op_type = str(op_type).strip()
        if op_type not in OP_TYPES:
            raise PresetError(
                "op_type must be one of %s (or absent) — the vocabulary is "
                "ratified, not accreted" % sorted(OP_TYPES))

    vc = _clean_value_unit("vc", payload.get("vc"))
    fz = _clean_value_unit("fz", payload.get("fz"))
    ratio = _clean_value_unit("ratio", payload.get("ratio"))
    if vc is None and fz is None and ratio is None:
        raise PresetError(
            "a preset needs at least one engineering value (vc, fz, or "
            "ratio) — raw feed/RPM are never stored; convert first")

    extras = payload.get("extras")
    if extras is not None and not isinstance(extras, dict):
        raise PresetError("extras must be an object (verbatim key-value bag)")

    machine_id = payload.get("machine_id")
    if machine_id is not None:
        machine_id = str(machine_id).strip() or None

    known = {"origin", "label", "material", "op_type", "vc", "fz", "ratio",
             "extras", "machine_id"}
    unknown = set(payload) - known
    if unknown:
        raise PresetError(
            "unknown keys %s — dimensional/spec extras go INSIDE `extras`"
            % sorted(unknown))

    return {
        "origin": origin, "label": label, "op_type": op_type,
        "machine_id": machine_id,
        "data": {"material": mat, "vc": vc, "fz": fz, "ratio": ratio,
                 "extras": extras},
    }


def contribute(db: Session, user: User, record_kind: str, record_id: str,
               payload: dict, actor: str) -> PresetContribution:
    """Apply one contribution through the audited door: validate, replace-own
    on (origin, label), stamp asserted:<actor>, and rematerialize the
    record's canonical union (caller writes the returned canonical)."""
    normalized = normalize_contribution(payload)
    source = "asserted:%s" % actor

    row = db.query(PresetContribution).filter(
        PresetContribution.user_id == user.id,
        PresetContribution.record_kind == record_kind,
        PresetContribution.record_id == record_id,
        PresetContribution.origin == normalized["origin"],
        PresetContribution.label == normalized["label"]).first()
    operation = "replace" if row is not None else "create"
    if row is None:
        row = PresetContribution(
            record_kind=record_kind, record_id=record_id,
            origin=normalized["origin"], label=normalized["label"],
            user_id=user.id, created_by=user.id, updated_by=user.id)
        db.add(row)
    row.op_type = normalized["op_type"]
    row.machine_id = normalized["machine_id"]
    row.data = normalized["data"]
    row.preset_schema = PRESET_SCHEMA
    row.source = source
    row.updated_by = user.id
    db.flush()
    create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                     entity_type="preset_contribution", entity_id=row.id,
                     changes={"record_kind": record_kind,
                              "record_id": record_id,
                              "origin": row.origin, "label": row.label,
                              "op": operation, "source": source})
    return row


def remove(db: Session, user: User, record_kind: str, record_id: str,
           entry_id: str) -> bool:
    """Delete one contribution (the delete door's deliberate act)."""
    row = db.query(PresetContribution).filter(
        PresetContribution.user_id == user.id,
        PresetContribution.record_kind == record_kind,
        PresetContribution.record_id == record_id,
        PresetContribution.id == entry_id).first()
    if row is None:
        return False
    create_audit_log(session=db, user_id=user.id, operation="DELETE",
                     entity_type="preset_contribution", entity_id=row.id,
                     changes={"record_kind": record_kind,
                              "record_id": record_id,
                              "origin": row.origin, "label": row.label})
    db.delete(row)
    db.flush()          # the rematerialization that follows must not see it
    return True


def _entry_view(row: PresetContribution) -> dict:
    data = row.data or {}
    view = {"id": row.id, "origin": row.origin, "label": row.label,
            "material": data.get("material"),
            "preset_schema": row.preset_schema, "source": row.source,
            "updated_at": row.updated_at.isoformat()
            if row.updated_at is not None else None}
    for key in ("vc", "fz", "ratio", "extras"):
        if data.get(key) is not None:
            view[key] = data[key]
    if row.op_type is not None:
        view["op_type"] = row.op_type
    if row.machine_id is not None:
        view["machine_id"] = row.machine_id
    return view


def record_entries(db: Session, user: User, record_kind: str,
                   record_id: str) -> list[dict]:
    """A record's OWN contribution rows as entry views, oldest first."""
    rows = db.query(PresetContribution).filter(
        PresetContribution.user_id == user.id,
        PresetContribution.record_kind == record_kind,
        PresetContribution.record_id == record_id).order_by(
        PresetContribution.created_at).all()
    return [_entry_view(row) for row in rows]


def materialize(db: Session, user: User, record_row, record_kind: str) -> None:
    """Write-through materialization of the derived union: recompute the
    record's own entries and stamp canonical.presets =
    {value: [...], source: derived:preset-union} (absent when empty).
    Recomputable at any time; called after every contribution/removal so
    reads stay cheap. Callers commit."""
    entries = record_entries(db, user, record_kind, record_row.id)
    for entry in entries:
        PresetEntry.model_validate(entry)      # contract-shape guarantee
    canonical = dict(record_row.canonical or {})
    if entries:
        canonical["presets"] = {"value": entries, "source": DERIVED_SOURCE}
    else:
        canonical.pop("presets", None)
    record_row.canonical = canonical
    record_row.version += 1
    record_row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="DERIVE",
                     entity_type="tool_%s_record" % record_kind,
                     entity_id=record_row.id,
                     changes={"path": "presets", "count": len(entries),
                              "source": DERIVED_SOURCE})


def union_for_instance(db: Session, user: User, instance_row) -> list[dict]:
    """The instance's full union: its own entries plus its linked catalog's,
    each marked with `scope` ("instance" | "catalog"). Composed at read time
    so catalog changes never go stale on the instance."""
    own = record_entries(db, user, KIND_INSTANCE, instance_row.id)
    for entry in own:
        entry["scope"] = KIND_INSTANCE
    catalog_id = (((instance_row.canonical or {}).get("catalog_type_id")
                   or {}).get("value"))
    linked = []
    if catalog_id:
        linked = record_entries(db, user, KIND_CATALOG, catalog_id)
        for entry in linked:
            entry["scope"] = KIND_CATALOG
    return own + linked


def filter_entries(entries: list[dict], origin: Optional[str] = None,
                   material: Optional[str] = None,
                   op_type: Optional[str] = None,
                   machine_id: Optional[str] = None) -> list[dict]:
    """Case-normalized listing filters (material matches on the verbatim
    name, case-insensitively — normalization is deferred, grouping is
    best-effort by design)."""
    out = entries
    if origin is not None:
        out = [e for e in out if e["origin"].lower() == origin.lower()]
    if material is not None:
        out = [e for e in out
               if (e.get("material") or {}).get("name", "").lower()
               == material.lower()]
    if op_type is not None:
        out = [e for e in out if e.get("op_type") == op_type]
    if machine_id is not None:
        out = [e for e in out if e.get("machine_id") == machine_id]
    return out
