# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
ToolInstance API endpoints.

Bulk-first design: all operations accept arrays.

Assumptions:
- POST /api/v1/tool-instances - Create (bulk)
- GET /api/v1/tool-instances - List/query with filters
- PUT /api/v1/tool-instances - Update (bulk) with version checking
- DELETE /api/v1/tool-instances - Delete (bulk)
- assembly_id references ToolAssembly
- status: available, in_use, needs_inspection, retired
"""
from typing import Annotated, Optional, List
from uuid import uuid4
from datetime import datetime, UTC
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db, require_auth, get_authenticated_user
from loobric_server.api.dependencies import get_tool_instance_access
from loobric_server.database.schema import User, ToolInstance


router = APIRouter(prefix="/api/v1/tool-instances", tags=["tool-instances"])


# Request/Response Models
class ToolInstanceCreate(BaseModel):
    """Schema for creating a tool instance."""
    assembly_id: Optional[str] = None
    serial_number: Optional[str] = None
    status: Optional[str] = "available"
    location: Optional[dict] = None
    measured_geometry: Optional[dict] = None
    lifecycle: Optional[dict] = None
    tags: List[str] = Field(default_factory=list, description="Tags for filtering and access control")


class ToolInstanceUpdate(BaseModel):
    """Schema for updating a tool instance."""
    id: str
    version: int
    assembly_id: Optional[str] = None
    serial_number: Optional[str] = None
    status: Optional[str] = None
    location: Optional[dict] = None
    measured_geometry: Optional[dict] = None
    lifecycle: Optional[dict] = None
    tags: Optional[List[str]] = None


class ToolInstanceResponse(BaseModel):
    """Schema for tool instance response."""
    id: str
    assembly_id: str
    serial_number: Optional[str]
    status: str
    location: Optional[dict]
    measured_geometry: Optional[dict]
    lifecycle: Optional[dict]
    tags: List[str]
    user_id: str
    created_by: str
    updated_by: str
    created_at: str
    updated_at: str
    version: int


class BulkCreateRequest(BaseModel):
    """Bulk create request."""
    items: List[ToolInstanceCreate]


class BulkUpdateRequest(BaseModel):
    """Bulk update request."""
    items: List[ToolInstanceUpdate]


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
    results: List[ToolInstanceResponse] = []
    errors: List[ErrorDetail] = []


class QueryResponse(BaseModel):
    """Response for query operations."""
    items: List[ToolInstanceResponse]
    total: int
    limit: int
    offset: int


@router.post("", response_model=BulkOperationResponse)
def create_tool_instances(
    req: Request,
    request: BulkCreateRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Create tool instances in bulk.
    
    Notes:
    - For API key authentication, validates that all tags in the request are allowed by the API key
    - For session authentication, allows any tags
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(req.state, 'is_api_key_auth', False)
    api_key_tags = getattr(req.state, 'api_key_tags', [])
    
    results = []
    errors = []
    
    for index, instance_data in enumerate(request.items):
        try:
            # Validate tags if using API key with tags
            if is_api_key_auth and api_key_tags and instance_data.tags:
                # Check if all tags in the request are allowed by the API key
                invalid_tags = [t for t in instance_data.tags if t not in api_key_tags]
                if invalid_tags:
                    errors.append(ErrorDetail(
                        index=index,
                        message=f"API key not authorized for tags: {', '.join(invalid_tags)}"
                    ))
                    continue
            
            # Validate required fields
            if not instance_data.assembly_id:
                raise ValueError("Field 'assembly_id' is required")
            
            # Create tool instance
            tool_instance = ToolInstance(
                id=str(uuid4()),
                assembly_id=instance_data.assembly_id,
                serial_number=instance_data.serial_number,
                status=instance_data.status or "available",
                location=instance_data.location,
                measured_geometry=instance_data.measured_geometry,
                lifecycle=instance_data.lifecycle,
                tags=instance_data.tags or [],
                user_id=current_user.id,
                created_by=current_user.id,
                updated_by=current_user.id
            )
            
            db.add(tool_instance)
            db.flush()
            
            results.append(_to_response(tool_instance))
            
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
def list_tool_instances(
    req: Request,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by status"),
    tags: Optional[List[str]] = Query(None, description="Filter by tags (logical AND)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """List tool instances with filters and pagination.
    
    Notes:
    - For API key authentication, only returns tool instances with tags that match the API key's tags
    - For session authentication, returns all tool instances owned by the user
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(req.state, 'is_api_key_auth', False)
    api_key_tags = getattr(req.state, 'api_key_tags', [])
    
    # Base query - filter by user for session auth or all accessible instances for API key
    if is_api_key_auth:
        # For API keys, we need to check tag access
        query = db.query(ToolInstance)
        
        # If API key has tags, filter by matching tags
        if api_key_tags:
            # Get all instances and filter in Python for SQLite compatibility
            all_instances = query.all()
            matching_ids = [
                i.id for i in all_instances 
                if i.tags and any(tag in i.tags for tag in api_key_tags)
            ]
            if matching_ids:
                query = query.filter(ToolInstance.id.in_(matching_ids))
            else:
                # No matching instances, return empty result
                query = query.filter(ToolInstance.id == None)
    else:
        # For session auth, only show user's own instances
        query = db.query(ToolInstance).filter(ToolInstance.user_id == current_user.id)
    
    if status:
        query = query.filter(ToolInstance.status == status)
    
    # Apply additional tag filters from query params
    if tags:
        for tag in tags:
            query = query.filter(ToolInstance.tags.contains([tag]))
    
    total = query.count()
    instances = query.offset(offset).limit(limit).all()
    
    return QueryResponse(
        items=[_to_response(instance) for instance in instances],
        total=total,
        limit=limit,
        offset=offset
    )


@router.get("/{instance_id}", response_model=ToolInstanceResponse)
def get_tool_instance(
    instance_id: str,
    req: Request,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
    _: None = Depends(get_tool_instance_access)
):
    """Retrieve a single ToolInstance by ID if user has access.
    
    Access is granted if:
    - User is the owner of the tool instance, or
    - User has an API key with matching tags for the tool instance
    """
    instance = db.query(ToolInstance).filter(
        ToolInstance.id == instance_id
    ).first()
    
    if not instance:
        raise HTTPException(status_code=404, detail="Tool instance not found")
    
    # For session auth, only allow access to own resources
    is_api_key_auth = getattr(req.state, 'is_api_key_auth', False)
    if not is_api_key_auth and instance.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Tool instance not found")
    
    return _to_response(instance)


@router.put("", response_model=BulkOperationResponse)
def update_tool_instances(
    req: Request,
    request: BulkUpdateRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Update tool instances in bulk.
    
    Notes:
    - For API key authentication, validates that all tags in the request are allowed by the API key
    - For session authentication, allows any tags
    - Only the owner of a tool instance can update it
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(req.state, 'is_api_key_auth', False)
    api_key_tags = getattr(req.state, 'api_key_tags', [])
    
    results = []
    errors = []
    
    for index, update_data in enumerate(request.items):
        try:
            # Get existing instance
            query = db.query(ToolInstance).filter(ToolInstance.id == update_data.id)
            
            # For session auth, only allow updating own instances
            if not is_api_key_auth:
                query = query.filter(ToolInstance.user_id == current_user.id)
            
            instance = query.first()
            
            if not instance:
                errors.append(ErrorDetail(
                    index=index,
                    id=update_data.id,
                    message="Instance not found or access denied"
                ))
                continue
            
            # For API key auth, check if tags are allowed
            if is_api_key_auth and api_key_tags:
                # Check if API key has access to the existing instance's tags
                if instance.tags and not any(tag in api_key_tags for tag in instance.tags):
                    errors.append(ErrorDetail(
                        index=index,
                        id=update_data.id,
                        message="API key not authorized to update this instance"
                    ))
                    continue
                
                # Check if new tags are allowed
                if update_data.tags is not None:
                    invalid_tags = [t for t in update_data.tags if t not in api_key_tags]
                    if invalid_tags:
                        errors.append(ErrorDetail(
                            index=index,
                            id=update_data.id,
                            message=f"API key not authorized for tags: {', '.join(invalid_tags)}"
                        ))
                        continue
            
            if instance.version != update_data.version:
                errors.append(ErrorDetail(
                    index=index,
                    id=update_data.id,
                    message=f"Version conflict: expected {instance.version}, got {update_data.version}"
                ))
                continue
            
            # Apply updates
            if update_data.assembly_id is not None:
                instance.assembly_id = update_data.assembly_id
            if update_data.serial_number is not None:
                instance.serial_number = update_data.serial_number
            if update_data.status is not None:
                instance.status = update_data.status
            if update_data.location is not None:
                instance.location = update_data.location
            if update_data.measured_geometry is not None:
                instance.measured_geometry = update_data.measured_geometry
            if update_data.lifecycle is not None:
                instance.lifecycle = update_data.lifecycle
            if update_data.tags is not None:
                instance.tags = update_data.tags
            
            instance.updated_by = current_user.id
            instance.updated_at = datetime.now(UTC)
            instance.version += 1
            
            db.flush()
            results.append(_to_response(instance))
            
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
def delete_tool_instances(
    req: Request,
    request: BulkDeleteRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Delete tool instances in bulk.
    
    Notes:
    - For API key authentication, validates that the API key has access to all instances
    - For session authentication, only allows deleting own instances
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(req.state, 'is_api_key_auth', False)
    api_key_tags = getattr(req.state, 'api_key_tags', [])
    
    results = []
    errors = []
    
    for index, instance_id in enumerate(request.ids):
        try:
            # Get existing instance
            query = db.query(ToolInstance).filter(ToolInstance.id == instance_id)
            
            # For session auth, only allow deleting own instances
            if not is_api_key_auth:
                query = query.filter(ToolInstance.user_id == current_user.id)
            
            instance = query.first()
            
            if not instance:
                errors.append(ErrorDetail(
                    index=index,
                    id=instance_id,
                    message="Instance not found or access denied"
                ))
                continue
            
            # For API key auth, check if tags are allowed
            if is_api_key_auth and api_key_tags and instance.tags:
                if not any(tag in api_key_tags for tag in instance.tags):
                    errors.append(ErrorDetail(
                        index=index,
                        id=instance_id,
                        message="API key not authorized to delete this instance"
                    ))
                    continue
            
            response = _to_response(instance)
            db.delete(instance)
            db.flush()
            
            results.append(response)
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=index,
                id=instance_id,
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


def _to_response(instance: ToolInstance) -> ToolInstanceResponse:
    """Convert ToolInstance entity to response model."""
    return ToolInstanceResponse(
        id=instance.id,
        assembly_id=instance.assembly_id,
        serial_number=instance.serial_number,
        status=instance.status,
        location=instance.location,
        measured_geometry=instance.measured_geometry,
        lifecycle=instance.lifecycle,
        tags=instance.tags or [],
        user_id=instance.user_id,
        created_by=instance.created_by,
        updated_by=instance.updated_by,
        created_at=instance.created_at.isoformat() if instance.created_at else "",
        updated_at=instance.updated_at.isoformat() if instance.updated_at else "",
        version=instance.version
    )
