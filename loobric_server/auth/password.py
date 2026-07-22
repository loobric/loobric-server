# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Password hashing and verification using bcrypt.

Assumptions:
- Uses bcrypt for password hashing
- Each hash includes unique salt
- Hashes are not reversible
"""
import bcrypt


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.
    
    Args:
        password: Plain text password
        
    Returns:
        str: Hashed password with salt
        
    Assumptions:
    - Each call generates unique hash (random salt)
    - Cost factor is 12 (good balance of security and performance)
    """
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a hash.
    
    Args:
        password: Plain text password to verify
        password_hash: Hashed password to check against
        
    Returns:
        bool: True if password matches, False otherwise
        
    Assumptions:
    - Uses constant-time comparison
    - Returns False on any error (invalid hash, etc.)
    """
    try:
        password_bytes = password.encode('utf-8')
        hash_bytes = password_hash.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception:
        return False
