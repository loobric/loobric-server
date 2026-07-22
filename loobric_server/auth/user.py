# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
User account management functions.

Handles user creation, authentication, password management, and account operations.

Assumptions:
- Functional programming style (pure functions where possible)
- All functions accept session parameter
- Password reset tokens expire after 1 hour
- Tokens are single-use only
"""
import secrets
from datetime import datetime, UTC, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from loobric_server.auth.password import hash_password, verify_password
from loobric_server.database.schema import User, PasswordResetToken


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


class InvalidTokenError(Exception):
    """Raised when password reset token is invalid or expired."""
    pass


def create_user(session: Session, email: str, password: str) -> User:
    """Create a new user account.
    
    Args:
        session: Database session
        email: User email (unique)
        password: Plain text password (will be hashed)
        
    Returns:
        User: Created user object
        
    Raises:
        IntegrityError: If email already exists
        
    Assumptions:
    - Email is case-insensitive
    - Password is hashed with bcrypt
    - User is active by default
    - First user created becomes admin automatically
    """
    from loobric_server.auth.password import hash_password
    
    # Normalize email to lowercase
    email = email.lower()
    
    # Hash password
    password_hash = hash_password(password)
    
    # Check if this is the first user (admin)
    user_count = session.query(User).count()
    is_admin = (user_count == 0)
    
    # Create user
    user = User(
        email=email,
        password_hash=password_hash,
        is_active=True,
        is_admin=is_admin
    )
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    return user


def authenticate_user(session: Session, email: str, password: str) -> Optional[User]:
    """Authenticate a user with email and password.
    
    Args:
        session: Database session
        email: User email address
        password: Plain text password
        
    Returns:
        User: User object if authentication succeeds, None otherwise
        
    Assumptions:
    - Returns None for non-existent users
    - Returns None for incorrect passwords
    - Returns None for inactive users
    - Does not raise exceptions
    """
    user = get_user_by_email(session, email)
    
    if user is None:
        return None
    
    if not user.is_active:
        return None
    
    if not verify_password(password, user.password_hash):
        return None
    
    return user


def get_user_by_email(session: Session, email: str) -> Optional[User]:
    """Get user by email address.
    
    Args:
        session: Database session
        email: User email address
        
    Returns:
        User: User object if found, None otherwise
        
    Assumptions:
    - Email lookup is case-insensitive
    """
    stmt = select(User).where(User.email == email.lower().strip())
    return session.scalar(stmt)


def get_user_by_id(session: Session, user_id: str) -> Optional[User]:
    """Get user by ID.
    
    Args:
        session: Database session
        user_id: User ID (UUID)
        
    Returns:
        User: User object if found, None otherwise
    """
    return session.get(User, user_id)


def update_user_password(
    session: Session,
    user_id: str,
    old_password: str,
    new_password: str
) -> None:
    """Update user password with verification of old password.
    
    Args:
        session: Database session
        user_id: User ID
        old_password: Current password (for verification)
        new_password: New password to set
        
    Raises:
        AuthenticationError: If old password is incorrect
        ValueError: If user not found
        
    Assumptions:
    - Old password must be verified
    - Version increments on update
    """
    user = get_user_by_id(session, user_id)
    
    if user is None:
        raise ValueError(f"User {user_id} not found")
    
    if not verify_password(old_password, user.password_hash):
        raise AuthenticationError("Incorrect old password")
    
    user.password_hash = hash_password(new_password)
    user.version += 1
    user.updated_at = datetime.now(UTC)
    
    session.commit()


def deactivate_user(session: Session, user_id: str) -> None:
    """Deactivate a user account.
    
    Args:
        session: Database session
        user_id: User ID
        
    Raises:
        ValueError: If user not found
        
    Assumptions:
    - Inactive users cannot authenticate
    - Account data is preserved (soft delete)
    """
    user = get_user_by_id(session, user_id)
    
    if user is None:
        raise ValueError(f"User {user_id} not found")
    
    user.is_active = False
    user.version += 1
    user.updated_at = datetime.now(UTC)
    
    session.commit()


def create_password_reset_token(session: Session, user_id: str) -> str:
    """Create a password reset token for a user.
    
    Args:
        session: Database session
        user_id: User ID
        
    Returns:
        str: Plain text token (to send to user via email)
        
    Raises:
        ValueError: If user not found
        
    Assumptions:
    - Token expires in 1 hour
    - Token is cryptographically secure (32 bytes)
    - Token is hashed before storage
    - Returns plain token (only time it's available)
    """
    user = get_user_by_id(session, user_id)
    
    if user is None:
        raise ValueError(f"User {user_id} not found")
    
    # Generate cryptographically secure token
    token = secrets.token_urlsafe(32)
    
    # Hash token for storage
    token_hash = hash_password(token)
    
    # Create reset token record
    reset_token = PasswordResetToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(hours=1)
    )
    
    session.add(reset_token)
    session.commit()
    
    return token


def reset_password_with_token(
    session: Session,
    token: str,
    new_password: str
) -> None:
    """Reset user password using a reset token.
    
    Args:
        session: Database session
        token: Plain text reset token
        new_password: New password to set
        
    Raises:
        InvalidTokenError: If token is invalid, expired, or already used
        
    Assumptions:
    - Token is single-use (deleted after successful use)
    - Expired tokens are rejected
    - User version increments
    """
    # Find all reset tokens (need to check hashes)
    stmt = select(PasswordResetToken)
    all_tokens = session.scalars(stmt).all()
    
    matching_token = None
    for reset_token in all_tokens:
        if verify_password(token, reset_token.token_hash):
            matching_token = reset_token
            break
    
    if matching_token is None:
        raise InvalidTokenError("Invalid or already used token")
    
    # Check expiration
    # Ensure both datetimes are timezone-aware for comparison
    expires_at = matching_token.expires_at
    if expires_at.tzinfo is None:
        # Make naive datetime timezone-aware (assume UTC)
        expires_at = expires_at.replace(tzinfo=UTC)
    
    if datetime.now(UTC) > expires_at:
        # Delete expired token
        session.delete(matching_token)
        session.commit()
        raise InvalidTokenError("Token has expired")
    
    # Get user
    user = get_user_by_id(session, matching_token.user_id)
    
    if user is None:
        raise ValueError("User not found")
    
    # Update password
    user.password_hash = hash_password(new_password)
    user.version += 1
    user.updated_at = datetime.now(UTC)
    
    # Delete token (single use)
    session.delete(matching_token)
    
    session.commit()
