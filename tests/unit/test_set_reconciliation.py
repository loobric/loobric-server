# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for reconcile_set_membership (MAPPING_PLAN.md §5.2).

The engine classifies each member of a set against a machine's tool-table
entries at read time: satisfied (bound at the claimed number), mismounted
(bound elsewhere), blocked (a different confirmed tool at the claimed number),
pending bind (identity unsettled), requested (nothing holds it). The stored
claim (`number`) is returned verbatim in every state — observation rides in
`observed`, it never overwrites the claim. With machine_id=None (no active
setup) members are returned verbatim with no state.
"""
import pytest

from loobric_server.binding_v2 import (
    reconcile_set_membership,
    SATISFIED, MISMOUNTED, BLOCKED, REQUESTED, PENDING_BIND,
)
from loobric_server.database.schema import (
    ToolSetRecord, ToolTableEntryRecord, EntryProposal,
)
from loobric_server.contract import Provenance, UNKNOWN

UID = "user-recon"
MACHINE = "m-recon"


def _entry(db, tool_number, bound=None):
    src = Provenance.observed("linuxcnc", "millstone")
    canonical = {
        "tool_number": {"value": tool_number, "source": src},
        "bound_instance_id": (
            {"value": bound, "source": Provenance.asserted("human@inbox")}
            if bound else {"value": None, "source": UNKNOWN}),
        "offsets": {},
    }
    row = ToolTableEntryRecord(
        machine_id=MACHINE, bound_instance_id=bound, canonical=canonical,
        clients={}, user_id=UID, created_by=UID, updated_by=UID)
    db.add(row)
    db.flush()
    return row


def _member(iid, number=None):
    num = ({"value": number, "source": Provenance.asserted("freecad")}
           if number is not None else {"value": None, "source": UNKNOWN})
    return {"tool_record_id": iid, "number": num}


def _set(db, members):
    canonical = {
        "name": {"value": "millstone", "source": Provenance.asserted("freecad")},
        "members": members,
    }
    row = ToolSetRecord(
        canonical=canonical, clients={},
        user_id=UID, created_by=UID, updated_by=UID)
    db.add(row)
    db.flush()
    return row


def _open_proposal(db, entry, instance_id):
    p = EntryProposal(
        entry_id=entry.id, proposed_instance_id=instance_id, confidence=0.9,
        reason="requested via set", status="open",
        user_id=UID, created_by=UID, updated_by=UID)
    db.add(p)
    db.flush()
    return p


@pytest.mark.unit
def test_satisfied_member_keeps_claim_and_carries_observed(db_session):
    entry = _entry(db_session, tool_number=5, bound="inst-A")
    s = _set(db_session, [_member("inst-A", number=5)])

    result = reconcile_set_membership(db_session, s, MACHINE)

    assert result.machine_bound is True
    (m,) = result.members
    assert m.state == SATISFIED
    assert m.number["value"] == 5                       # the claim, untouched
    assert Provenance.kind(m.number["source"]) == Provenance.ASSERTED
    assert m.observed["value"] == 5                     # the observation, alongside
    assert m.observed["source"].startswith("observed:")
    assert m.entry_id == entry.id
    assert result.ambiguities == []


@pytest.mark.unit
def test_member_with_no_claim_bound_anywhere_is_satisfied(db_session):
    entry = _entry(db_session, tool_number=7, bound="inst-A")
    s = _set(db_session, [_member("inst-A")])           # no claimed number

    (m,) = reconcile_set_membership(db_session, s, MACHINE).members

    assert m.state == SATISFIED
    assert m.number["value"] is None                    # claim honestly unknown
    assert m.observed["value"] == 7


@pytest.mark.unit
def test_mismounted_member_keeps_claim_and_shows_observed(db_session):
    entry = _entry(db_session, tool_number=9, bound="inst-A")
    s = _set(db_session, [_member("inst-A", number=14)])

    (m,) = reconcile_set_membership(db_session, s, MACHINE).members

    assert m.state == MISMOUNTED
    assert m.number["value"] == 14                      # CAM's claim survives
    assert Provenance.kind(m.number["source"]) == Provenance.ASSERTED
    assert m.observed["value"] == 9                     # machine truth alongside
    assert m.entry_id == entry.id


@pytest.mark.unit
def test_blocked_when_claimed_number_held_by_different_confirmed_tool(db_session):
    blocker = _entry(db_session, tool_number=5, bound="inst-OTHER")
    s = _set(db_session, [_member("inst-A", number=5)])

    (m,) = reconcile_set_membership(db_session, s, MACHINE).members

    assert m.state == BLOCKED
    assert m.number["value"] == 5
    assert m.observed["value"] == 5                     # the occupied slot
    assert m.entry_id == blocker.id                     # points at the blocker


@pytest.mark.unit
def test_requested_member_preserved_with_asserted_number(db_session):
    _entry(db_session, tool_number=5, bound="inst-A")
    s = _set(db_session, [_member("inst-A"), _member("inst-NEW", number=18)])

    result = reconcile_set_membership(db_session, s, MACHINE)

    states = {m.tool_record_id: m for m in result.members}
    assert states["inst-A"].state == SATISFIED
    req = states["inst-NEW"]
    assert req.state == REQUESTED
    assert req.number["value"] == 18                 # asserted claim preserved
    assert Provenance.kind(req.number["source"]) == Provenance.ASSERTED
    assert req.observed is None
    assert req.entry_id is None


@pytest.mark.unit
def test_requested_member_with_no_number_stays_unknown(db_session):
    s = _set(db_session, [_member("inst-NEW")])

    (m,) = reconcile_set_membership(db_session, s, MACHINE).members

    assert m.state == REQUESTED
    assert m.number["value"] is None
    assert m.number["source"] == UNKNOWN


@pytest.mark.unit
def test_pending_bind_when_open_proposal_names_instance(db_session):
    entry = _entry(db_session, tool_number=18)          # unbound, observed number 18
    _open_proposal(db_session, entry, "inst-NEW")
    s = _set(db_session, [_member("inst-NEW", number=18)])

    (m,) = reconcile_set_membership(db_session, s, MACHINE).members

    assert m.state == PENDING_BIND
    assert m.number["value"] == 18                      # claim untouched
    assert Provenance.kind(m.number["source"]) == Provenance.ASSERTED
    assert m.observed["value"] == 18                    # from the entry
    assert m.observed["source"].startswith("observed:")
    assert m.entry_id == entry.id


@pytest.mark.unit
def test_pending_bind_when_unbound_entry_sits_at_claimed_number(db_session):
    """An unbound entry at the claimed number with NO proposal is still
    identity-pending — indistinguishable from blocked until someone binds
    (MAPPING_PLAN.md §5.2). Never guessed into a flavor."""
    entry = _entry(db_session, tool_number=12)          # unbound, no proposal
    s = _set(db_session, [_member("inst-NEW", number=12)])

    (m,) = reconcile_set_membership(db_session, s, MACHINE).members

    assert m.state == PENDING_BIND
    assert m.observed["value"] == 12
    assert m.entry_id == entry.id


@pytest.mark.unit
def test_no_machine_returns_members_verbatim_with_no_state(db_session):
    s = _set(db_session, [_member("inst-A", number=3)])

    result = reconcile_set_membership(db_session, s, None)

    assert result.machine_bound is False
    (m,) = result.members
    assert m.state is None
    assert m.observed is None
    assert m.number["value"] == 3
    assert Provenance.kind(m.number["source"]) == Provenance.ASSERTED


@pytest.mark.unit
def test_ambiguous_two_members_resolve_to_one_entry(db_session):
    _entry(db_session, tool_number=5, bound="inst-A")
    s = _set(db_session, [_member("inst-A"), _member("inst-A")])

    result = reconcile_set_membership(db_session, s, MACHINE)

    kinds = {a["kind"] for a in result.ambiguities}
    assert "multiple_members_one_entry" in kinds
