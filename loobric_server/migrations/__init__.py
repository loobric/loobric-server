# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Schema migration spine. See `docs/MIGRATIONS.md`."""
from loobric_server.migrations.runner import (
    Migration,
    MigrationError,
    MigrationResult,
    current_head,
    discover_migrations,
    run_migrations,
    safety_backup,
)

__all__ = [
    "Migration",
    "MigrationError",
    "MigrationResult",
    "current_head",
    "discover_migrations",
    "run_migrations",
    "safety_backup",
]
