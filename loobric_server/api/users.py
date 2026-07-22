# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
User management API endpoints.

Provides REST API for user administration and role management.

Assumptions:
- Only admin users can modify roles
- Manufacturer role requires manufacturer_profile
- Role changes are audited
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db, get_authenticated_user
from loobric_server.database.schema import User
from loobric_server.auth.user import get_user_by_id


router = APIRouter(prefix="/api/v1/users", tags=["users"])


# Request/Response Models
class ManufacturerProfile(BaseModel):
    """Manufacturer profile data."""
    company_name: str
    website: Optional[str] = None
    description: Optional[str] = None
    partnership_tier: Optional[str] = None
    analytics_enabled: Optional[bool] = None


class RoleUpdateRequest(BaseModel):
    """Request to update user role."""
    role: str
    manufacturer_profile: Optional[ManufacturerProfile] = None


class UserUpdateRequest(BaseModel):
    """Request to update user details."""
    is_verified: Optional[bool] = None
    manufacturer_profile: Optional[dict] = None


class UserResponse(BaseModel):
    """User response model."""
    id: str
    email: str
    role: str
    is_active: bool
    is_admin: bool
    is_verified: bool
    manufacturer_profile: Optional[dict] = None


@router.patch("/{user_id}/roles", response_model=UserResponse)
def update_user_role(
    user_id: str,
    request: RoleUpdateRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Update user role (admin only).
    
    Args:
        user_id: ID of user to update
        request: Role update request
        current_user: Authenticated user (must be admin)
        db: Database session
        
    Returns:
        UserResponse: Updated user
        
    Raises:
        HTTPException: 403 if not admin, 404 if user not found
    """
    # Check admin permission
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can modify user roles"
        )
    
    # Get target user
    target_user = get_user_by_id(db, user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update role
    target_user.role = request.role
    
    # Update manufacturer profile if provided
    if request.manufacturer_profile:
        target_user.manufacturer_profile = request.manufacturer_profile.model_dump()
    
    # If changing to non-manufacturer role, keep profile for history
    # but don't require it
    
    db.commit()
    db.refresh(target_user)
    
    return UserResponse(
        id=target_user.id,
        email=target_user.email,
        role=target_user.role,
        is_active=target_user.is_active,
        is_admin=target_user.is_admin,
        is_verified=target_user.is_verified,
        manufacturer_profile=target_user.manufacturer_profile
    )


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    request: UserUpdateRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Update user details (admin only).
    
    Args:
        user_id: ID of user to update
        request: User update request
        current_user: Authenticated user (must be admin)
        db: Database session
        
    Returns:
        UserResponse: Updated user
        
    Raises:
        HTTPException: 403 if not admin, 404 if user not found
    """
    # Check admin permission
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can modify users"
        )
    
    # Get target user
    target_user = get_user_by_id(db, user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update fields
    if request.is_verified is not None:
        target_user.is_verified = request.is_verified
    
    if request.manufacturer_profile:
        # Merge with existing profile - need to create new dict for SQLAlchemy to detect change
        existing = dict(target_user.manufacturer_profile or {})
        existing.update(request.manufacturer_profile)
        target_user.manufacturer_profile = existing
        # Mark as modified for SQLAlchemy
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(target_user, "manufacturer_profile")
    
    db.commit()
    db.refresh(target_user)
    
    return UserResponse(
        id=target_user.id,
        email=target_user.email,
        role=target_user.role,
        is_active=target_user.is_active,
        is_admin=target_user.is_admin,
        is_verified=target_user.is_verified,
        manufacturer_profile=target_user.manufacturer_profile
    )


class UserCreateRequest(BaseModel):
    """Request to create a user."""
    email: EmailStr
    password: str
    role: str = "user"
    manufacturer_profile: Optional[dict] = None


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_admin(
    request: UserCreateRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """Create user (admin only).
    
    Args:
        request: User creation request
        current_user: Authenticated user (must be admin)
        db: Database session
        
    Returns:
        UserResponse: Created user
        
    Raises:
        HTTPException: 403 if not admin
    """
    from loobric_server.auth.user import create_user
    
    # Check admin permission
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can create users"
        )
    
    # Create user
    user = create_user(db, request.email, request.password)
    user.role = request.role
    
    if request.manufacturer_profile:
        user.manufacturer_profile = request.manufacturer_profile
    
    db.commit()
    db.refresh(user)
    
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        is_admin=user.is_admin,
        is_verified=user.is_verified,
        manufacturer_profile=user.manufacturer_profile
    )
