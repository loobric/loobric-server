# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Database schema for Loobric using SQLAlchemy.

Defines all entity models with versioning and user attribution.

Assumptions:
- All entities have id (UUID), created_at, updated_at, version, user_id
- Version starts at 1 and increments on update
- JSON fields store nested data structures
- Foreign keys maintain referential integrity
"""
from datetime import datetime, UTC
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean, DateTime, Float, Integer, String, Text, JSON, ForeignKey,
    UniqueConstraint, create_engine
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class TimestampMixin:
    """Mixin for timestamp fields.
    
    Assumptions:
    - created_at is set on insert
    - updated_at is updated on every change
    """
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False)


class VersionMixin:
    """Mixin for versioning.
    
    Assumptions:
    - version starts at 1
    - version must be incremented manually or via trigger
    """
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class UserAttributionMixin:
    """Mixin for user attribution.
    
    Assumptions:
    - user_id identifies the owner of the data (for multi-tenancy)
    - created_by identifies who created the record
    - updated_by identifies who last updated the record
    """
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(36), nullable=False)


class User(Base, TimestampMixin, VersionMixin):
    """User account model for authentication.
    
    Assumptions:
    - Email is unique
    - Password is hashed (never plaintext)
    - Users own their tool data (multi-tenant)
    - role: "user" (default), "manufacturer", "admin"
    - manufacturer_profile: JSON field for manufacturer company info
    - is_verified: Partnership verification for manufacturers
    """
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="user", nullable=False, index=True)
    manufacturer_profile: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Relationships
    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="user")


class ApiKey(Base, TimestampMixin, VersionMixin):
    """API key model for application authentication.
    
    Assumptions:
    - API key belongs to a user account
    - Scopes define permissions (JSON array)
    - Tags allow for flexible access control grouping
    - expires_at is optional expiration timestamp
    """
    __tablename__ = "api_keys"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="api_keys")


class PasswordResetToken(Base):
    """Password reset token model.
    
    Assumptions:
    - Tokens are single-use
    - Tokens expire after 1 hour
    - Token is hashed in database
    - Deleted after use or expiration
    """
    __tablename__ = "password_reset_tokens"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    
    # Relationships
    user: Mapped["User"] = relationship("User")


class ToolItem(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Tool item model - catalog items (cutting tools and holders).
    
    Assumptions:
    - type: cutting_tool, holder, insert, adapter
    - geometry and material are JSON fields for nested data
    - shape_data stores tool shape file references (native CAD, STEP, STL, etc.)
    - iso_13399_reference is optional for standards compliance
    - parent_tool_id: References another ToolItem if copied from catalog (nullable)
    - tags is JSON array for access control and organization
    - Indexes on version and updated_at for change detection queries
    """
    __tablename__ = "tool_items"
    __table_args__ = (
        {'extend_existing': True}
    )
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    product_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    geometry: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    material: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    capabilities: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    shape_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    iso_13399_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    parent_tool_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tool_items.id"), nullable=True, index=True)
    # Opaque client passthrough for the v2 facade (lossless round trips);
    # a client may stash its full native tool document here, namespaced.
    extra: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class ManufacturerCatalog(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Manufacturer catalog model - collections of catalog tools.
    
    Assumptions:
    - user_id is manufacturer owner (role="manufacturer")
    - tool_ids is JSON array of ToolItem IDs in this catalog
    - tags is JSON array for searchability (e.g., ["lathe", "aluminum"])
    - Same tool can exist in multiple catalogs
    - is_published: only published catalogs visible to public
    - catalog_year is optional (e.g., 2024)
    """
    __tablename__ = "manufacturer_catalogs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    catalog_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tool_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


class ToolAssembly(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Tool assembly model - combinations of tool items.
    
    Assumptions:
    - components is JSON array of {item_id, role, position, gauge_offset}
    - computed_geometry is JSON object calculated from components
    - tags is JSON array for access control and organization
    - Indexes on version and updated_at for change detection queries
    """
    __tablename__ = "tool_assemblies"
    __table_args__ = (
        {'extend_existing': True}
    )
    
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default='[]')
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    components: Mapped[list] = mapped_column(JSON, nullable=False)
    computed_geometry: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class ToolInstance(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Tool instance model - specific physical tools.
    
    Assumptions:
    - assembly_id references ToolAssembly
    - status: available, in_use, needs_inspection, retired
    - Indexes on version and updated_at for change detection queries
    - location, measured_geometry, lifecycle are JSON fields
    - tags is JSON array for access control and organization
    """
    __tablename__ = "tool_instances"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    assembly_id: Mapped[str] = mapped_column(String(36), ForeignKey("tool_assemblies.id"), nullable=False, index=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="available")
    location: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    measured_geometry: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    lifecycle: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default='[]')
    
    # Relationships
    assembly: Mapped["ToolAssembly"] = relationship("ToolAssembly")


class ToolPreset(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Tool preset model - machine-specific setup data.
    
    Assumptions:
    - instance_id references ToolInstance
    - machine_id identifies the CNC machine
    - tool_number is the T-code
    - offsets, orientation, limits are JSON fields
    - tags is JSON array for access control and organization
    """
    __tablename__ = "tool_presets"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    machine_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tool_number: Mapped[int] = mapped_column(Integer, nullable=False)
    instance_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tool_instances.id"), nullable=True, index=True)
    pocket: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preset_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    offsets: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    orientation: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    limits: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    loaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    loaded_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default='[]')
    
    # Relationships
    instance: Mapped["ToolInstance"] = relationship("ToolInstance")


class ToolUsage(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Tool usage model - runtime tracking and wear monitoring.
    
    Assumptions:
    - preset_id references ToolPreset
    - job_id identifies the NC program or work order
    - wear_progression and events are JSON arrays
    """
    __tablename__ = "tool_usage"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    preset_id: Mapped[str] = mapped_column(String(36), ForeignKey("tool_presets.id"), nullable=False, index=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cycle_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cut_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wear_progression: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    events: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    
    # Relationships
    preset: Mapped["ToolPreset"] = relationship("ToolPreset")


class ToolInstanceRecord(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Sectioned tool-schema entity (docs/TOOL_SCHEMA.md): a physical tool.

    `internal` is derived from the id/version/timestamp columns; `canonical`
    (provenance-tagged truth) and `clients` (per-client envelope + opaque data)
    are stored as JSON. `catalog_type_id` is extracted from canonical for FK-ish
    queries. The sectioned facade lives in loobric_server/api/tool_instance_records.py
    and is validated against loobric_server/contract on the way in and out.
    """
    __tablename__ = "tool_instance_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    canonical: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    clients: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    catalog_type_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)


class ToolCatalogRecord(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Sectioned tool-schema entity: a catalog TYPE (docs/TOOL_SCHEMA.md). May
    exist with zero instances. Nominal, asserted geometry.

    `manufacturer_norm`/`product_code_norm` are server-maintained, extracted from
    canonical (trim + casefold) — they exist only to back the natural-key unique
    index. Like the entry's install-once `bound_instance_id` column, they are the
    race-safe enforcement point, not a check-then-insert. The original display
    values stay untouched in canonical; the client never sets these columns.
    Scope is per-account: the key carries `user_id`, so two accounts may each
    hold the same `(manufacturer, product_code)` (M2, issue #25)."""
    __tablename__ = "tool_catalog_records"
    __table_args__ = (
        UniqueConstraint("user_id", "manufacturer_norm", "product_code_norm",
                         name="uq_catalog_record_natural_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    canonical: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    clients: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Extracted, normalized natural key (server-maintained on every canonical
    # write); the unique index above is per-account.
    manufacturer_norm: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    product_code_norm: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class ToolTableEntryRecord(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Sectioned tool-schema entity: a machine entry. `bound_instance_id` is
    extracted from canonical with a UNIQUE index — the install-once guarantee
    (a physical instance is in at most one entry, globally; NULLs are exempt so
    unbound entries are unconstrained)."""
    __tablename__ = "tool_table_entry_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    machine_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    bound_instance_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, unique=True, index=True)
    canonical: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    clients: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ToolSetRecord(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Sectioned tool-schema entity: an agnostic named collection. Optional
    `machine_id` link (extracted) — when set, member numbers are reconciled
    from that machine's entries (machine wins)."""
    __tablename__ = "tool_set_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    machine_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    canonical: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    clients: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class MachineRecord(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Sectioned tool-schema entity: a controller (name, controller_type,
    definition — mostly asserted)."""
    __tablename__ = "machine_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    canonical: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    clients: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class EntryProposal(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """A heuristic proposal that an unbound entry holds a particular instance,
    awaiting human review (the binding inbox for the sectioned schema). status:
    open | confirmed | rejected; a rejected (entry, instance) pair is never
    re-proposed."""
    __tablename__ = "entry_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entry_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    proposed_instance_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True, nullable=False)


class ToolSet(Base, TimestampMixin, VersionMixin, UserAttributionMixin):
    """Tool set model - collections of tools used as a group.
    
    Assumptions:
    - type: machine_setup, job_specific, template, project
    - members is JSON array of tool references
    - status: draft, active, archived
    - tags is JSON array for access control and organization
    """
    __tablename__ = "tool_sets"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    machine_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    members: Mapped[list] = mapped_column(JSON, nullable=False)
    capacity: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Opaque client passthrough for the v2 ToolSet facade (lossless round trips)
    extra: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    activation: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default='[]')


class ToolSetHistory(Base):
    """Tool set history model - snapshots of ToolSet at each version.
    
    Assumptions:
    - Immutable: records never modified or deleted
    - One record per version change
    - snapshot contains full ToolSet state at that version
    - Used for rollback and version comparison
    """
    __tablename__ = "tool_set_history"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tool_set_id: Mapped[str] = mapped_column(String(36), ForeignKey("tool_sets.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    changed_by: Mapped[str] = mapped_column(String(36), nullable=False)
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    """Audit log model - immutable record of all data changes.
    
    Assumptions:
    - Immutable: records never modified or deleted
    - Tracks all CRUD operations with user context
    - Retention: 7 years for compliance
    - Fields: user_id, timestamp, operation, entity_type, entity_id, result
    - changes stores before/after values as JSON
    """
    __tablename__ = "audit_logs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC), index=True)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)  # CREATE, UPDATE, DELETE
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    changes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result: Mapped[str] = mapped_column(String(20), nullable=False)  # success, error
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


def init_db(engine=None):
    """Initialize database by creating all tables.
    
    Args:
        engine: SQLAlchemy engine (optional, creates default if not provided)
        
    Assumptions:
    - Creates all tables defined in Base.metadata
    - Safe to call multiple times (no-op if tables exist)
    """
    if engine is None:
        from loobric_server.config import settings
        engine = create_engine(settings.database_url)
    
    Base.metadata.create_all(engine)
    return engine
