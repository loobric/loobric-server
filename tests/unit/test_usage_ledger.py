# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the usage ledger's delta rules (TOOL_SCHEMA.md §7.8).

The full matrix: baseline, contribution, orphan (unbound), orphan (binding
changed), reset-then-resume, noop, unit refusal. Counters are deltas, never
gauges.
"""
import pytest

from loobric_server.database.schema import (
    ToolInstanceRecord, ToolTableEntryRecord, UsageLedger, User,
)
from loobric_server.usage_ledger import (
    UsageError, ingest_usage_observation, instance_total,
)

SRC = "observed:haas@vf2"


@pytest.fixture
def world(db_session):
    user = User(email="usage@test.io", password_hash="x")
    db_session.add(user)
    db_session.flush()
    instance = ToolInstanceRecord(
        canonical={"name": {"value": "6mm", "source": "asserted:t"},
                   "catalog_type_id": {"value": None, "source": "unknown"},
                   "geometry": {}},
        clients={}, user_id=user.id, created_by=user.id, updated_by=user.id)
    entry = ToolTableEntryRecord(
        machine_id="m-1", bound_instance_id=None,
        canonical={"tool_number": {"value": 1, "source": SRC},
                   "bound_instance_id": {"value": None, "source": "unknown"},
                   "offsets": {}},
        clients={}, user_id=user.id, created_by=user.id, updated_by=user.id)
    db_session.add_all([instance, entry])
    db_session.commit()
    return db_session, user, entry, instance


def observe(db, user, entry, value):
    """What the observe endpoint does: ingest against the PREVIOUS reading,
    then write the new one to canonical."""
    result = ingest_usage_observation(db, user, entry, value, "h", SRC,
                                      entry.machine_id)
    canonical = dict(entry.canonical)
    canonical["usage_hours"] = {"value": value, "unit": "h", "source": SRC}
    entry.canonical = canonical
    db.commit()
    return result


def bind(db, entry, instance_id):
    entry.bound_instance_id = instance_id
    db.commit()


def ledger_rows(db, user):
    return db.query(UsageLedger).filter(
        UsageLedger.user_id == user.id).order_by(UsageLedger.created_at).all()


class TestDeltaRules:
    def test_first_observation_is_baseline(self, world):
        db, user, entry, instance = world
        bind(db, entry, instance.id)
        assert observe(db, user, entry, 40.0)["disposition"] == "baseline"
        assert ledger_rows(db, user) == []
        assert instance_total(db, user, instance.id) == 0.0

    def test_positive_delta_bound_stable_contributes(self, world):
        db, user, entry, instance = world
        bind(db, entry, instance.id)
        observe(db, user, entry, 10.0)
        result = observe(db, user, entry, 25.3)
        assert result == {"disposition": "contribution",
                          "amount": pytest.approx(15.3)}
        (row,) = ledger_rows(db, user)
        assert row.instance_id == instance.id
        assert row.amount == pytest.approx(15.3)
        assert row.counter_value == 25.3
        assert row.source == SRC
        assert instance_total(db, user, instance.id) == pytest.approx(15.3)

    def test_positive_delta_unbound_orphans(self, world):
        db, user, entry, instance = world
        observe(db, user, entry, 10.0)
        result = observe(db, user, entry, 14.0)
        assert result["disposition"] == "orphan"
        (row,) = ledger_rows(db, user)
        assert row.instance_id is None
        assert row.amount == pytest.approx(4.0)
        assert instance_total(db, user, instance.id) == 0.0

    def test_binding_changed_within_interval_orphans(self, world):
        """Bound AFTER the interval started: the hours can't be honestly
        credited — orphaned, never guessed."""
        db, user, entry, instance = world
        observe(db, user, entry, 10.0)      # baseline while unbound
        bind(db, entry, instance.id)        # binding changes mid-interval
        result = observe(db, user, entry, 12.5)
        assert result["disposition"] == "orphan"
        (row,) = ledger_rows(db, user)
        assert row.instance_id is None
        # …but the NEXT interval starts bound, so it contributes.
        result = observe(db, user, entry, 13.5)
        assert result["disposition"] == "contribution"

    def test_reset_rebaselines_then_resumes(self, world):
        db, user, entry, instance = world
        bind(db, entry, instance.id)
        observe(db, user, entry, 10.0)
        observe(db, user, entry, 25.3)                       # +15.3
        assert observe(db, user, entry, 5.0)["disposition"] == "reset"
        assert instance_total(db, user, instance.id) == pytest.approx(15.3)
        result = observe(db, user, entry, 8.0)               # +3 from NEW base
        assert result["amount"] == pytest.approx(3.0)
        assert instance_total(db, user, instance.id) == pytest.approx(18.3)

    def test_zero_delta_is_noop(self, world):
        db, user, entry, instance = world
        bind(db, entry, instance.id)
        observe(db, user, entry, 10.0)
        assert observe(db, user, entry, 10.0)["disposition"] == "noop"
        assert ledger_rows(db, user) == []


class TestRefusals:
    def test_wrong_unit(self, world):
        db, user, entry, _ = world
        with pytest.raises(UsageError):
            ingest_usage_observation(db, user, entry, 10.0, "min", SRC, "m-1")

    @pytest.mark.parametrize("bad", ["ten", None, True, -1.0])
    def test_bad_values(self, world, bad):
        db, user, entry, _ = world
        with pytest.raises(UsageError):
            ingest_usage_observation(db, user, entry, bad, "h", SRC, "m-1")


class TestDerivedTotal:
    def test_contribution_writes_derived_canonical(self, world):
        db, user, entry, instance = world
        bind(db, entry, instance.id)
        observe(db, user, entry, 0.0)
        observe(db, user, entry, 7.5)
        db.refresh(instance)
        hours = instance.canonical["usage"]["hours"]
        assert hours == {"value": 7.5, "unit": "h",
                         "source": "derived:usage-ledger"}

    def test_total_sums_across_entries(self, world):
        """The point of the whole design: two machines' counters credit one
        physical tool."""
        db, user, entry, instance = world
        bind(db, entry, instance.id)
        observe(db, user, entry, 0.0)
        observe(db, user, entry, 25.3)
        bind(db, entry, None)               # tool moves to another machine
        entry2 = ToolTableEntryRecord(
            machine_id="m-2", bound_instance_id=instance.id,
            canonical={"tool_number": {"value": 3, "source": SRC},
                       "bound_instance_id": {"value": instance.id,
                                             "source": "asserted:human@inbox"},
                       "offsets": {}},
            clients={}, user_id=user.id, created_by=user.id,
            updated_by=user.id)
        db.add(entry2)
        db.commit()
        observe(db, user, entry2, 0.0)
        observe(db, user, entry2, 12.1)
        assert instance_total(db, user, instance.id) == pytest.approx(37.4)
        db.refresh(instance)
        assert instance.canonical["usage"]["hours"]["value"] == \
            pytest.approx(37.4)
