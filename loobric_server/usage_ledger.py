# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""The usage ledger (docs/TOOL_SCHEMA.md §7.8): counter observations →
attributed contributions → a derived lifetime total.

A controller's tool-life counter is per-machine and resettable, so no
observation can ever be a tool's total. Each `usage_hours` observation on an
entry is turned into a DELTA against that entry's previous observation:

- Δ > 0, binding confirmed and unchanged across the interval → a
  contribution row credited to the bound instance
- Δ < 0 → a counter reset: re-baseline, contribute nothing
- Δ > 0 but unbound / binding changed → ORPHANED (instance_id null),
  recorded and surfaced, never guessed onto an instance
- first observation → baseline only (pre-Loobric hours are deliberately
  not invented; a human starting-balance assert is a deferred feature)

Counters are deltas, never gauges. The instance's lifetime total is written
back as canonical `usage.hours` with source `derived:usage-ledger` — no
door writes it directly; it decomposes into the per-machine contributions,
and that decomposition IS the provenance.

Assumptions:
- Callers pass the entry ROW BEFORE writing the new canonical usage_hours
  leaf — the previous counter reading is read off entry.canonical here.
- Callers commit; this module only appends and mutates in-session (the
  binding_v2 discipline). Audit rows for contributions ride the caller's
  request audit trail via create_audit_log (which commits as usual).
- v1 metric is hours with unit "h" (a controller reporting minutes converts
  client-side; see docs/HOWTO_BUILD_A_CLIENT.md).
"""
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from loobric_server.audit import create_audit_log
from loobric_server.database.schema import (
    ToolInstanceRecord, ToolTableEntryRecord, UsageLedger, User,
)

METRIC_HOURS = "hours"
HOURS_UNIT = "h"
DERIVED_SOURCE = "derived:usage-ledger"


class UsageError(ValueError):
    """A usage observation the ledger refuses (bad unit, bad value)."""


def ingest_usage_observation(db: Session, user: User,
                             entry: ToolTableEntryRecord,
                             new_value, unit: Optional[str],
                             source: str, machine_id: str) -> dict:
    """Apply the §7.8 delta rules for one usage_hours observation.

    Call BEFORE the observation is written to entry.canonical. Returns
    {"disposition": "baseline"|"reset"|"noop"|"contribution"|"orphan",
    "amount": float|None}; appends at most one ledger row. Always advances
    the baseline (counter value via the caller's canonical write; binding
    endpoint via usage_baseline_instance_id here).
    """
    if unit is not None and unit != HOURS_UNIT:
        raise UsageError(
            "usage_hours must be in %r (got %r) — convert client-side"
            % (HOURS_UNIT, unit))
    if not isinstance(new_value, (int, float)) or isinstance(new_value, bool):
        raise UsageError("usage_hours value must be a number")
    if new_value < 0:
        raise UsageError("usage_hours value must be >= 0")

    previous = ((entry.canonical or {}).get("usage_hours") or {}).get("value")
    bound = entry.bound_instance_id
    baseline_instance = entry.usage_baseline_instance_id
    entry.usage_baseline_instance_id = bound

    if previous is None or not isinstance(previous, (int, float)):
        return {"disposition": "baseline", "amount": None}
    delta = new_value - previous
    if delta < 0:
        return {"disposition": "reset", "amount": None}
    if delta == 0:
        return {"disposition": "noop", "amount": None}

    contributes = bound is not None and bound == baseline_instance
    row = UsageLedger(
        entry_id=entry.id, machine_id=machine_id,
        instance_id=bound if contributes else None,
        metric=METRIC_HOURS, amount=delta, counter_value=new_value,
        source=source,
        user_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(row)
    db.flush()
    disposition = "contribution" if contributes else "orphan"
    create_audit_log(session=db, user_id=user.id, operation="USAGE",
                     entity_type="usage_ledger", entity_id=row.id,
                     changes={"entry_id": entry.id, "amount": delta,
                              "instance_id": row.instance_id,
                              "disposition": disposition, "source": source})
    if contributes:
        recompute_instance_usage(db, user, bound)
    return {"disposition": disposition, "amount": delta}


def instance_total(db: Session, user: User, instance_id: str) -> float:
    """SUM of the instance's hour contributions."""
    total = db.query(func.sum(UsageLedger.amount)).filter(
        UsageLedger.user_id == user.id,
        UsageLedger.instance_id == instance_id,
        UsageLedger.metric == METRIC_HOURS).scalar()
    return float(total or 0.0)


def recompute_instance_usage(db: Session, user: User,
                             instance_id: str) -> None:
    """Write-through materialization of the derived total: recompute the sum
    and stamp canonical usage.hours = {value, "h", derived:usage-ledger} on
    the instance. Recomputable at any time; called after every contribution
    so reads stay cheap."""
    instance = db.query(ToolInstanceRecord).filter(
        ToolInstanceRecord.id == instance_id,
        ToolInstanceRecord.user_id == user.id).first()
    if instance is None:
        return
    total = round(instance_total(db, user, instance_id), 6)
    canonical = dict(instance.canonical or {})
    usage = dict(canonical.get("usage") or {})
    usage["hours"] = {"value": total, "unit": HOURS_UNIT,
                      "source": DERIVED_SOURCE}
    canonical["usage"] = usage
    instance.canonical = canonical
    instance.version += 1
    instance.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="DERIVE",
                     entity_type="tool_instance_record",
                     entity_id=instance_id,
                     changes={"path": "usage.hours", "value": total,
                              "source": DERIVED_SOURCE})


def contributions(db: Session, user: User, instance_id: str) -> list:
    """The decomposition: the instance's contribution rows, oldest first —
    '37.4 = 25.3 observed:haas@vf2 + 12.1 observed:haas@vf3'."""
    return db.query(UsageLedger).filter(
        UsageLedger.user_id == user.id,
        UsageLedger.instance_id == instance_id,
        UsageLedger.metric == METRIC_HOURS).order_by(
        UsageLedger.created_at).all()


def entry_rows(db: Session, user: User, entry_id: str) -> list:
    """All ledger rows for an entry — contributions AND orphans."""
    return db.query(UsageLedger).filter(
        UsageLedger.user_id == user.id,
        UsageLedger.entry_id == entry_id).order_by(
        UsageLedger.created_at).all()


def orphans_by_entry(db: Session, user: User) -> list:
    """Grouped orphaned hours for surfacing: [{entry_id, machine_id, hours,
    since}] — recorded, awaiting a human, never guessed."""
    rows = db.query(
        UsageLedger.entry_id, UsageLedger.machine_id,
        func.sum(UsageLedger.amount), func.min(UsageLedger.created_at),
    ).filter(
        UsageLedger.user_id == user.id,
        UsageLedger.instance_id.is_(None),
        UsageLedger.metric == METRIC_HOURS,
    ).group_by(UsageLedger.entry_id, UsageLedger.machine_id).all()
    return [{"entry_id": entry_id, "machine_id": machine_id,
             "hours": round(float(hours), 6),
             "since": since.isoformat() if since is not None else None}
            for entry_id, machine_id, hours, since in rows]
