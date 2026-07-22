# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Backup and restore API endpoints.

Provides REST API for database backup and restore operations.

Assumptions:
- Backup downloads as JSON file
- Restore accepts uploaded JSON file
- Requires an authenticated administrator (solo user qualifies)
- Returns metadata and validation results
"""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from loobric_server.backup import (
    export_backup_json, restore_backup_json,
    BackupVersionError, BackupValidationError
)
from loobric_server.api.auth import get_db, get_authenticated_user
from loobric_server.database.schema import User

# Router
router = APIRouter(prefix="/api/v1/backup", tags=["backup"])


def require_admin(user: User = Depends(get_authenticated_user)) -> User:
    """Gate full-database backup/restore to administrators. In solo mode the
    built-in solo user is the first user and therefore an admin, so solo
    deployments still work with no auth ceremony."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Backup requires an administrator")
    return user


@router.get("/export")
def export_database(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Export full database backup as JSON. Admin-only.

    Args:
        db: Database session
        admin: Authenticated administrator (enforced)

    Returns:
        JSON response with backup data
    """
    try:
        backup_json = export_backup_json(db)
        
        return Response(
            content=backup_json,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=loobric_server-backup.json"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@router.post("/import")
async def import_database(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Import database from backup JSON file. Admin-only.

    Args:
        file: Uploaded JSON backup file
        db: Database session
        admin: Authenticated administrator (enforced)

    Returns:
        dict: Import result with success status and counts

    Raises:
        HTTPException: If import fails

    Assumptions:
    - Accepts JSON file upload
    - Validates before importing
    - Atomic operation (all or nothing)
    """
    try:
        # Read file content
        content = await file.read()
        json_str = content.decode('utf-8')
        
        # Restore from JSON
        result = restore_backup_json(db, json_str)
        
        return result
        
    except BackupVersionError as e:
        raise HTTPException(status_code=400, detail=f"Version error: {str(e)}")
    except BackupValidationError as e:
        raise HTTPException(status_code=400, detail=f"Validation error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
