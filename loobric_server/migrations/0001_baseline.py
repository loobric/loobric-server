# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Baseline revision.

Marks the schema as it shipped when the migration spine was introduced (the v2
sectioned records). It performs no DDL — it only establishes the starting point
in the ledger so that later migrations apply on top of a known state. Fresh
databases (built at head by `create_all`) and legacy populated databases alike
are stamped with this revision.
"""

revision = "0001"
name = "baseline"
baseline = True


def upgrade(conn):  # noqa: ARG001 - the baseline performs no schema change
    """No-op: the baseline only records the starting revision."""
    return None
