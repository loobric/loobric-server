# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Manufacturer Catalog API endpoints.

Provides REST API for manufacturer catalog management.

Assumptions:
- Only manufacturer role users can create/modify catalogs
- Catalogs contain arrays of ToolItem IDs
- Only published catalogs visible to public
- Same tool can be in multiple catalogs
"""
from typing import Optional, List
from uuid import uuid4
from datetime import datetime, UTC
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db, get_authenticated_user
from loobric_server.database.schema import User, ManufacturerCatalog, ToolItem


router = APIRouter(prefix="/api/v1/catalogs", tags=["catalogs"])


# Request/Response Models
class CatalogCreate(BaseModel):
    """Schema for creating a catalog."""
    name: str
    description: Optional[str] = None
    catalog_year: Optional[int] = None
    tool_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    is_published: bool = False


class CatalogUpdate(BaseModel):
    """Schema for updating a catalog."""
    name: Optional[str] = None
    description: Optional[str] = None
    catalog_year: Optional[int] = None
    tool_ids: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    is_published: Optional[bool] = None


class CatalogResponse(BaseModel):
    """Schema for catalog response."""
    id: str
    name: str
    description: Optional[str]
    catalog_year: Optional[int]
    tool_ids: List[str]
    tags: List[str]
    is_published: bool
    user_id: str
    created_at: str
    updated_at: str
    version: int
    tool_count: Optional[int] = None


class CatalogListResponse(BaseModel):
    """Schema for catalog list response."""
    catalogs: List[CatalogResponse]
    total: int


class CatalogAnalyticsResponse(BaseModel):
    """Schema for catalog analytics."""
    total_copies: int
    tool_popularity: List[dict]


@router.post("", response_model=CatalogResponse, status_code=status.HTTP_201_CREATED)
def create_catalog(
    request: CatalogCreate,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Create a new manufacturer catalog.
    
    Args:
        request: Catalog creation data
        current_user: Authenticated user (must be manufacturer)
        db: Database session
        
    Returns:
        CatalogResponse: Created catalog
        
    Raises:
        HTTPException: 403 if not manufacturer role
    """
    # Check manufacturer permission
    if current_user.role != "manufacturer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only manufacturer users can create catalogs"
        )
    
    # Create catalog
    catalog = ManufacturerCatalog(
        id=str(uuid4()),
        name=request.name,
        description=request.description,
        catalog_year=request.catalog_year,
        tool_ids=request.tool_ids,
        tags=request.tags,
        is_published=request.is_published,
        user_id=current_user.id,
        created_by=current_user.id,
        updated_by=current_user.id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        version=1
    )
    
    db.add(catalog)
    db.commit()
    db.refresh(catalog)
    
    return _to_response(catalog)


@router.get("", response_model=CatalogListResponse)
def list_catalogs(
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by"),
    db: Session = Depends(get_db)
):
    """List published catalogs (public endpoint).
    
    Args:
        tags: Optional comma-separated tags to filter
        db: Database session
        
    Returns:
        CatalogListResponse: List of published catalogs
    """
    # Only show published catalogs to public
    query = db.query(ManufacturerCatalog).filter(
        ManufacturerCatalog.is_published == True
    )
    
    catalogs = query.all()
    
    # Filter by tags if provided (in Python for SQLite compatibility)
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        catalogs = [
            c for c in catalogs
            if c.tags and all(tag in c.tags for tag in tag_list)
        ]
    
    return CatalogListResponse(
        catalogs=[_to_response(c) for c in catalogs],
        total=len(catalogs)
    )


@router.get("/{catalog_id}", response_model=CatalogResponse)
def get_catalog(
    catalog_id: str,
    current_user: Optional[User] = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Get a single catalog by ID.
    
    Args:
        catalog_id: Catalog ID
        current_user: Optional authenticated user
        db: Database session
        
    Returns:
        CatalogResponse: Catalog details
        
    Raises:
        HTTPException: 404 if not found or not published (unless owner)
    """
    catalog = db.query(ManufacturerCatalog).filter(
        ManufacturerCatalog.id == catalog_id
    ).first()
    
    if not catalog:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog not found"
        )
    
    # Allow owner to see unpublished, others only see published
    if not catalog.is_published:
        if not current_user or catalog.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Catalog not found"
            )
    
    return _to_response(catalog)


@router.patch("/{catalog_id}", response_model=CatalogResponse)
def update_catalog(
    catalog_id: str,
    request: CatalogUpdate,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Update a catalog (owner only).
    
    Args:
        catalog_id: Catalog ID
        request: Update data
        current_user: Authenticated user (must be owner)
        db: Database session
        
    Returns:
        CatalogResponse: Updated catalog
        
    Raises:
        HTTPException: 403 if not owner, 404 if not found
    """
    catalog = db.query(ManufacturerCatalog).filter(
        ManufacturerCatalog.id == catalog_id
    ).first()
    
    if not catalog:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog not found"
        )
    
    # Check ownership
    if catalog.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only catalog owner can update it"
        )
    
    # Update fields
    if request.name is not None:
        catalog.name = request.name
    if request.description is not None:
        catalog.description = request.description
    if request.catalog_year is not None:
        catalog.catalog_year = request.catalog_year
    if request.tool_ids is not None:
        catalog.tool_ids = request.tool_ids
    if request.tags is not None:
        catalog.tags = request.tags
    if request.is_published is not None:
        catalog.is_published = request.is_published
    
    catalog.updated_by = current_user.id
    catalog.updated_at = datetime.now(UTC)
    catalog.version += 1
    
    db.commit()
    db.refresh(catalog)
    
    return _to_response(catalog)


@router.get("/{catalog_id}/analytics", response_model=CatalogAnalyticsResponse)
def get_catalog_analytics(
    catalog_id: str,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Get analytics for a catalog (owner only).
    
    Args:
        catalog_id: Catalog ID
        current_user: Authenticated user (must be owner)
        db: Database session
        
    Returns:
        CatalogAnalyticsResponse: Analytics data
        
    Raises:
        HTTPException: 403 if not owner, 404 if not found
    """
    catalog = db.query(ManufacturerCatalog).filter(
        ManufacturerCatalog.id == catalog_id
    ).first()
    
    if not catalog:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog not found"
        )
    
    # Check ownership
    if catalog.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only catalog owner can view analytics"
        )
    
    # Count copies for each tool in catalog
    tool_popularity = []
    total_copies = 0
    
    for tool_id in catalog.tool_ids:
        # Count how many ToolItems have this as parent_tool_id
        copy_count = db.query(ToolItem).filter(
            ToolItem.parent_tool_id == tool_id
        ).count()
        
        total_copies += copy_count
        tool_popularity.append({
            "tool_id": tool_id,
            "copies": copy_count
        })
    
    return CatalogAnalyticsResponse(
        total_copies=total_copies,
        tool_popularity=tool_popularity
    )


def _to_response(catalog: ManufacturerCatalog) -> CatalogResponse:
    """Convert ManufacturerCatalog entity to response model.
    
    Args:
        catalog: ManufacturerCatalog entity
        
    Returns:
        CatalogResponse model
    """
    return CatalogResponse(
        id=catalog.id,
        name=catalog.name,
        description=catalog.description,
        catalog_year=catalog.catalog_year,
        tool_ids=catalog.tool_ids,
        tags=catalog.tags,
        is_published=catalog.is_published,
        user_id=catalog.user_id,
        created_at=catalog.created_at.isoformat(),
        updated_at=catalog.updated_at.isoformat(),
        version=catalog.version,
        tool_count=len(catalog.tool_ids)
    )
