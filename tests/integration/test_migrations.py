# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the schema migration spine (loobric_server/migrations).

Covers the three boot states (fresh / legacy / managed), idempotent re-runs,
failure-aborts-without-recording, checksum drift, and the safety backup hook.
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from loobric_server.migrations import (
    Migration,
    MigrationError,
    discover_migrations,
    run_migrations,
    safety_backup,
)


def _engine(tmp_path, name="test.db"):
    return create_engine(f"sqlite:///{tmp_path / name}")


def _baseline():
    return Migration(
        revision="0001", name="baseline", upgrade=lambda c: None,
        checksum="base", baseline=True,
    )


def _creates_widgets(checksum="w1"):
    def upgrade(conn):
        conn.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY)"))

    return Migration(revision="0002", name="widgets", upgrade=upgrade, checksum=checksum)


def _ledger(engine):
    with engine.begin() as conn:
        return {
            row[0]: row[1]
            for row in conn.execute(
                text("SELECT revision, checksum FROM schema_migrations")
            ).fetchall()
        }


def _has_table(engine, name):
    return name in inspect(engine).get_table_names()


def test_fresh_db_stamps_all_without_running_upgrades(tmp_path):
    engine = _engine(tmp_path)
    result = run_migrations(engine, fresh=True, migrations=[_baseline(), _creates_widgets()])
    assert result.head == "0002"
    assert result.applied == []
    assert set(result.stamped) == {"0001", "0002"}
    assert set(_ledger(engine)) == {"0001", "0002"}
    # Fresh => create_all already built head; upgrades must NOT run again.
    assert not _has_table(engine, "widgets")


def test_legacy_db_stamps_baseline_and_applies_rest(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as conn:  # simulate a pre-spine populated database
        conn.execute(text("CREATE TABLE tools (id INTEGER PRIMARY KEY)"))
    result = run_migrations(
        engine, fresh=False, migrations=[_baseline(), _creates_widgets()]
    )
    assert result.stamped == ["0001"]
    assert result.applied == ["0002"]
    assert _has_table(engine, "widgets")
    assert set(_ledger(engine)) == {"0001", "0002"}


def test_managed_db_applies_only_new_pending(tmp_path):
    engine = _engine(tmp_path)
    run_migrations(engine, fresh=True, migrations=[_baseline()])
    assert set(_ledger(engine)) == {"0001"}
    result = run_migrations(
        engine, fresh=False, migrations=[_baseline(), _creates_widgets()]
    )
    assert result.applied == ["0002"]
    assert _has_table(engine, "widgets")


def test_rerun_is_idempotent(tmp_path):
    engine = _engine(tmp_path)
    migs = [_baseline(), _creates_widgets()]
    run_migrations(engine, fresh=False, migrations=migs)
    result = run_migrations(engine, fresh=False, migrations=migs)
    assert result.applied == []
    assert result.stamped == []
    assert set(_ledger(engine)) == {"0001", "0002"}


def test_failure_aborts_without_recording(tmp_path):
    engine = _engine(tmp_path)

    def boom(conn):
        raise RuntimeError("kaboom")

    bad = Migration(revision="0002", name="bad", upgrade=boom, checksum="b")
    with pytest.raises(MigrationError):
        run_migrations(engine, fresh=False, migrations=[_baseline(), bad])
    ledger = _ledger(engine)
    assert "0001" in ledger  # baseline is stamped before applies begin
    assert "0002" not in ledger  # a failed migration is never recorded


def test_failed_migration_is_retried_on_next_run(tmp_path):
    # Because a failed migration is not recorded, the next startup retries it.
    # On SQLite, DDL is not rolled back on failure, so migrations must be
    # idempotent; an idempotent retry recovers cleanly.
    engine = _engine(tmp_path)
    state = {"fail": True}

    def flaky(conn):
        conn.execute(text("CREATE TABLE IF NOT EXISTS widgets (id INTEGER PRIMARY KEY)"))
        if state["fail"]:
            raise RuntimeError("transient")

    mig = Migration(revision="0002", name="widgets", upgrade=flaky, checksum="w1")
    with pytest.raises(MigrationError):
        run_migrations(engine, fresh=False, migrations=[_baseline(), mig])
    assert "0002" not in _ledger(engine)

    state["fail"] = False
    result = run_migrations(engine, fresh=False, migrations=[_baseline(), mig])
    assert result.applied == ["0002"]
    assert "0002" in _ledger(engine)
    assert _has_table(engine, "widgets")


def test_checksum_drift_is_rejected(tmp_path):
    engine = _engine(tmp_path)
    run_migrations(
        engine, fresh=False, migrations=[_baseline(), _creates_widgets(checksum="v1")]
    )
    with pytest.raises(MigrationError, match="edited after"):
        run_migrations(
            engine, fresh=False, migrations=[_baseline(), _creates_widgets(checksum="v2")]
        )


def test_backup_runs_before_applying(tmp_path):
    engine = _engine(tmp_path)
    calls = []
    run_migrations(
        engine,
        fresh=False,
        migrations=[_baseline(), _creates_widgets()],
        backup_fn=lambda: calls.append("backup"),
    )
    assert calls == ["backup"]


def test_backup_skipped_when_nothing_is_applied(tmp_path):
    engine = _engine(tmp_path)
    calls = []
    run_migrations(
        engine,
        fresh=True,
        migrations=[_baseline()],
        backup_fn=lambda: calls.append("backup"),
    )
    assert calls == []


def test_discover_finds_real_baseline():
    migs = discover_migrations()
    baseline = next((m for m in migs if m.revision == "0001"), None)
    assert baseline is not None
    assert baseline.baseline is True


def test_safety_backup_copies_sqlite_file(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER)"))
    path = safety_backup(engine)
    assert path is not None
    assert Path(path).exists()


def test_safety_backup_noop_for_memory_db():
    engine = create_engine("sqlite://")  # in-memory
    assert safety_backup(engine) is None
