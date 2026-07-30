# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the request-aware binding bridge (ROUNDTRIP_FIXES Fix 2 / S3,
reworked for setups in MAPPING_PLAN.md).

`requested_members_by_number` resolves the machine's ACTIVE setup
(machine_set_maps) and indexes that set's requested members by asserted claimed
number; `propose_for_requested_entry` opens an elevated-confidence proposal
when a new entry's tool_number matches one, falling back to the geometry
heuristic otherwise. `bridge_requested_claims` covers the CAM-first ordering:
the entry already exists when the claim arrives. The rejected-pair guard holds.
"""
from datetime import datetime, UTC

import pytest

from loobric_server.binding_v2 import (
    requested_members_by_number, propose_for_requested_entry,
    bridge_requested_claims, REQUESTED_CONFIDENCE, DIAMETER_WEIGHT,
)
from loobric_server.database.schema import (
    User, ToolSetRecord, ToolTableEntryRecord, ToolInstanceRecord,
    EntryProposal, MachineSetMap,
)
from loobric_server.contract import Provenance, UNKNOWN

UID = "user-req"
MACHINE = "m-req-bridge"


@pytest.fixture
def user(db_session):
    u = User(id=UID, email="r@example.com", password_hash="x")
    db_session.add(u)
    db_session.flush()
    return u


def _instance(db, iid, diameter=None):
    canonical = {"name": {"value": None, "source": UNKNOWN},
                 "catalog_type_id": {"value": None, "source": UNKNOWN},
                 "geometry": {}}
    if diameter is not None:
        canonical["geometry"]["diameter"] = {
            "value": diameter, "unit": "mm",
            "source": Provenance.asserted("freecad")}
    row = ToolInstanceRecord(id=iid, canonical=canonical, clients={},
                             catalog_type_id=None, user_id=UID,
                             created_by=UID, updated_by=UID)
    db.add(row)
    db.flush()
    return row


def _entry(db, tool_number, diameter=None):
    src = Provenance.observed("linuxcnc", "millstone")
    canonical = {
        "tool_number": {"value": tool_number, "source": src},
        "bound_instance_id": {"value": None, "source": UNKNOWN},
        "offsets": ({"diameter": {"value": diameter, "unit": "mm", "source": src}}
                    if diameter is not None else {}),
    }
    row = ToolTableEntryRecord(
        machine_id=MACHINE, bound_instance_id=None, canonical=canonical,
        clients={}, user_id=UID, created_by=UID, updated_by=UID)
    db.add(row)
    db.flush()
    return row


def _active_set(db, members, name="millstone"):
    """A set plus the setup row that makes it the machine's active set."""
    canonical = {
        "name": {"value": name, "source": Provenance.asserted("freecad")},
        "members": members,
    }
    row = ToolSetRecord(canonical=canonical, clients={},
                        user_id=UID, created_by=UID, updated_by=UID)
    db.add(row)
    db.flush()
    db.add(MachineSetMap(machine_id=MACHINE, tool_set_id=row.id,
                         status="active", activated_at=datetime.now(UTC),
                         user_id=UID, created_by=UID, updated_by=UID))
    db.flush()
    return row


def _member(iid, number=None):
    num = ({"value": number, "source": Provenance.asserted("freecad")}
           if number is not None else {"value": None, "source": UNKNOWN})
    return {"tool_record_id": iid, "number": num}


@pytest.mark.unit
def test_index_only_asserted_numbered_requested_members(db_session, user):
    _instance(db_session, "inst-A")
    _active_set(db_session, [_member("inst-REQ", number=18),  # requested w/ claim
                             _member("inst-UNK")])            # requested, unknown
    idx = requested_members_by_number(db_session, user, MACHINE)
    assert idx == {18: ("inst-REQ", "millstone")}        # only the numbered claim


@pytest.mark.unit
def test_no_active_setup_indexes_nothing(db_session, user):
    """A set with claims but no setup on this machine can auto-bind nothing —
    only the active set's claims are the bridge's signal."""
    canonical = {"name": {"value": "idle", "source": Provenance.asserted("freecad")},
                 "members": [_member("inst-REQ", number=18)]}
    db_session.add(ToolSetRecord(canonical=canonical, clients={},
                                 user_id=UID, created_by=UID, updated_by=UID))
    db_session.flush()
    assert requested_members_by_number(db_session, user, MACHINE) == {}


@pytest.mark.unit
def test_number_match_short_circuits_threshold(db_session, user):
    _active_set(db_session, [_member("inst-REQ", number=18)])
    entry = _entry(db_session, tool_number=18)           # no diameter at all
    idx = requested_members_by_number(db_session, user, MACHINE)

    p = propose_for_requested_entry(db_session, user, entry, idx)
    assert p is not None
    assert p.proposed_instance_id == "inst-REQ"
    assert p.confidence == round(REQUESTED_CONFIDENCE, 3)
    assert p.reason == "requested via set millstone"


@pytest.mark.unit
def test_no_number_match_falls_back_to_geometry(db_session, user):
    _instance(db_session, "inst-GEO", diameter=6.35)
    _active_set(db_session, [_member("inst-REQ", number=99)])  # claim won't match
    entry = _entry(db_session, tool_number=18, diameter=6.35)
    idx = requested_members_by_number(db_session, user, MACHINE)

    p = propose_for_requested_entry(db_session, user, entry, idx)
    assert p is not None
    assert p.proposed_instance_id == "inst-GEO"          # geometry, not the request
    assert p.confidence == round(DIAMETER_WEIGHT, 3)
    assert "diameter" in p.reason


@pytest.mark.unit
def test_rejected_pair_is_not_reproposed_falls_back_to_geometry(db_session, user):
    _instance(db_session, "inst-GEO", diameter=6.35)
    _active_set(db_session, [_member("inst-REQ", number=18)])
    entry = _entry(db_session, tool_number=18, diameter=6.35)
    db_session.add(EntryProposal(
        entry_id=entry.id, proposed_instance_id="inst-REQ", confidence=0.95,
        reason="requested via set millstone", status="rejected",
        user_id=UID, created_by=UID, updated_by=UID))
    db_session.flush()
    idx = requested_members_by_number(db_session, user, MACHINE)

    p = propose_for_requested_entry(db_session, user, entry, idx)
    # The rejected (entry, inst-REQ) pair is never re-proposed; geometry carries it.
    assert p is not None
    assert p.proposed_instance_id == "inst-GEO"


@pytest.mark.unit
def test_bridge_covers_cam_first_ordering(db_session, user):
    """Slice 0b: the entry EXISTS FIRST; the claim arrives afterward. The
    bridge opens the elevated-confidence proposal immediately instead of
    stalling until the machine's next push."""
    entry = _entry(db_session, tool_number=12)           # mounted long ago, unbound
    _active_set(db_session, [_member("inst-REQ", number=12)])

    opened = bridge_requested_claims(db_session, user, MACHINE)

    assert opened == 1
    p = db_session.query(EntryProposal).filter(
        EntryProposal.entry_id == entry.id,
        EntryProposal.status == "open").one()
    assert p.proposed_instance_id == "inst-REQ"
    assert p.confidence == round(REQUESTED_CONFIDENCE, 3)
    # Idempotent: a second bridge run opens nothing new (open-proposal guard).
    assert bridge_requested_claims(db_session, user, MACHINE) == 0
