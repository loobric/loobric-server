# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
ToolUsage API endpoints.

Bulk-first design: all operations accept arrays.

Assumptions:
- POST /api/v1/tool-usage - Create (bulk)
- GET /api/v1/tool-usage - List/query with filters
- PUT /api/v1/tool-usage - Update (bulk) with version checking
- DELETE /api/v1/tool-usage - Delete (bulk)
- preset_id references ToolPreset
- Tracks runtime, cycle count, wear progression
"""
from typing import Annotated, Optional, List
from uuid import uuid4
from datetime import datetime, UTC
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db, require_auth
from loobric_server.database.schema import User, ToolUsage


router = APIRouter(prefix="/api/v1/tool-usage", tags=["tool-usage"])


# Request/Response Models
class ToolUsageCreate(BaseModel):
    """Schema for creating a tool usage record."""
    preset_id: Optional[str] = None
    job_id: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    cycle_count: Optional[int] = None
    cut_time: Optional[float] = None
    wear_progression: Optional[list] = None
    events: Optional[list] = None


class ToolUsageUpdate(BaseModel):
    """Schema for updating a tool usage record."""
    id: str
    version: int
    preset_id: Optional[str] = None
    job_id: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    cycle_count: Optional[int] = None
    cut_time: Optional[float] = None
    wear_progression: Optional[list] = None
    events: Optional[list] = None


class ToolUsageResponse(BaseModel):
    """Schema for tool usage response."""
    id: str
    preset_id: str
    job_id: Optional[str]
    start_time: str
    end_time: Optional[str]
    cycle_count: Optional[int]
    cut_time: Optional[float]
    wear_progression: Optional[list]
    events: Optional[list]
    user_id: str
    created_by: str
    updated_by: str
    created_at: str
    updated_at: str
    version: int


class BulkCreateRequest(BaseModel):
    """Bulk create request."""
    items: List[ToolUsageCreate]


class BulkUpdateRequest(BaseModel):
    """Bulk update request."""
    items: List[ToolUsageUpdate]


class BulkDeleteRequest(BaseModel):
    """Bulk delete request."""
    ids: List[str]


class ErrorDetail(BaseModel):
    """Error detail for a failed operation."""
    index: Optional[int] = None
    id: Optional[str] = None
    message: str


class BulkOperationResponse(BaseModel):
    """Response for bulk operations."""
    success_count: int
    error_count: int
    results: List[ToolUsageResponse] = []
    errors: List[ErrorDetail] = []


class QueryResponse(BaseModel):
    """Response for query operations."""
    items: List[ToolUsageResponse]
    total: int
    limit: int
    offset: int


@router.post("", response_model=BulkOperationResponse)
def create_tool_usage(
    request: BulkCreateRequest,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Create tool usage records in bulk."""
    results = []
    errors = []
    
    for index, usage_data in enumerate(request.items):
        try:
            # Validate required fields
            if not usage_data.preset_id:
                raise ValueError("Field 'preset_id' is required")
            if not usage_data.start_time:
                raise ValueError("Field 'start_time' is required")
            
            # Parse start_time
            start_time = datetime.fromisoformat(usage_data.start_time.replace('Z', '+00:00'))
            end_time = None
            if usage_data.end_time:
                end_time = datetime.fromisoformat(usage_data.end_time.replace('Z', '+00:00'))
            
            # Create tool usage
            tool_usage = ToolUsage(
                id=str(uuid4()),
                preset_id=usage_data.preset_id,
                job_id=usage_data.job_id,
                start_time=start_time,
                end_time=end_time,
                cycle_count=usage_data.cycle_count,
                cut_time=usage_data.cut_time,
                wear_progression=usage_data.wear_progression,
                events=usage_data.events,
                user_id=current_user.id,
                created_by=current_user.id,
                updated_by=current_user.id
            )
            
            db.add(tool_usage)
            db.flush()
            
            results.append(_to_response(tool_usage))
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=index,
                message=str(e)
            ))
    
    if results:
        db.commit()
    else:
        db.rollback()
    
    return BulkOperationResponse(
        success_count=len(results),
        error_count=len(errors),
        results=results,
        errors=errors
    )


@router.get("", response_model=QueryResponse)
def list_tool_usage(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """List tool usage records with pagination."""
    query = db.query(ToolUsage).filter(ToolUsage.user_id == current_user.id)
    
    total = query.count()
    usage_records = query.limit(limit).offset(offset).all()
    
    return QueryResponse(
        items=[_to_response(usage) for usage in usage_records],
        total=total,
        limit=limit,
        offset=offset
    )


@router.put("", response_model=BulkOperationResponse)
def update_tool_usage(
    request: BulkUpdateRequest,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Update tool usage records in bulk."""
    results = []
    errors = []
    
    for index, update_data in enumerate(request.items):
        try:
            usage = db.query(ToolUsage).filter(
                ToolUsage.id == update_data.id,
                ToolUsage.user_id == current_user.id
            ).first()
            
            if not usage:
                errors.append(ErrorDetail(
                    index=index,
                    id=update_data.id,
                    message="Usage record not found or access denied"
                ))
                continue
            
            if usage.version != update_data.version:
                errors.append(ErrorDetail(
                    index=index,
                    id=update_data.id,
                    message=f"Version conflict: expected {usage.version}, got {update_data.version}"
                ))
                continue
            
            # Apply updates
            if update_data.preset_id is not None:
                usage.preset_id = update_data.preset_id
            if update_data.job_id is not None:
                usage.job_id = update_data.job_id
            if update_data.start_time is not None:
                usage.start_time = datetime.fromisoformat(update_data.start_time.replace('Z', '+00:00'))
            if update_data.end_time is not None:
                usage.end_time = datetime.fromisoformat(update_data.end_time.replace('Z', '+00:00'))
            if update_data.cycle_count is not None:
                usage.cycle_count = update_data.cycle_count
            if update_data.cut_time is not None:
                usage.cut_time = update_data.cut_time
            if update_data.wear_progression is not None:
                usage.wear_progression = update_data.wear_progression
            if update_data.events is not None:
                usage.events = update_data.events
            
            usage.updated_by = current_user.id
            usage.updated_at = datetime.now(UTC)
            usage.version += 1
            
            db.flush()
            results.append(_to_response(usage))
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=index,
                id=update_data.id,
                message=str(e)
            ))
    
    if results:
        db.commit()
    else:
        db.rollback()
    
    return BulkOperationResponse(
        success_count=len(results),
        error_count=len(errors),
        results=results,
        errors=errors
    )


@router.delete("", response_model=BulkOperationResponse)
def delete_tool_usage(
    request: BulkDeleteRequest,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Delete tool usage records in bulk."""
    results = []
    errors = []
    
    for index, usage_id in enumerate(request.ids):
        try:
            usage = db.query(ToolUsage).filter(
                ToolUsage.id == usage_id,
                ToolUsage.user_id == current_user.id
            ).first()
            
            if not usage:
                errors.append(ErrorDetail(
                    index=index,
                    id=usage_id,
                    message="Usage record not found or access denied"
                ))
                continue
            
            response = _to_response(usage)
            db.delete(usage)
            db.flush()
            
            results.append(response)
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=index,
                id=usage_id,
                message=str(e)
            ))
    
    if results:
        db.commit()
    else:
        db.rollback()
    
    return BulkOperationResponse(
        success_count=len(results),
        error_count=len(errors),
        results=results,
        errors=errors
    )


def _to_response(usage: ToolUsage) -> ToolUsageResponse:
    """Convert ToolUsage entity to response model."""
    return ToolUsageResponse(
        id=usage.id,
        preset_id=usage.preset_id,
        job_id=usage.job_id,
        start_time=usage.start_time.isoformat() if usage.start_time else "",
        end_time=usage.end_time.isoformat() if usage.end_time else None,
        cycle_count=usage.cycle_count,
        cut_time=usage.cut_time,
        wear_progression=usage.wear_progression,
        events=usage.events,
        user_id=usage.user_id,
        created_by=usage.created_by,
        updated_by=usage.updated_by,
        created_at=usage.created_at.isoformat() if usage.created_at else "",
        updated_at=usage.updated_at.isoformat() if usage.updated_at else "",
        version=usage.version
    )
