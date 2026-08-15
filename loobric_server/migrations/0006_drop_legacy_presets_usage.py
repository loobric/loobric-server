# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Drop the legacy deep-schema `tool_presets` and `tool_usage` tables
(REBOOT.md R6, first slice). The v1 ToolPreset was machine/pocket/offset
"setup data" — a tool-*location* concept superseded by ToolTableEntry and
the setups model, and squatting on the vocabulary the M3 feeds-and-speeds
Preset needs. ToolUsage hung off it by FK and is superseded by the
usage-ledger (§7.8). Their routers and ORM models are removed in the same
release; v1 rows are pre-facade data, deliberately not migrated anywhere.

Idempotent: DROP IF EXISTS only (mandatory on SQLite, where DDL
auto-commits). Order matters: tool_usage carries the FK to tool_presets.
"""
from sqlalchemy import text

revision = "0006"
name = "drop_legacy_presets_usage"


def upgrade(conn):
    conn.execute(text("DROP TABLE IF EXISTS tool_usage"))
    conn.execute(text("DROP TABLE IF EXISTS tool_presets"))
