# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Audit rows record the acting credential (SCOPES_PLAN §6, 0.6.0).

Adds `channel` (session / api-key / solo) and `api_key_id` to audit_logs.
The declared actor inside `changes` is client-supplied; these columns are
server-known truth, which makes a spoofed actor detectable after the fact.
Pre-existing rows keep NULL — honestly unknown, never backfilled with a guess.

Idempotent: skips each column if it already exists (a fresh database built at
head by create_all already has them).
"""
from sqlalchemy import text

revision = "0002"
name = "audit_credentials"


def upgrade(conn):
    existing = {row[1] for row in
                conn.execute(text("PRAGMA table_info(audit_logs)"))}
    if "channel" not in existing:
        conn.execute(text(
            "ALTER TABLE audit_logs ADD COLUMN channel VARCHAR(10)"))
    if "api_key_id" not in existing:
        conn.execute(text(
            "ALTER TABLE audit_logs ADD COLUMN api_key_id VARCHAR(36)"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_api_key_id "
            "ON audit_logs (api_key_id)"))
