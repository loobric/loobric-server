# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Binding engine for the sectioned schema — proposes which instance an unbound
entry holds, for human review (docs/TOOL_SCHEMA.md; successor to binding.py).

The entry OBSERVED a tool in it (a diameter); the engine proposes the best-
matching existing instance. It never installs anything — its only output is
EntryProposal rows. A diameter agreement (within 1%) is, as before, sufficient
to propose; name matching is left for when entries carry an observed description.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from loobric_server.database.schema import (
    User, ToolInstanceRecord as InstanceRow, ToolTableEntryRecord as EntryRow,
    ToolSetRecord, EntryProposal,
)
from loobric_server.audit import create_audit_log
from loobric_server.contract import Provenance, UNKNOWN

PROPOSAL_THRESHOLD = 0.5
DIAMETER_WEIGHT = 0.55
DIAMETER_TOLERANCE = 0.01  # relative
# A new entry whose observed tool_number matches a machine-bound set's requested
# member is the strongest binding signal (the operator honored the preferred
# pocket); it short-circuits the diameter threshold. See ROUNDTRIP_FIXES S3.
REQUESTED_CONFIDENCE = 0.95

# Tool-set member states (derived at read time for a machine-bound set; never
# stored). See docs/UBIQUITOUS_LANGUAGE.md and docs/ROUNDTRIP.md.
LOADED = "loaded"
REQUESTED = "requested"
PENDING_BIND = "pending bind"


def _diameter(canonical: dict, *path: str):
    node = canonical or {}
    for p in path:
        node = (node or {}).get(p) or {}
    return node.get("value")


def score(entry: EntryRow, instance: InstanceRow) -> Tuple[float, str]:
    """How plausibly `instance` is the tool observed in `entry`."""
    entry_dia = _diameter(entry.canonical, "offsets", "diameter")
    inst_dia = _diameter(instance.canonical, "geometry", "diameter")
    if entry_dia and inst_dia and \
            abs(entry_dia - inst_dia) <= DIAMETER_TOLERANCE * max(entry_dia, inst_dia):
        return DIAMETER_WEIGHT, "diameter matches (%s)" % inst_dia
    return 0.0, "no overlap"


def propose_for_entry(db: Session, user: User, entry: EntryRow) -> Optional[EntryProposal]:
    """Create the best-match open proposal for an unbound entry, if any. Caller
    commits. Returns None when the entry is bound, already has an open proposal,
    or nothing clears the threshold."""
    if entry.bound_instance_id is not None:
        return None
    if db.query(EntryProposal).filter(
            EntryProposal.entry_id == entry.id, EntryProposal.status == "open").first():
        return None
    rejected = {p.proposed_instance_id for p in db.query(EntryProposal).filter(
        EntryProposal.entry_id == entry.id, EntryProposal.status == "rejected").all()}

    best = None  # (score, reason, instance)
    for inst in db.query(InstanceRow).filter(InstanceRow.user_id == user.id).all():
        if inst.id in rejected:
            continue
        s, reason = score(entry, inst)
        if s >= PROPOSAL_THRESHOLD and (best is None or s > best[0]):
            best = (s, reason, inst)
    if best is None:
        return None

    s, reason, inst = best
    proposal = EntryProposal(
        entry_id=entry.id, proposed_instance_id=inst.id,
        confidence=round(s, 3), reason=reason, status="open",
        user_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(proposal)
    db.flush()
    create_audit_log(session=db, user_id=user.id, operation="PROPOSE",
                     entity_type="entry_proposal", entity_id=proposal.id,
                     changes={"entry_id": entry.id, "instance_id": inst.id,
                              "confidence": proposal.confidence})
    return proposal


def close_open_proposal_on_bind(db: Session, user: User, entry_id: str,
                                bound_instance_id: str) -> None:
    """When a entry is bound explicitly, resolve its open proposal: confirmed if
    it named the bound instance, else rejected (the human chose a different
    tool; don't propose that pair again). Caller commits."""
    proposal = db.query(EntryProposal).filter(
        EntryProposal.entry_id == entry_id, EntryProposal.status == "open").first()
    if proposal is None:
        return
    proposal.status = ("confirmed" if proposal.proposed_instance_id == bound_instance_id
                       else "rejected")
    proposal.version += 1
    proposal.updated_by = user.id


# -- tool-set membership reconciliation (ROUNDTRIP_FIXES Fix 2 / S1) ----------

@dataclass
class MemberState:
    """One member's derived classification against the machine's tool table."""
    tool_record_id: str
    state: Optional[str]          # LOADED | REQUESTED | PENDING_BIND | None
    number: dict                  # provenance-tagged Field; observed for loaded
    entry_id: Optional[str] = None


@dataclass
class ReconcileResult:
    members: List[MemberState]
    ambiguities: List[Dict[str, Any]]
    machine_bound: bool


def _entry_number(entry: EntryRow) -> dict:
    """The entry's observed tool_number Field, inherited verbatim (value +
    `observed:<client>@<machine>` provenance) — the inheritance TOOL_SCHEMA.md
    §8 promises. Falls back to an honest unknown when the entry has no number."""
    return dict((entry.canonical or {}).get("tool_number")
                or {"value": None, "source": UNKNOWN})


def reconcile_set_membership(db: Session, set_row) -> ReconcileResult:
    """Classify each member of a machine-bound ToolSet against its machine's
    tool-table entries, deriving per-member state and inheriting observed tool
    numbers for loaded members. Pure: computes at read time and mutates nothing
    (the GET path uses the result to enrich its response; the caller would commit
    only if it chose to persist).

    For a set with no `machine_id`, members are returned verbatim with no state
    (`machine_bound=False`). Otherwise each member's instance (`tool_record_id`)
    is resolved against the machine's entries:

    - **loaded** — its instance is the `bound_instance_id` of an entry; the
      member's `number` becomes that entry's observed `tool_number`.
    - **pending bind** — not bound, but an open EntryProposal on an entry of this
      machine names the instance; the entry's observed number is surfaced, the
      binding unconfirmed.
    - **requested** — neither; the member and its asserted/unknown number are
      preserved (a load request awaiting the operator).

    Ambiguities (two members resolving to one entry; an observed number colliding
    with another member's asserted number) are surfaced, never silently
    renumbered — observation > assertion is not resolved by guessing.
    """
    members_canon = (set_row.canonical or {}).get("members") or []

    if not set_row.machine_id:
        return ReconcileResult(
            members=[MemberState(m["tool_record_id"], None,
                                 m.get("number") or {"value": None, "source": UNKNOWN})
                     for m in members_canon],
            ambiguities=[], machine_bound=False)

    entries = db.query(EntryRow).filter(
        EntryRow.user_id == set_row.user_id,
        EntryRow.machine_id == set_row.machine_id).all()
    entry_by_id = {e.id: e for e in entries}
    bound_by_instance = {e.bound_instance_id: e for e in entries
                         if e.bound_instance_id is not None}

    # Open proposals on this machine's entries, indexed by the instance they name.
    proposal_entry_by_instance: Dict[str, str] = {}
    if entry_by_id:
        for p in db.query(EntryProposal).filter(
                EntryProposal.status == "open",
                EntryProposal.entry_id.in_(entry_by_id.keys())).all():
            proposal_entry_by_instance.setdefault(p.proposed_instance_id, p.entry_id)

    out: List[MemberState] = []
    entry_claims: Dict[str, List[str]] = {}
    for m in members_canon:
        iid = m["tool_record_id"]
        asserted = m.get("number") or {"value": None, "source": UNKNOWN}
        entry = bound_by_instance.get(iid)
        if entry is not None:
            out.append(MemberState(iid, LOADED, _entry_number(entry), entry.id))
            entry_claims.setdefault(entry.id, []).append(iid)
        elif iid in proposal_entry_by_instance:
            eid = proposal_entry_by_instance[iid]
            entry = entry_by_id.get(eid)
            number = _entry_number(entry) if entry is not None else asserted
            out.append(MemberState(iid, PENDING_BIND, number, eid))
            entry_claims.setdefault(eid, []).append(iid)
        else:
            out.append(MemberState(iid, REQUESTED, asserted, None))

    ambiguities: List[Dict[str, Any]] = []
    for eid, claimants in entry_claims.items():
        if len(claimants) > 1:
            ambiguities.append({"kind": "multiple_members_one_entry",
                                "entry_id": eid, "tool_record_ids": claimants})

    # An observed (loaded/pending) number landing on the same value a different
    # member asserts as its preference: surface, don't renumber.
    observed_at: Dict[Any, List[str]] = {}
    asserted_at: Dict[Any, List[str]] = {}
    for ms in out:
        val = (ms.number or {}).get("value")
        if val is None:
            continue
        kind = Provenance.kind((ms.number or {}).get("source") or UNKNOWN)
        if ms.state in (LOADED, PENDING_BIND):
            observed_at.setdefault(val, []).append(ms.tool_record_id)
        elif ms.state == REQUESTED and kind == Provenance.ASSERTED:
            asserted_at.setdefault(val, []).append(ms.tool_record_id)
    for val, observers in observed_at.items():
        if val in asserted_at:
            ambiguities.append({"kind": "number_collision", "number": val,
                                "observed_members": observers,
                                "asserted_members": asserted_at[val]})

    return ReconcileResult(members=out, ambiguities=ambiguities, machine_bound=True)


# -- request-aware binding bridge (ROUNDTRIP_FIXES Fix 2 / S3) -----------------

def requested_members_by_number(
        db: Session, user: User, machine_id: str) -> Dict[Any, Tuple[str, Optional[str]]]:
    """Index every machine-bound set's REQUESTED members by their asserted
    preferred tool_number → (instance_id, set_name).

    Reuses `reconcile_set_membership` so request resolution is not re-derived:
    only members the engine classifies as `requested` AND that carry an
    *asserted* preferred number are indexed — that number is the auto-bind signal
    (S3.1). A requested member with an unknown number has nothing to tie an entry
    to and is left to the geometry path. First writer wins on a duplicate number."""
    out: Dict[Any, Tuple[str, Optional[str]]] = {}
    for set_row in db.query(ToolSetRecord).filter(
            ToolSetRecord.user_id == user.id,
            ToolSetRecord.machine_id == machine_id).all():
        name = (set_row.canonical.get("name") or {}).get("value")
        for ms in reconcile_set_membership(db, set_row).members:
            if ms.state != REQUESTED:
                continue
            num = (ms.number or {}).get("value")
            if num is None:
                continue
            if Provenance.kind((ms.number or {}).get("source") or UNKNOWN) != Provenance.ASSERTED:
                continue
            out.setdefault(num, (ms.tool_record_id, name))
    return out


def propose_for_requested_entry(
        db: Session, user: User, entry: EntryRow,
        requested: Dict[Any, Tuple[str, Optional[str]]]) -> Optional[EntryProposal]:
    """Bridge a freshly-mounted tool to its load request. If the new entry's
    observed `tool_number` equals a requested member's asserted preferred number,
    open an elevated-confidence proposal naming that member's instance — the
    request short-circuits the diameter threshold (S3.1). With no such match it
    falls back to the geometry heuristic (`propose_for_entry`, S3.2), i.e. behaves
    exactly as today. Honors the same guards: skip if bound, if an open proposal
    exists, or if this (entry, instance) pair was already rejected. Caller commits."""
    if entry.bound_instance_id is not None:
        return None
    if db.query(EntryProposal).filter(
            EntryProposal.entry_id == entry.id, EntryProposal.status == "open").first():
        return None

    tn = (entry.canonical.get("tool_number") or {}).get("value")
    match = requested.get(tn) if tn is not None else None
    if match is None:
        return propose_for_entry(db, user, entry)        # nothing ties it → geometry

    instance_id, set_name = match
    rejected = {p.proposed_instance_id for p in db.query(EntryProposal).filter(
        EntryProposal.entry_id == entry.id, EntryProposal.status == "rejected").all()}
    if instance_id in rejected:                          # never re-propose a rejected pair
        return propose_for_entry(db, user, entry)

    reason = "requested via set %s" % set_name if set_name else "requested via set"
    proposal = EntryProposal(
        entry_id=entry.id, proposed_instance_id=instance_id,
        confidence=round(REQUESTED_CONFIDENCE, 3), reason=reason, status="open",
        user_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(proposal)
    db.flush()
    create_audit_log(session=db, user_id=user.id, operation="PROPOSE",
                     entity_type="entry_proposal", entity_id=proposal.id,
                     changes={"entry_id": entry.id, "instance_id": instance_id,
                              "confidence": proposal.confidence, "requested": True})
    return proposal
