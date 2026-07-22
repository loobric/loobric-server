# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for reconcile_set_membership (ROUNDTRIP_FIXES Fix 2 / S1).

A machine-bound ToolSet classifies each member against the machine's tool-table
entries at read time: loaded (bound -> observed number inherited), requested (no
entry), or pending bind (an open proposal names the instance but it isn't bound
yet). Ambiguities are surfaced, never silently renumbered. A set with no
machine_id is returned verbatim with no derived state.
"""
import pytest

from loobric_server.binding_v2 import (
    reconcile_set_membership, LOADED, REQUESTED, PENDING_BIND,
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


def _set(db, members, machine_id=MACHINE):
    canonical = {
        "name": {"value": "millstone", "source": Provenance.asserted("freecad")},
        "machine_id": (
            {"value": machine_id, "source": Provenance.asserted("freecad")}
            if machine_id else {"value": None, "source": UNKNOWN}),
        "members": members,
    }
    row = ToolSetRecord(
        machine_id=machine_id, canonical=canonical, clients={},
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
def test_loaded_member_inherits_observed_number(db_session):
    entry = _entry(db_session, tool_number=5, bound="inst-A")
    s = _set(db_session, [_member("inst-A")])

    result = reconcile_set_membership(db_session, s)

    assert result.machine_bound is True
    (m,) = result.members
    assert m.state == LOADED
    assert m.number["value"] == 5
    assert m.number["source"].startswith("observed:")
    assert m.entry_id == entry.id
    assert result.ambiguities == []


@pytest.mark.unit
def test_requested_member_preserved_with_asserted_number(db_session):
    _entry(db_session, tool_number=5, bound="inst-A")
    s = _set(db_session, [_member("inst-A"), _member("inst-NEW", number=18)])

    result = reconcile_set_membership(db_session, s)

    states = {m.tool_record_id: m for m in result.members}
    assert states["inst-A"].state == LOADED
    req = states["inst-NEW"]
    assert req.state == REQUESTED
    assert req.number["value"] == 18                 # asserted preference preserved
    assert Provenance.kind(req.number["source"]) == Provenance.ASSERTED
    assert req.entry_id is None


@pytest.mark.unit
def test_requested_member_with_no_number_stays_unknown(db_session):
    s = _set(db_session, [_member("inst-NEW")])

    (m,) = reconcile_set_membership(db_session, s).members

    assert m.state == REQUESTED
    assert m.number["value"] is None
    assert m.number["source"] == UNKNOWN


@pytest.mark.unit
def test_pending_bind_when_open_proposal_names_instance(db_session):
    entry = _entry(db_session, tool_number=18)          # unbound, but observed number 18
    _open_proposal(db_session, entry, "inst-NEW")
    s = _set(db_session, [_member("inst-NEW", number=18)])

    (m,) = reconcile_set_membership(db_session, s).members

    assert m.state == PENDING_BIND
    assert m.number["value"] == 18
    assert m.number["source"].startswith("observed:")   # observed from the entry
    assert m.entry_id == entry.id


@pytest.mark.unit
def test_non_machine_bound_set_is_unaffected(db_session):
    s = _set(db_session, [_member("inst-A", number=3)], machine_id=None)

    result = reconcile_set_membership(db_session, s)

    assert result.machine_bound is False
    (m,) = result.members
    assert m.state is None
    assert m.number["value"] == 3
    assert Provenance.kind(m.number["source"]) == Provenance.ASSERTED


@pytest.mark.unit
def test_ambiguous_two_members_resolve_to_one_entry(db_session):
    _entry(db_session, tool_number=5, bound="inst-A")
    s = _set(db_session, [_member("inst-A"), _member("inst-A")])

    result = reconcile_set_membership(db_session, s)

    kinds = {a["kind"] for a in result.ambiguities}
    assert "multiple_members_one_entry" in kinds


@pytest.mark.unit
def test_ambiguous_observed_number_collides_with_asserted(db_session):
    _entry(db_session, tool_number=5, bound="inst-A")        # loaded -> observed 5
    s = _set(db_session, [_member("inst-A"),
                          _member("inst-NEW", number=5)])     # asserted 5 collides

    result = reconcile_set_membership(db_session, s)

    collisions = [a for a in result.ambiguities if a["kind"] == "number_collision"]
    assert collisions and collisions[0]["number"] == 5
