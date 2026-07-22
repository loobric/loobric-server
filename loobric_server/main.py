# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Main FastAPI application entry point.

This module creates and configures the FastAPI application.

Assumptions:
- FastAPI instance should include OpenAPI documentation
- Authentication middleware is optional based on settings
- API versioning is handled via path prefix
"""
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from loobric_server.config import settings
from loobric_server.version import __version__ as SERVER_VERSION, build_info
from loobric_server.api.auth import router as auth_router
from loobric_server.api.backup_api import router as backup_router
from loobric_server.api.users import router as users_router
from loobric_server.api.catalogs import router as catalogs_router
from loobric_server.api.tool_items import router as tool_items_router
from loobric_server.api.tool_assemblies import router as tool_assemblies_router
from loobric_server.api.tool_instances import router as tool_instances_router
from loobric_server.api.tool_presets import router as tool_presets_router
from loobric_server.api.tool_usage import router as tool_usage_router
from loobric_server.api.audit_log_api import router as audit_log_router
from loobric_server.api.changes_api import router as changes_router
from loobric_server.api.tool_instance_records import router as tool_instance_records_router
from loobric_server.api.tool_catalog_records import router as tool_catalog_records_router
from loobric_server.api.tool_table_entry_records import router as tool_table_entry_records_router
from loobric_server.api.tool_set_records import router as tool_set_records_router
from loobric_server.api.machine_records import router as machine_records_router
from loobric_server.api.instance_inbox import router as instance_inbox_router
from loobric_server.api.account import router as account_router
from loobric_server.api.admin import router as admin_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.
    
    Returns:
        FastAPI: Configured FastAPI application instance
        
    Assumptions:
    - OpenAPI docs are enabled by default
    - Title and version are set for documentation
    - CORS is not configured yet (will be added later if needed)
    - Database schema is initialized on startup
    """
    # Initialize database schema
    from loobric_server.database.session import init_db
    init_db()
    
    # Print database configuration on startup
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        # Extract the path from sqlite:///path
        db_path = db_url.replace("sqlite:///", "")
        # Resolve to absolute path
        if db_path.startswith("./"):
            db_path = db_path[2:]
        abs_path = Path(db_path).resolve()
        print(f"Database: {abs_path}")
        print(f"Database exists: {abs_path.exists()}")
    else:
        print(f"Database: {db_url}")
    
    app = FastAPI(
        title="Loobric Server",
        description="Vendor-neutral tool data synchronization system",
        version=SERVER_VERSION,
        docs_url=f"/api/{settings.api_version}/docs",
        redoc_url=f"/api/{settings.api_version}/redoc",
        openapi_url=f"/api/{settings.api_version}/openapi.json",
    )

    # Health check endpoint (before mounting static files and routers)
    @app.get("/api/health")
    async def health_check():
        """API health check endpoint.

        Returns:
            dict: Service status information
        """
        return {
            "service": "loobric_server",
            "version": SERVER_VERSION,
            "status": "running"
        }

    @app.get(f"/api/{settings.api_version}/version")
    async def version_info():
        """Server build identity — version + git commit. Unauthenticated on
        purpose: a client (or `loobric_server whoami`) can verify *which code* a server
        is running before, or without, logging in. A 404 here means the server
        predates this endpoint — i.e. it is an older build."""
        return build_info()
    
    # Include routers.
    # Public facade = the sectioned tool schema (docs/TOOL_SCHEMA.md): the
    # *-records entities + the instance inbox. The old flat facade (tool-records,
    # the machines tool-table, tool-sets, the record inbox) was retired in the
    # v2 cutover; clients and the web UI speak the sectioned API.
    app.include_router(auth_router)
    app.include_router(backup_router)
    app.include_router(users_router)
    app.include_router(catalogs_router)
    app.include_router(tool_instance_records_router)
    app.include_router(tool_catalog_records_router)
    app.include_router(tool_table_entry_records_router)
    app.include_router(tool_set_records_router)
    app.include_router(machine_records_router)
    app.include_router(instance_inbox_router)
    app.include_router(account_router)
    app.include_router(admin_router)
    # Legacy deep-schema routers: retiring v1 substrate, kept reachable for the
    # v2 transition but unpublished (hidden from the OpenAPI contract). Slated
    # for removal — see REBOOT.md R6.
    app.include_router(tool_items_router, include_in_schema=False)
    app.include_router(tool_assemblies_router, include_in_schema=False)
    app.include_router(tool_instances_router, include_in_schema=False)
    app.include_router(tool_presets_router, include_in_schema=False)
    app.include_router(tool_usage_router, include_in_schema=False)
    app.include_router(audit_log_router)
    app.include_router(changes_router)

    # Web inbox (loobric-server#6): one static file, no build step. Auth is
    # enforced by the API the page calls, not by the page itself.
    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/ui", StaticFiles(directory=str(static_dir), html=True), name="ui")

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url="/ui/")

    return app


app = create_app()
