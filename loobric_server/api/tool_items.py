# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
ToolItem API endpoints.

Bulk-first design: all operations accept arrays.

Assumptions:
- POST /api/v1/tool-items - Create (bulk)
- GET /api/v1/tool-items - List/query with filters
- PUT /api/v1/tool-items - Update (bulk) with version checking
- DELETE /api/v1/tool-items - Delete (bulk)
- Multi-tenant: Users only access their own data
- Partial success: Returns per-item results and errors
"""
from typing import Annotated, Optional, List
from uuid import uuid4
from datetime import datetime, UTC
from fastapi import APIRouter, Depends, Query, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from loobric_server.api.auth import get_db, require_auth, get_authenticated_user
from loobric_server.api.dependencies import get_tool_item_access
from loobric_server.database.schema import User, ToolItem


router = APIRouter(prefix="/api/v1/tool-items", tags=["tool-items"])


# Request/Response Models
class ToolItemCreate(BaseModel):
    """Schema for creating a tool item.
    
    Assumptions:
    - Type is required but validated in endpoint for partial success
    - Other fields are optional
    - If parent_tool_id is provided, copies data from parent ToolItem in manufacturer's account
    """
    type: Optional[str] = Field(None, description="Tool type: cutting_tool, holder, insert, adapter")
    manufacturer: Optional[str] = None
    product_code: Optional[str] = None
    description: Optional[str] = None
    geometry: Optional[dict] = None
    material: Optional[dict] = None
    iso_13399_reference: Optional[str] = None
    tags: List[str] = Field(default_factory=list, description="Tags for filtering and access control")
    parent_tool_id: Optional[str] = Field(None, description="ID of catalog tool to copy from")


class ToolItemUpdate(BaseModel):
    """Schema for updating a tool item."""
    id: str
    version: Optional[int] = None  # Optional for /bulk endpoint, will fetch current version
    type: Optional[str] = None
    manufacturer: Optional[str] = None
    product_code: Optional[str] = None
    description: Optional[str] = None
    geometry: Optional[dict] = None
    material: Optional[dict] = None
    iso_13399_reference: Optional[str] = None
    tags: Optional[List[str]] = None


class ToolItemResponse(BaseModel):
    """Schema for tool item response."""
    id: str
    type: str
    manufacturer: Optional[str]
    product_code: Optional[str]
    description: Optional[str]
    geometry: Optional[dict]
    material: Optional[dict]
    iso_13399_reference: Optional[str]
    tags: List[str]
    parent_tool_id: Optional[str]
    user_id: str
    created_by: str
    updated_by: str
    created_at: str
    updated_at: str
    version: int


class BulkCreateRequest(BaseModel):
    """Bulk create request."""
    items: List[ToolItemCreate]


class BulkPostRequest(BaseModel):
    """Bulk post request (alternate format for /bulk endpoint)."""
    tools: List[ToolItemCreate]


class BulkUpdateRequest(BaseModel):
    """Bulk update request."""
    items: List[ToolItemUpdate]


class BulkPatchRequest(BaseModel):
    """Bulk patch request (alternate format for /bulk endpoint)."""
    updates: List[ToolItemUpdate]


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
    results: List[ToolItemResponse] = []
    errors: List[ErrorDetail] = []


class QueryResponse(BaseModel):
    """Response for query operations."""
    items: List[ToolItemResponse]
    total: int
    limit: int
    offset: int


@router.post("/bulk", status_code=status.HTTP_201_CREATED)
def bulk_post_tool_items(
    req: Request,
    request: BulkPostRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Bulk create tool items (alternate endpoint format).
    
    Returns:
        dict: {"tools_created": count, "tool_ids": [...]}
    """
    # Convert to standard format and call main create function
    standard_request = BulkCreateRequest(items=request.tools)
    result = _create_tool_items_impl(req, standard_request, current_user, db)
    
    return {
        "tools_created": result.success_count,
        "tool_ids": [r.id for r in result.results]
    }


@router.post("", response_model=BulkOperationResponse)
def create_tool_items(
    req: Request,
    request: BulkCreateRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Create tool items in bulk."""
    return _create_tool_items_impl(req, request, current_user, db)


def _create_tool_items_impl(
    req: Request,
    request: BulkCreateRequest,
    current_user: User,
    db: Session
) -> BulkOperationResponse:
    """Internal implementation for bulk create.
    
    Args:
        req: FastAPI request object
        request: Bulk create request with array of items
        current_user: Authenticated user
        db: Database session
        
    Returns:
        BulkOperationResponse with success/error counts and results
        
    Notes:
    - For API key authentication, validates that all tags in the request are allowed by the API key
    - For session authentication, allows any tags
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(req.state, 'is_api_key_auth', False)
    api_key_tags = getattr(req.state, 'api_key_tags', [])
    
    results = []
    errors = []
    
    for index, item_data in enumerate(request.items):
        try:
            # Validate tags if using API key with tags
            if is_api_key_auth and api_key_tags and item_data.tags:
                # Check if all tags in the request are allowed by the API key
                invalid_tags = [t for t in item_data.tags if t not in api_key_tags]
                if invalid_tags:
                    errors.append(ErrorDetail(
                        index=index,
                        message=f"API key not authorized for tags: {', '.join(invalid_tags)}"
                    ))
                    continue
            
            # If parent_tool_id provided, copy from parent
            if item_data.parent_tool_id:
                parent = db.query(ToolItem).filter(ToolItem.id == item_data.parent_tool_id).first()
                if not parent:
                    raise ValueError(f"Parent tool {item_data.parent_tool_id} not found")
                
                # Copy data from parent, allow overrides from request
                tool_item = ToolItem(
                    id=str(uuid4()),
                    type=item_data.type or parent.type,
                    manufacturer=item_data.manufacturer or parent.manufacturer,
                    product_code=item_data.product_code or parent.product_code,
                    description=item_data.description or parent.description,
                    geometry=item_data.geometry or parent.geometry,
                    material=item_data.material or parent.material,
                    iso_13399_reference=item_data.iso_13399_reference or parent.iso_13399_reference,
                    tags=item_data.tags or parent.tags or [],
                    parent_tool_id=item_data.parent_tool_id,
                    user_id=current_user.id,
                    created_by=current_user.id,
                    updated_by=current_user.id
                )
            else:
                # Validate required fields for new tools
                if not item_data.type:
                    raise ValueError("Field 'type' is required")
                
                # Create tool item
                tool_item = ToolItem(
                    id=str(uuid4()),
                    type=item_data.type,
                    manufacturer=item_data.manufacturer,
                    product_code=item_data.product_code,
                    description=item_data.description,
                    geometry=item_data.geometry,
                    material=item_data.material,
                    iso_13399_reference=item_data.iso_13399_reference,
                    tags=item_data.tags or [],
                    parent_tool_id=None,
                    user_id=current_user.id,
                    created_by=current_user.id,
                    updated_by=current_user.id
                )
            
            db.add(tool_item)
            db.flush()  # Flush to get the generated timestamps
            
            results.append(_to_response(tool_item))
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=index,
                message=str(e)
            ))
    
    # Commit all successful creates
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
def list_tool_items(
    req: Request,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
    type: Optional[str] = Query(None, description="Filter by tool type"),
    manufacturer: Optional[str] = Query(None, description="Filter by manufacturer"),
    product_code: Optional[str] = Query(None, description="Filter by product code"),
    tags: Optional[List[str]] = Query(None, description="Filter by tags (logical AND)"),
    limit: int = Query(100, ge=1, le=1000, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip")
):
    """List tool items with filters and pagination.
    
    Notes:
    - For API key authentication, only returns tool items with tags that match the API key's tags
    - For session authentication, returns all tool items owned by the user
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(req.state, 'is_api_key_auth', False)
    api_key_tags = getattr(req.state, 'api_key_tags', [])
    
    # Base query - filter by user for session auth or all accessible items for API key
    if is_api_key_auth:
        # For API keys, we need to check tag access
        query = db.query(ToolItem)
        
        # If API key has tags, filter by matching tags
        if api_key_tags:
            # Get all items and filter in Python for SQLite compatibility
            all_items = query.all()
            matching_ids = [
                i.id for i in all_items 
                if i.tags and any(tag in i.tags for tag in api_key_tags)
            ]
            if matching_ids:
                query = query.filter(ToolItem.id.in_(matching_ids))
            else:
                # No matching items, return empty result
                query = query.filter(ToolItem.id == None)
    else:
        # For session auth, only show user's own items
        query = db.query(ToolItem).filter(ToolItem.user_id == current_user.id)
    
    # Apply filters
    if type:
        query = query.filter(ToolItem.type == type)
    if manufacturer:
        query = query.filter(ToolItem.manufacturer == manufacturer)
    if product_code:
        query = query.filter(ToolItem.product_code == product_code)
    
    # Apply additional tag filters from query params
    if tags:
        for tag in tags:
            query = query.filter(ToolItem.tags.contains([tag]))
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    items = query.offset(offset).limit(limit).all()
    
    return QueryResponse(
        items=[_to_response(item) for item in items],
        total=total,
        limit=limit,
        offset=offset
    )


@router.get("/{item_id}", response_model=ToolItemResponse)
def get_tool_item(
    item_id: str,
    req: Request,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
    _: None = Depends(get_tool_item_access)
):
    """Retrieve a single ToolItem by ID if user has access.
    
    Access is granted if:
    - User is the owner of the tool item, or
    - User has an API key with matching tags for the tool item
    """
    item = db.query(ToolItem).filter(
        ToolItem.id == item_id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Tool item not found")
    
    # For session auth, only allow access to own resources
    is_api_key_auth = getattr(req.state, 'is_api_key_auth', False)
    if not is_api_key_auth and item.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Tool item not found")
    
    return _to_response(item)


@router.patch("/bulk")
def bulk_patch_tool_items(
    req: Request,
    request: BulkPatchRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Bulk update tool items (alternate endpoint format).
    
    Returns:
        dict: {"tools_updated": count}
    """
    # Convert to standard format and call main update function
    standard_request = BulkUpdateRequest(items=request.updates)
    result = _update_tool_items_impl(req, standard_request, current_user, db)
    
    return {
        "tools_updated": result.success_count
    }


@router.put("", response_model=BulkOperationResponse)
def update_tool_items(
    req: Request,
    request: BulkUpdateRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Update tool items in bulk."""
    return _update_tool_items_impl(req, request, current_user, db)


def _update_tool_items_impl(
    req: Request,
    request: BulkUpdateRequest,
    current_user: User,
    db: Session
) -> BulkOperationResponse:
    """Internal implementation for bulk update.
    
    Notes:
    - For API key authentication, validates that all tags in the request are allowed by the API key
    - For session authentication, allows any tags
    - Only the owner of a tool item can update it
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(req.state, 'is_api_key_auth', False)
    api_key_tags = getattr(req.state, 'api_key_tags', [])
    
    results = []
    errors = []
    
    for index, update_data in enumerate(request.items):
        try:
            # Get existing item
            query = db.query(ToolItem).filter(ToolItem.id == update_data.id)
            
            # For session auth, only allow updating own items
            if not is_api_key_auth:
                query = query.filter(ToolItem.user_id == current_user.id)
            
            item = query.first()
            
            if not item:
                errors.append(ErrorDetail(
                    index=index,
                    id=update_data.id,
                    message="Item not found or access denied"
                ))
                continue
            
            # For API key auth, check if tags are allowed
            if is_api_key_auth and api_key_tags:
                # Check if API key has access to the existing item's tags
                if item.tags and not any(tag in api_key_tags for tag in item.tags):
                    errors.append(ErrorDetail(
                        index=index,
                        id=update_data.id,
                        message="API key not authorized to update this item"
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
            
            # Check version for optimistic locking (if version provided)
            if update_data.version is not None and item.version != update_data.version:
                errors.append(ErrorDetail(
                    index=index,
                    id=update_data.id,
                    message=f"Version conflict: expected {item.version}, got {update_data.version}"
                ))
                continue
            
            # Apply updates
            if update_data.type is not None:
                item.type = update_data.type
            if update_data.manufacturer is not None:
                item.manufacturer = update_data.manufacturer
            if update_data.product_code is not None:
                item.product_code = update_data.product_code
            if update_data.description is not None:
                item.description = update_data.description
            if update_data.geometry is not None:
                item.geometry = update_data.geometry
            if update_data.material is not None:
                item.material = update_data.material
            if update_data.iso_13399_reference is not None:
                item.iso_13399_reference = update_data.iso_13399_reference
            if update_data.tags is not None:
                item.tags = update_data.tags
            
            # Update metadata
            item.updated_by = current_user.id
            item.updated_at = datetime.now(UTC)
            item.version += 1
            
            db.flush()
            results.append(_to_response(item))
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=index,
                id=update_data.id,
                message=str(e)
            ))
    
    # Commit all successful updates
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
def delete_tool_items(
    req: Request,
    request: BulkDeleteRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Delete tool items in bulk.
    
    Notes:
    - For API key authentication, validates that the API key has access to all items
    - For session authentication, only allows deleting own items
    """
    # Get API key tags if using API key auth
    is_api_key_auth = getattr(req.state, 'is_api_key_auth', False)
    api_key_tags = getattr(req.state, 'api_key_tags', [])
    
    results = []
    errors = []
    
    for index, item_id in enumerate(request.ids):
        try:
            # Get existing item
            query = db.query(ToolItem).filter(ToolItem.id == item_id)
            
            # For session auth, only allow deleting own items
            if not is_api_key_auth:
                query = query.filter(ToolItem.user_id == current_user.id)
            
            item = query.first()
            
            if not item:
                errors.append(ErrorDetail(
                    index=index,
                    id=item_id,
                    message="Item not found or access denied"
                ))
                continue
            
            # For API key auth, check if tags are allowed
            if is_api_key_auth and api_key_tags and item.tags:
                if not any(tag in api_key_tags for tag in item.tags):
                    errors.append(ErrorDetail(
                        index=index,
                        id=item_id,
                        message="API key not authorized to delete this item"
                    ))
                    continue
            
            # Store response before deletion
            response = _to_response(item)
            
            # Delete item
            db.delete(item)
            db.flush()
            
            results.append(response)
            
        except Exception as e:
            errors.append(ErrorDetail(
                index=index,
                id=item_id,
                message=str(e)
            ))
    
    # Commit all successful deletes
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


def _to_response(item: ToolItem) -> ToolItemResponse:
    """Convert ToolItem entity to response model.
    
    Args:
        item: ToolItem entity
        
    Returns:
        ToolItemResponse model
    """
    return ToolItemResponse(
        id=item.id,
        type=item.type,
        manufacturer=item.manufacturer,
        product_code=item.product_code,
        description=item.description,
        geometry=item.geometry,
        material=item.material,
        iso_13399_reference=item.iso_13399_reference,
        tags=item.tags or [],
        parent_tool_id=item.parent_tool_id,
        user_id=item.user_id,
        created_by=item.created_by,
        updated_by=item.updated_by,
        created_at=item.created_at.isoformat() if item.created_at else "",
        updated_at=item.updated_at.isoformat() if item.updated_at else "",
        version=item.version
    )
