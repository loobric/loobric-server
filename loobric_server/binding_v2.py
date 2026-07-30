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
    ToolSetRecord, EntryProposal, MachineSetMap,
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

# Tool-set member states (derived at read time against the machine the set is
# active on — its setup; never stored). MAPPING_PLAN.md §5.2; ratified labels.
SATISFIED = "satisfied"          # mounted, at the claimed number, identity confirmed
MISMOUNTED = "mismounted"        # mounted + confirmed, but at a different number
BLOCKED = "blocked"              # a DIFFERENT confirmed tool occupies the claimed number
REQUESTED = "requested"          # nothing on the machine holds it
PENDING_BIND = "pending bind"    # something mounted, identity unconfirmed

# Note states for entries the active set does not claim (MAPPING_PLAN.md §5.3:
# "interesting, not important" — never counted against readiness).
UNLISTED = "unlisted"            # bound to a tool the set doesn't list
UNIDENTIFIED = "unknown tool"    # unbound entry: something's there, identity unknown


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


# -- setups (machine_set_maps): the transitory machine↔set relationship -------

def active_map_for_machine(db: Session, user_id: str,
                           machine_id: str) -> Optional[MachineSetMap]:
    """The machine's active setup, if any (at most one — DB constraint)."""
    return db.query(MachineSetMap).filter(
        MachineSetMap.user_id == user_id,
        MachineSetMap.machine_id == machine_id,
        MachineSetMap.status == "active").first()


def active_maps_for_set(db: Session, user_id: str,
                        set_id: str) -> List[MachineSetMap]:
    """Every machine this set is currently active on (usually 0 or 1; the
    one-active constraint is per MACHINE, so a set may serve several)."""
    return db.query(MachineSetMap).filter(
        MachineSetMap.user_id == user_id,
        MachineSetMap.tool_set_id == set_id,
        MachineSetMap.status == "active").order_by(
        MachineSetMap.activated_at).all()


# -- tool-set membership reconciliation (MAPPING_PLAN.md §5) -------------------

@dataclass
class MemberState:
    """One member's derived classification against a machine's tool table.

    `number` is the member's durable claim, verbatim from storage (asserted or
    unknown — never substituted). `observed` is the relevant entry's observed
    tool_number Field, when an entry is involved. Severity falls out of state:
    anything but SATISFIED needs attention (MAPPING_PLAN.md §5.3)."""
    tool_record_id: str
    state: Optional[str]          # SATISFIED|MISMOUNTED|BLOCKED|REQUESTED|PENDING_BIND|None
    number: dict                  # the claim: provenance-tagged Field, asserted/unknown
    observed: Optional[dict] = None   # the entry's observed number Field, if any
    entry_id: Optional[str] = None    # the entry involved (for BLOCKED: the blocker)


@dataclass
class ReconcileResult:
    members: List[MemberState]
    ambiguities: List[Dict[str, Any]]
    machine_bound: bool


def _entry_number(entry: EntryRow) -> dict:
    """The entry's observed tool_number Field, verbatim (value +
    `observed:<client>@<machine>` provenance). Falls back to an honest unknown
    when the entry has no number."""
    return dict((entry.canonical or {}).get("tool_number")
                or {"value": None, "source": UNKNOWN})


def reconcile_set_membership(db: Session, set_row,
                             machine_id: Optional[str]) -> ReconcileResult:
    """Classify each member of a ToolSet against `machine_id`'s tool-table
    entries. Pure: computes at read time and mutates NOTHING — asserted member
    numbers are durable and only ever change via an assert (MAPPING_PLAN.md
    §5.1); observation is returned alongside, never written over the claim.

    `machine_id` comes from the set's active setup (machine_set_maps), passed
    in by the caller. None → members returned verbatim with no state
    (`machine_bound=False`): an unmapped set has nothing to reconcile against,
    so every number is simply its claim.

    Per member (instance I, claimed number A):

    - entry bound to I, at A (or A unknown)   → **satisfied**
    - entry bound to I, at P ≠ A              → **mismounted** (observed=P)
    - no bound entry, open proposal names I    → **pending bind**
    - no bound entry, unbound entry sits at A  → **pending bind** (something is
      mounted at the claimed number; identity unsettled — indistinguishable
      from blocked until someone binds)
    - no bound entry, entry at A bound to J≠I  → **blocked** (the dangerous
      case: posted G-code calling A would run the wrong tool)
    - otherwise                                → **requested**

    Two members resolving to one entry is surfaced under `ambiguities`, never
    guessed away. (The old `number_collision` ambiguity is superseded by the
    member-level BLOCKED state.)
    """
    members_canon = (set_row.canonical or {}).get("members") or []

    def _claim(m: dict) -> dict:
        return dict(m.get("number") or {"value": None, "source": UNKNOWN})

    if not machine_id:
        return ReconcileResult(
            members=[MemberState(m["tool_record_id"], None, _claim(m))
                     for m in members_canon],
            ambiguities=[], machine_bound=False)

    entries = db.query(EntryRow).filter(
        EntryRow.user_id == set_row.user_id,
        EntryRow.machine_id == machine_id).all()
    entry_by_id = {e.id: e for e in entries}
    bound_by_instance = {e.bound_instance_id: e for e in entries
                         if e.bound_instance_id is not None}
    by_number: Dict[Any, EntryRow] = {}
    for e in entries:
        tn = (e.canonical.get("tool_number") or {}).get("value")
        if tn is not None:
            by_number.setdefault(tn, e)

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
        claim = _claim(m)
        claimed = claim.get("value")
        entry = bound_by_instance.get(iid)
        if entry is not None:
            observed = _entry_number(entry)
            state = (SATISFIED if claimed is None or claimed == observed.get("value")
                     else MISMOUNTED)
            out.append(MemberState(iid, state, claim, observed, entry.id))
            entry_claims.setdefault(entry.id, []).append(iid)
            continue
        if iid in proposal_entry_by_instance:
            eid = proposal_entry_by_instance[iid]
            entry = entry_by_id.get(eid)
            observed = _entry_number(entry) if entry is not None else None
            out.append(MemberState(iid, PENDING_BIND, claim, observed, eid))
            entry_claims.setdefault(eid, []).append(iid)
            continue
        at_claimed = by_number.get(claimed) if claimed is not None else None
        if at_claimed is not None:
            if at_claimed.bound_instance_id is None:
                out.append(MemberState(iid, PENDING_BIND, claim,
                                       _entry_number(at_claimed), at_claimed.id))
                entry_claims.setdefault(at_claimed.id, []).append(iid)
            else:
                out.append(MemberState(iid, BLOCKED, claim,
                                       _entry_number(at_claimed), at_claimed.id))
            continue
        out.append(MemberState(iid, REQUESTED, claim, None, None))

    ambiguities: List[Dict[str, Any]] = []
    for eid, claimants in entry_claims.items():
        if len(claimants) > 1:
            ambiguities.append({"kind": "multiple_members_one_entry",
                                "entry_id": eid, "tool_record_ids": claimants})

    return ReconcileResult(members=out, ambiguities=ambiguities, machine_bound=True)


# -- request-aware binding bridge (ROUNDTRIP_FIXES Fix 2 / S3) -----------------

def requested_members_by_number(
        db: Session, user: User, machine_id: str) -> Dict[Any, Tuple[str, Optional[str]]]:
    """Index the machine's active set's REQUESTED members by their asserted
    claimed tool_number → (instance_id, set_name).

    Resolves through the machine's active setup (machine_set_maps): only the
    active set's claims can auto-bind a freshly mounted tool. Members whose
    instance is UNBOUND on this machine (`requested`, or `pending bind` — an
    unbound entry already sits at the claimed number) AND that carry an
    *asserted* number are indexed — that number is the auto-bind signal (S3.1).
    Pending members are included because the proposal guards live at the entry
    (`propose_for_requested_entry` skips bound entries and open proposals);
    excluding them would starve the bridge for exactly the entry the claim
    points at. A member with an unknown number has nothing to tie an entry to
    and is left to the geometry path."""
    out: Dict[Any, Tuple[str, Optional[str]]] = {}
    map_row = active_map_for_machine(db, user.id, machine_id)
    if map_row is None:
        return out
    set_row = db.query(ToolSetRecord).filter(
        ToolSetRecord.id == map_row.tool_set_id,
        ToolSetRecord.user_id == user.id).first()
    if set_row is None:
        return out
    name = (set_row.canonical.get("name") or {}).get("value")
    for ms in reconcile_set_membership(db, set_row, machine_id).members:
        if ms.state not in (REQUESTED, PENDING_BIND):
            continue
        num = (ms.number or {}).get("value")
        if num is None:
            continue
        if Provenance.kind((ms.number or {}).get("source") or UNKNOWN) != Provenance.ASSERTED:
            continue
        out.setdefault(num, (ms.tool_record_id, name))
    return out


def bridge_requested_claims(db: Session, user: User, machine_id: str) -> int:
    """Open number-match proposals for existing unbound entries that an active
    set's requested members now claim (MAPPING_PLAN.md slice 0b).

    The push path (`sync_entries`) bridges machine-first ordering: entry
    arrives, claim already exists. This bridges the CAM-first ordering — claim
    asserted (or setup activated) AFTER the entry already exists — which would
    otherwise stall until the machine's next sync. Same guards, same elevated
    confidence, via `propose_for_requested_entry`. Caller commits. Returns the
    number of proposals opened."""
    requested = requested_members_by_number(db, user, machine_id)
    if not requested:
        return 0
    opened = 0
    for entry in db.query(EntryRow).filter(
            EntryRow.user_id == user.id,
            EntryRow.machine_id == machine_id,
            EntryRow.bound_instance_id.is_(None)).all():
        tn = (entry.canonical.get("tool_number") or {}).get("value")
        if tn is None or tn not in requested:
            continue
        if propose_for_requested_entry(db, user, entry, requested) is not None:
            opened += 1
    return opened


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


# -- the machine reconciliation view (MAPPING_PLAN.md §5.4) --------------------

def reconcile_machine(db: Session, user: User, machine_id: str) -> Dict[str, Any]:
    """The setup's derived view for one machine: claims (every line the active
    set asserts, with state) and notes (table rows the set doesn't claim).
    Computed entirely at read time; nothing is stored.

    The headline is `ready` — every claim satisfied: mounted, at the claimed
    number, identity confirmed. Notes never count against readiness
    (MAPPING_PLAN.md §5.3: severity is derived from direction, not stored).
    With no active setup, `active` is False and there is nothing to reconcile.
    """
    map_row = active_map_for_machine(db, user.id, machine_id)
    if map_row is None:
        return {"machine_id": machine_id, "active": False, "setup_id": None,
                "tool_set_id": None, "tool_set_name": None, "ready": None,
                "claims": [], "notes": [],
                "attention": {"important": 0, "notes": 0}}

    set_row = db.query(ToolSetRecord).filter(
        ToolSetRecord.id == map_row.tool_set_id,
        ToolSetRecord.user_id == user.id).first()
    members_result = (reconcile_set_membership(db, set_row, machine_id)
                      if set_row is not None
                      else ReconcileResult(members=[], ambiguities=[],
                                           machine_bound=True))

    entries = db.query(EntryRow).filter(
        EntryRow.user_id == user.id,
        EntryRow.machine_id == machine_id).all()
    entry_by_id = {e.id: e for e in entries}

    # Instance display names, resolved in one query: the members' instances
    # plus whatever non-member tools are bound on the table.
    wanted = {ms.tool_record_id for ms in members_result.members}
    wanted.update(e.bound_instance_id for e in entries
                  if e.bound_instance_id is not None)
    names: Dict[str, Optional[str]] = {}
    if wanted:
        for inst in db.query(InstanceRow).filter(InstanceRow.id.in_(wanted)).all():
            names[inst.id] = (inst.canonical.get("name") or {}).get("value")

    claims: List[Dict[str, Any]] = []
    consumed: set = set()
    for ms in members_result.members:
        claim = {
            "tool_record_id": ms.tool_record_id,
            "name": names.get(ms.tool_record_id),
            "number": ms.number,
            "observed": ms.observed,
            "state": ms.state,
            "entry_id": ms.entry_id,
        }
        if ms.state == BLOCKED and ms.entry_id in entry_by_id:
            blocker = entry_by_id[ms.entry_id].bound_instance_id
            claim["blocked_by"] = {"tool_record_id": blocker,
                                   "name": names.get(blocker)}
        claims.append(claim)
        # SATISFIED/MISMOUNTED consume their bound entry; PENDING_BIND consumes
        # the entry awaiting identity. BLOCKED does NOT consume the blocker —
        # the same physical row honestly appears again below as an unlisted note.
        if ms.state in (SATISFIED, MISMOUNTED, PENDING_BIND) and ms.entry_id:
            consumed.add(ms.entry_id)

    notes: List[Dict[str, Any]] = []
    for e in entries:
        if e.id in consumed:
            continue
        number = _entry_number(e)
        description = (e.canonical.get("description") or {}).get("value")
        if e.bound_instance_id is not None:
            notes.append({"entry_id": e.id, "number": number,
                          "state": UNLISTED,
                          "tool_record_id": e.bound_instance_id,
                          "name": names.get(e.bound_instance_id),
                          "description": description})
        else:
            notes.append({"entry_id": e.id, "number": number,
                          "state": UNIDENTIFIED, "tool_record_id": None,
                          "name": None, "description": description})

    important = sum(1 for c in claims if c["state"] != SATISFIED)
    return {
        "machine_id": machine_id,
        "active": True,
        "setup_id": map_row.id,
        "tool_set_id": map_row.tool_set_id,
        "tool_set_name": ((set_row.canonical.get("name") or {}).get("value")
                          if set_row is not None else None),
        "ready": important == 0,
        "claims": claims,
        "notes": notes,
        "ambiguities": members_result.ambiguities,
        "attention": {"important": important, "notes": len(notes)},
    }
