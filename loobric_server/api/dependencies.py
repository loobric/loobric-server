# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Dependency injection utilities for FastAPI endpoints.

This module provides dependency functions for handling authentication,
authorization, and other cross-cutting concerns.
"""

from typing import Callable, Optional, List, Any
from fastapi import Depends, Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from loobric_server.api.auth import require_auth, get_authenticated_user
from loobric_server.auth.authorization import require_tag_scope_access
from loobric_server.database.schema import User
from loobric_server.database.session import get_db

# Re-export commonly used dependencies
__all__ = [
    'get_current_user',
    'require_tag_access',
]

# Bearer token security scheme
bearer_scheme = HTTPBearer(auto_error=False)

def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Dependency to get the current authenticated user.
    
    This is a thin wrapper around get_authenticated_user that extracts the
    Authorization header and passes it along.
    """
    authorization = f"Bearer {credentials.credentials}" if credentials else None
    return get_authenticated_user(
        authorization=authorization,
        db=db,
        request=request
    )

def require_tag_access(
    resource_type: str,
    resource_id_param: str = "id",
    resource_tags_getter: Optional[Callable[[str, Session], List[str]]] = None
):
    """Dependency factory for tag-based access control.
    
    Args:
        resource_type: The type of resource being accessed (e.g., 'tool_assembly')
        resource_id_param: The name of the path parameter containing the resource ID
        resource_tags_getter: Optional function to retrieve tags for a resource
            Signature: (resource_id: str, db: Session) -> List[str]
            
    Returns:
        A dependency function that can be used with FastAPI's Depends()
    """
    
    async def _dependency(
        request: Request,
        resource_id: str = None,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_authenticated_user)
    ) -> None:
        """Check if the current request has access to the resource."""
        # If no resource_id was provided, try to get it from the path parameters
        if resource_id is None and hasattr(request, "path_params"):
            resource_id = request.path_params.get(resource_id_param)
        
        if not resource_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Resource ID is required for {resource_type} access check"
            )
        
        # Get the resource's tags
        resource_tags = []
        if resource_tags_getter:
            resource_tags = resource_tags_getter(resource_id, db)
        
        # Get the action from the request method
        action = {
            'GET': 'read',
            'POST': 'create',
            'PUT': 'update',
            'PATCH': 'update',
            'DELETE': 'delete'
        }.get(request.method.upper(), 'access')
        
        # Get auth info from request state
        scopes = getattr(request.state, 'scopes', [])
        api_key_tags = getattr(request.state, 'api_key_tags', [])
        
        # Check tag-based access
        from loobric_server.auth.authorization import PermissionDeniedError
        try:
            require_tag_scope_access(
                scopes=scopes,
                api_key_tags=api_key_tags,
                resource_tags=resource_tags,
                resource_type=resource_type,
                resource_id=resource_id,
                action=action
            )
        except PermissionDeniedError as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e)
            )
    
    return _dependency

# Resource tags getter functions
def get_tool_assembly_tags(resource_id: str, db: Session) -> List[str]:
    """Get tags for a tool assembly."""
    from loobric_server.database.schema import ToolAssembly
    assembly = db.query(ToolAssembly).filter(ToolAssembly.id == resource_id).first()
    return assembly.tags if assembly and assembly.tags else []

def get_tool_set_tags(resource_id: str, db: Session) -> List[str]:
    """Get tags for a tool set."""
    from loobric_server.database.schema import ToolSet
    tool_set = db.query(ToolSet).filter(ToolSet.id == resource_id).first()
    return tool_set.tags if tool_set and tool_set.tags else []

def get_tool_item_tags(resource_id: str, db: Session) -> List[str]:
    """Get tags for a tool item."""
    from loobric_server.database.schema import ToolItem
    tool_item = db.query(ToolItem).filter(ToolItem.id == resource_id).first()
    return tool_item.tags if tool_item and tool_item.tags else []

def get_tool_preset_tags(resource_id: str, db: Session) -> List[str]:
    """Get tags for a tool preset."""
    from loobric_server.database.schema import ToolPreset
    tool_preset = db.query(ToolPreset).filter(ToolPreset.id == resource_id).first()
    return tool_preset.tags if tool_preset and tool_preset.tags else []

def get_tool_instance_tags(resource_id: str, db: Session) -> List[str]:
    """Get tags for a tool instance."""
    from loobric_server.database.schema import ToolInstance
    tool_instance = db.query(ToolInstance).filter(ToolInstance.id == resource_id).first()
    return tool_instance.tags if tool_instance and tool_instance.tags else []

# Common tag-based access dependencies
get_tool_assembly_access = require_tag_access(
    resource_type="tool_assembly",
    resource_id_param="assembly_id",
    resource_tags_getter=get_tool_assembly_tags
)

get_tool_instance_access = require_tag_access(
    resource_type="tool_instance",
    resource_id_param="instance_id",
    resource_tags_getter=get_tool_instance_tags
)

get_tool_preset_access = require_tag_access(
    resource_type="tool_preset",
    resource_id_param="preset_id",
    resource_tags_getter=get_tool_preset_tags
)

get_tool_set_access = require_tag_access(
    resource_type="tool_set",
    resource_id_param="tool_set_id",
    resource_tags_getter=get_tool_set_tags
)

get_tool_item_access = require_tag_access(
    resource_type="tool_item",
    resource_id_param="item_id",
    resource_tags_getter=get_tool_item_tags
)
