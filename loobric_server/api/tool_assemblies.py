# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
ToolAssembly API endpoints.

Bulk-first design: all operations accept arrays.

Assumptions:
- POST /api/v1/tool-assemblies - Create (bulk)
- GET /api/v1/tool-assemblies - List/query with filters
- PUT /api/v1/tool-assemblies - Update (bulk) with version checking
- DELETE /api/v1/tool-assemblies - Delete (bulk)
- Multi-tenant: Users only access their own data
- Partial success: Returns per-item results and errors
"""
from typing import Annotated, Optional, List, Callable, Any
from uuid import uuid4
from datetime import datetime, UTC
from fastapi import APIRouter, Depends, Query, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db, require_auth, get_authenticated_user
from loobric_server.api.dependencies import get_tool_assembly_access
from loobric_server.database.schema import User, ToolAssembly


router = APIRouter(prefix="/api/v1/tool-assemblies", tags=["tool-assemblies"])


# Request/Response Models
class ToolAssemblyCreate(BaseModel):
    """Schema for creating a tool assembly."""
    name: str = Field(..., description="Name of the tool assembly (required)")
    description: Optional[str] = None
    components: List[dict] = Field(..., description="List of components (required)")
    computed_geometry: Optional[dict] = None
    tags: List[str] = Field(default_factory=list, description="Tags for filtering and access control")


class ToolAssemblyUpdate(BaseModel):
    """Schema for updating a tool assembly."""
    id: str
    version: int
    name: Optional[str] = None
    description: Optional[str] = None
    components: Optional[list] = None
    computed_geometry: Optional[dict] = None
    tags: Optional[list[str]] = None


class ToolAssemblyResponse(BaseModel):
    """Schema for tool assembly response."""
    id: str
    name: str
    description: Optional[str]
    components: list
    computed_geometry: Optional[dict]
    tags: list[str]
    user_id: str
    created_by: str
    updated_by: str
    created_at: str
    updated_at: str
    version: int


class BulkCreateRequest(BaseModel):
    """Bulk create request."""
    items: List[ToolAssemblyCreate]


class BulkUpdateRequest(BaseModel):
    """Bulk update request."""
    items: List[ToolAssemblyUpdate]


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
    results: List[ToolAssemblyResponse] = []
    errors: List[ErrorDetail] = []


class QueryResponse(BaseModel):
    """Response for query operations."""
    items: List[ToolAssemblyResponse]
    total: int
    limit: int
    offset: int


@router.post("", response_model=BulkOperationResponse, status_code=status.HTTP_201_CREATED)
async def create_tool_assemblies(
    request: Request,
    create_request: BulkCreateRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Create tool assemblies in bulk.
    
    Args:
        request: FastAPI request object
        create_request: Bulk create request with array of assemblies
        current_user: Authenticated user
        db: Database session
        
    Returns:
        BulkOperationResponse with success/error counts and results
        
    Notes:
    - For API key authentication, validates that all tags in the request are allowed by the API key
    - For session authentication, allows any tags
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(request.state, 'is_api_key_auth', False)
    api_key_tags = getattr(request.state, 'api_key_tags', [])
    
    results = []
    errors = []
    
    for i, item in enumerate(create_request.items):
        try:
            # Validate tags if using API key with tags
            if is_api_key_auth and api_key_tags and item.tags:
                # Check if all tags in the request are allowed by the API key
                invalid_tags = [t for t in item.tags if t not in api_key_tags]
                if invalid_tags:
                    errors.append(ErrorDetail(
                        index=i,
                        message=f"API key not authorized for tags: {', '.join(invalid_tags)}"
                    ))
                    continue
            
            # Generate new ID and timestamps
            assembly_id = str(uuid4())
            now = datetime.now(UTC)
            
            # Create assembly
            assembly = ToolAssembly(
                id=assembly_id,
                name=item.name or f"Assembly {i+1}",
                description=item.description,
                components=item.components or [],
                computed_geometry=item.computed_geometry or {},
                tags=item.tags or [],
                user_id=current_user.id,
                created_by=current_user.email,
                updated_by=current_user.email,
                created_at=now,
                updated_at=now,
                version=1
            )
            
            db.add(assembly)
            db.flush()  # Get the ID
            
            results.append(_to_response(assembly))
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=i,
                message=str(e)
            ))
    
    # Commit all successful creates if there are no errors or if we have some successful creates
    if results or not errors:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create tool assemblies: {str(e)}"
            )
    
    return BulkOperationResponse(
        success_count=len(results),
        error_count=len(errors),
        results=results,
        errors=errors
    )


@router.get("", response_model=QueryResponse)
async def list_tool_assemblies(
    request: Request,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    tags: Optional[List[str]] = Query(None, description="Filter by tags (logical AND)")
):
    """List tool assemblies with pagination and filtering.
    
    Args:
        request: FastAPI request object
        current_user: Authenticated user
        db: Database session
        limit: Max items to return
        offset: Items to skip
        tags: Filter by tags (logical AND)
        
    Returns:
        QueryResponse with assemblies, total count, limit, offset
        
    Notes:
    - For API key authentication, only returns assemblies with tags that match the API key's tags
    - For session authentication, returns all assemblies owned by the user
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(request.state, 'is_api_key_auth', False)
    api_key_tags = getattr(request.state, 'api_key_tags', [])
    
    # Base query - filter by user for session auth or all accessible assemblies for API key
    if is_api_key_auth:
        # For API keys, we need to check tag access
        query = db.query(ToolAssembly)
        
        # If API key has tags, filter by matching tags
        if api_key_tags:
            # For SQLite, we need to filter in Python since JSON querying is limited
            # We'll fetch all and filter, or use a different approach
            # For now, filter by checking if any tag matches
            from sqlalchemy import func
            # Get all assemblies and filter in Python for SQLite compatibility
            all_assemblies = query.all()
            matching_ids = [
                a.id for a in all_assemblies 
                if a.tags and any(tag in a.tags for tag in api_key_tags)
            ]
            if matching_ids:
                query = query.filter(ToolAssembly.id.in_(matching_ids))
            else:
                # No matching assemblies, return empty result
                query = query.filter(ToolAssembly.id == None)
    else:
        # For session auth, only show user's own assemblies
        user_id = str(current_user.id)
        query = db.query(ToolAssembly).filter(
            ToolAssembly.user_id == user_id
        )
    
    # Apply additional tag filters from query params
    if tags:
        for tag in tags:
            query = query.filter(ToolAssembly.tags.contains([tag]))
    
    # Get total count before pagination
    total = query.count()
    
    # Apply pagination
    assemblies = query.offset(offset).limit(limit).all()
    
    return QueryResponse(
        items=[_to_response(a) for a in assemblies],
        total=total,
        limit=limit,
        offset=offset
    )


def get_assembly_tags(assembly_id: str, db: Session) -> List[str]:
    """Helper function to get tags for a tool assembly."""
    assembly = db.query(ToolAssembly).filter(ToolAssembly.id == assembly_id).first()
    return assembly.tags if assembly else []


@router.get("/{assembly_id}", response_model=ToolAssemblyResponse)
async def get_tool_assembly(
    assembly_id: str,
    request: Request,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
    _: None = Depends(get_tool_assembly_access)
):
    """Retrieve a single ToolAssembly by ID if user has access.
    
    Access is granted if:
    - User is the owner of the assembly, or
    - User has an API key with matching tags for the assembly
    """
    assembly = db.query(ToolAssembly).filter(
        ToolAssembly.id == assembly_id
    ).first()
    
    if not assembly:
        raise HTTPException(status_code=404, detail="Tool assembly not found")
    
    # For session auth, only allow access to own resources
    is_api_key_auth = getattr(request.state, 'is_api_key_auth', False)
    if not is_api_key_auth and assembly.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Tool assembly not found")
    
    return _to_response(assembly)


def get_assembly_tags(assembly_id: str, db: Session) -> List[str]:
    """Helper function to get tags for a tool assembly."""
    assembly = db.query(ToolAssembly).filter(ToolAssembly.id == assembly_id).first()
    return assembly.tags if assembly else []


@router.put("", response_model=BulkOperationResponse)
async def update_tool_assemblies(
    request: Request,
    update_request: BulkUpdateRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Update tool assemblies in bulk.
    
    Args:
        request: FastAPI request object
        update_request: Bulk update request with array of assemblies
        current_user: Authenticated user
        db: Database session
        
    Returns:
        BulkOperationResponse with success/error counts and results
        
    Notes:
    - For API key authentication, validates that all tags in the request are allowed by the API key
    - For session authentication, allows any tags
    - Only the owner of an assembly can update it
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(request.state, 'is_api_key_auth', False)
    api_key_tags = getattr(request.state, 'api_key_tags', [])
    
    results = []
    errors = []
    has_version_conflict = False
    
    # First pass: validate all updates
    updates = []
    for i, item in enumerate(update_request.items):
        try:
            # Get existing assembly
            query = db.query(ToolAssembly).filter(ToolAssembly.id == item.id)
            
            # For session auth, only allow updating own assemblies
            if not is_api_key_auth:
                query = query.filter(ToolAssembly.user_id == current_user.id)
            
            assembly = query.first()
            
            if not assembly:
                errors.append(ErrorDetail(
                    index=i,
                    id=item.id,
                    message="Tool assembly not found or access denied"
                ))
                continue
                
            # For API key auth, check if tags are allowed
            if is_api_key_auth and api_key_tags:
                # Check if API key has access to the existing assembly's tags
                if assembly.tags and not any(tag in api_key_tags for tag in assembly.tags):
                    errors.append(ErrorDetail(
                        index=i,
                        id=item.id,
                        message="API key not authorized to update this assembly"
                    ))
                    continue
                
                # Check if new tags are allowed
                if item.tags is not None:
                    invalid_tags = [t for t in item.tags if t not in api_key_tags]
                    if invalid_tags:
                        errors.append(ErrorDetail(
                            index=i,
                            id=item.id,
                            message=f"API key not authorized for tags: {', '.join(invalid_tags)}"
                        ))
                        continue
            
            # Check version
            if assembly.version != item.version:
                has_version_conflict = True
                errors.append(ErrorDetail(
                    index=i,
                    id=item.id,
                    message=f"Version mismatch. Current version: {assembly.version}"
                ))
                continue
                
            updates.append((i, item, assembly))
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=i,
                id=getattr(item, 'id', None),
                message=str(e)
            ))
    
    # If there are version conflicts and no successful updates, return 409
    if has_version_conflict and not updates:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "success_count": 0,
                "error_count": len(errors),
                "results": [],
                "errors": [e.model_dump() for e in errors]
            }
        )
    
    # Second pass: apply updates
    for i, item, assembly in updates:
        try:
            # Update fields
            if item.name is not None:
                assembly.name = item.name
            if item.description is not None:
                assembly.description = item.description
            if item.components is not None:
                assembly.components = item.components
            if item.computed_geometry is not None:
                assembly.computed_geometry = item.computed_geometry
            if item.tags is not None:
                assembly.tags = item.tags
                
            # Update metadata
            assembly.updated_by = current_user.email
            assembly.updated_at = datetime.now(UTC)
            assembly.version += 1
            
            db.add(assembly)
            db.flush()
            
            results.append(_to_response(assembly))
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=i,
                id=item.id,
                message=str(e)
            ))
    
    # Commit all updates if there are no errors or if we have some successful updates
    if results or not errors:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update tool assemblies: {str(e)}"
            )
    
    # If we had version conflicts, return 409
    if has_version_conflict:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "success_count": len(results),
                "error_count": len(errors),
                "results": [r.model_dump() for r in results],
                "errors": [e.model_dump() for e in errors]
            }
        )
    
    return BulkOperationResponse(
        success_count=len(results),
        error_count=len(errors),
        results=results,
        errors=errors
    )


@router.delete("", response_model=BulkOperationResponse)
async def delete_tool_assemblies(
    request: Request,
    delete_request: BulkDeleteRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Delete tool assemblies in bulk.
    
    Args:
        request: FastAPI request object
        delete_request: Bulk delete request with array of IDs
        current_user: Authenticated user
        db: Database session
        
    Returns:
        BulkOperationResponse with success/error counts
        
    Notes:
    - For API key authentication, validates that the API key has access to all assemblies
    - For session authentication, only allows deleting own assemblies
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(request.state, 'is_api_key_auth', False)
    api_key_tags = getattr(request.state, 'api_key_tags', [])
    
    results = []
    errors = []
    
    # First pass: validate all deletes
    to_delete = []
    for i, assembly_id in enumerate(delete_request.ids):
        try:
            # Get existing assembly
            query = db.query(ToolAssembly).filter(ToolAssembly.id == assembly_id)
            
            # For session auth, only allow deleting own assemblies
            if not is_api_key_auth:
                query = query.filter(ToolAssembly.user_id == current_user.id)
            
            assembly = query.first()
            
            if not assembly:
                errors.append(ErrorDetail(
                    index=i,
                    id=assembly_id,
                    message="Tool assembly not found or access denied"
                ))
                continue
                
            # For API key auth, check if tags are allowed
            if is_api_key_auth and api_key_tags and assembly.tags:
                if not any(tag in api_key_tags for tag in assembly.tags):
                    errors.append(ErrorDetail(
                        index=i,
                        id=assembly_id,
                        message="API key not authorized to delete this assembly"
                    ))
                    continue
                
            to_delete.append((i, assembly))
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=i,
                id=assembly_id,
                message=str(e)
            ))
    
    # Second pass: perform deletes
    for i, assembly in to_delete:
        try:
            response_data = _to_response(assembly)
            db.delete(assembly)
            results.append(response_data)
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=i,
                id=assembly.id,
                message=str(e)
            ))
    
    # Commit all deletes if there are no errors or if we have some successful deletes
    if results or not errors:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete tool assemblies: {str(e)}"
            )
    
    return BulkOperationResponse(
        success_count=len(results),
        error_count=len(errors),
        results=results,
        errors=errors
    )


def _to_response(assembly: ToolAssembly) -> ToolAssemblyResponse:
    """Convert ToolAssembly entity to response model.
    
    Args:
        assembly: ToolAssembly entity
        
    Returns:
        ToolAssemblyResponse model
    """
    return ToolAssemblyResponse(
        id=assembly.id,
        name=assembly.name,
        description=assembly.description,
        components=assembly.components,
        computed_geometry=assembly.computed_geometry,
        tags=assembly.tags or [],
        user_id=assembly.user_id,
        created_by=assembly.created_by,
        updated_by=assembly.updated_by,
        created_at=assembly.created_at.isoformat(),
        updated_at=assembly.updated_at.isoformat(),
        version=assembly.version
    )
