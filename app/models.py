from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

JsonObject = JSON().with_variant(JSONB(), "postgresql")

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, index=True),
    Column("assigned_at", DateTime, nullable=False, server_default=func.now()),
)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(String(255))


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, lazy="selectin"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    projects: Mapped[list["Project"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["UserSession"]] = relationship(cascade="all, delete-orphan")
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        cascade="all, delete-orphan"
    )
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column()


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column()


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("owner_id", "name"),
        CheckConstraint("status IN ('draft', 'active', 'archived')"),
        CheckConstraint("roof IN ('gable', 'flat')"),
        CheckConstraint("latitude BETWEEN -90 AND 90"),
        CheckConstraint("longitude BETWEEN -180 AND 180"),
        CheckConstraint("location_zoom BETWEEN 1 AND 19"),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    location_zoom: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    roof: Mapped[str] = mapped_column(String(10), server_default="gable")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped[User] = relationship(back_populates="projects")
    terrains: Mapped[list["Terrain"]] = relationship(cascade="all, delete-orphan")
    files: Mapped[list["File"]] = relationship(cascade="all, delete-orphan")
    plans: Mapped[list["Plan"]] = relationship(cascade="all, delete-orphan")
    elevations: Mapped[list["Elevation"]] = relationship(cascade="all, delete-orphan")
    materials: Mapped[list["Material"]] = relationship(cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(cascade="all, delete-orphan")
    conversations: Mapped[list["AIConversation"]] = relationship(cascade="all, delete-orphan")
    properties: Mapped[list["Property"]] = relationship(cascade="all, delete-orphan")
    spatial_elements: Mapped[list["SpatialElement"]] = relationship(cascade="all, delete-orphan")
    walkthrough_steps: Mapped[list["WalkthroughStep"]] = relationship(cascade="all, delete-orphan")
    renovation_logs: Mapped[list["RenovationLog"]] = relationship(cascade="all, delete-orphan")
    # Kept without its project when that is deleted: the daily quota counts these rows.
    extractions: Mapped[list["AIExtraction"]] = relationship()


class AIExtraction(Base):
    """What the AI read in a document and what it changed (migration 017)."""

    __tablename__ = "ai_extractions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('review', 'applied', 'undone', 'failed')",
            name="ai_extractions_status_known",
        ),
        Index("idx_ai_extractions_project_id", "project_id"),
        Index("idx_ai_extractions_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(10), server_default="review")
    proposal: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Terrain(Base):
    __tablename__ = "terrains"
    __table_args__ = (
        CheckConstraint("area_m2 > 0"),
        CheckConstraint("width_m > 0"),
        CheckConstraint("length_m > 0"),
        CheckConstraint("slope_percent >= 0"),
        CheckConstraint("latitude BETWEEN -90 AND 90"),
        CheckConstraint("longitude BETWEEN -180 AND 180"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    area_m2: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    width_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    length_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    slope_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    soil_type: Mapped[str | None] = mapped_column(String(80))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    points: Mapped[list["TerrainPoint"]] = relationship(
        cascade="all, delete-orphan", order_by="TerrainPoint.position"
    )


class TerrainPoint(Base):
    __tablename__ = "terrain_points"
    __table_args__ = (
        UniqueConstraint("terrain_id", "position"),
        CheckConstraint("position >= 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    terrain_id: Mapped[int] = mapped_column(
        ForeignKey("terrains.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column()
    x_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    y_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))


class File(Base):
    __tablename__ = "files"
    __table_args__ = (CheckConstraint("size_bytes >= 0"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    content: Mapped["FileContent | None"] = relationship(cascade="all, delete-orphan")


class FileContent(Base):
    __tablename__ = "file_contents"

    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary)


class RuntimeState(Base):
    __tablename__ = "runtime_state"

    scope: Mapped[str] = mapped_column(String(40), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


SURFACE_CHECK = "surface IN ('concrete', 'brick', 'plaster', 'glass', 'steel', 'wood', 'stone')"
ROOM_CATEGORY_CHECK = (
    "category IN ('master_bedroom', 'bedroom', 'living_dining', 'kitchen', 'bathroom', "
    "'study', 'circulation', 'service', 'garage', 'commercial', 'other')"
)
LAYER_CHECK = "layer IN ('structure', 'installations', 'finishes')"


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (CheckConstraint(SURFACE_CHECK),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(160))
    level: Mapped[str | None] = mapped_column(String(60))
    scale: Mapped[str | None] = mapped_column(String(20))
    surface: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    rooms: Mapped[list["Room"]] = relationship(cascade="all, delete-orphan")
    components: Mapped[list["StructuralComponent"]] = relationship(cascade="all, delete-orphan")


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("width_m > 0"),
        CheckConstraint("depth_m > 0"),
        CheckConstraint("height_m > 0"),
        CheckConstraint(SURFACE_CHECK),
        CheckConstraint(ROOM_CATEGORY_CHECK),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(20), server_default="other")
    mesh_ref: Mapped[str | None] = mapped_column(String(500))
    x_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    y_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    width_m: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    depth_m: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    height_m: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    surface: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    spatial_elements: Mapped[list["SpatialElement"]] = relationship(overlaps="spatial_elements")
    walkthrough_steps: Mapped[list["WalkthroughStep"]] = relationship(overlaps="walkthrough_steps")
    renovation_logs: Mapped[list["RenovationLog"]] = relationship(overlaps="renovation_logs")


class StructuralComponent(Base):
    __tablename__ = "structural_components"
    __table_args__ = (
        CheckConstraint("kind IN ('column', 'beam', 'wall')"),
        CheckConstraint("width_m > 0"),
        CheckConstraint("depth_m > 0"),
        CheckConstraint("height_m > 0"),
        CheckConstraint(SURFACE_CHECK),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(160))
    x_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    y_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    width_m: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    depth_m: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    height_m: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    surface: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Elevation(Base):
    __tablename__ = "elevations"
    __table_args__ = (CheckConstraint("orientation IN ('north', 'south', 'east', 'west')"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(160))
    orientation: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        UniqueConstraint("project_id", "name"),
        CheckConstraint("quantity >= 0"),
        CheckConstraint("unit_cost >= 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str | None] = mapped_column(String(80))
    unit: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default="0")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'user', 'system')"),
        CheckConstraint("priority IN ('high', 'medium', 'low')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(80))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), server_default="ai")
    priority: Mapped[str] = mapped_column(String(10), server_default="medium")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    messages: Mapped[list["AIMessage"]] = relationship(
        cascade="all, delete-orphan", order_by="AIMessage.id"
    )


class AIMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system')"),
        CheckConstraint("source IN ('ai', 'rules')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("project_id", "name"),
        CheckConstraint(
            "property_type IN ('house', 'apartment_building', 'commercial', 'mixed_use')"
        ),
        CheckConstraint("status IN ('planning', 'under_construction', 'renovation', 'delivered')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    property_type: Mapped[str] = mapped_column(String(20), server_default="house")
    address: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), server_default="planning")
    spatial_metadata: Mapped[dict[str, Any]] = mapped_column(JsonObject, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    units: Mapped[list["Unit"]] = relationship(cascade="all, delete-orphan")


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint("property_id", "code"),
        CheckConstraint("status IN ('available', 'reserved', 'sold', 'under_renovation')"),
        CheckConstraint("price >= 0"),
        CheckConstraint("area_m2 > 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    floor_level: Mapped[int] = mapped_column(server_default="0")
    status: Mapped[str] = mapped_column(String(20), server_default="available")
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), server_default="USD")
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    model_asset_ref: Mapped[str | None] = mapped_column(String(500))
    asset_config: Mapped[dict[str, Any]] = mapped_column(JsonObject, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    rooms: Mapped[list[Room]] = relationship()


class SpatialElement(Base):
    __tablename__ = "spatial_elements"
    __table_args__ = (
        CheckConstraint(LAYER_CHECK),
        CheckConstraint("work_status IN ('existing', 'planned', 'demolition')"),
        CheckConstraint("max_x_m > min_x_m"),
        CheckConstraint("max_y_m > min_y_m"),
        CheckConstraint("max_z_m > min_z_m"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), index=True
    )
    layer: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    work_status: Mapped[str] = mapped_column(String(20), server_default="existing")
    min_x_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    min_y_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    min_z_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    max_x_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    max_y_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    max_z_m: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    mesh_ref: Mapped[str | None] = mapped_column(String(500))
    config: Mapped[dict[str, Any]] = mapped_column(JsonObject, default=dict)
    source: Mapped[str] = mapped_column(String(20), server_default="manual")
    external_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    renovation_logs: Mapped[list["RenovationLog"]] = relationship(overlaps="renovation_logs")


class WalkthroughStep(Base):
    __tablename__ = "walkthrough_steps"
    __table_args__ = (
        CheckConstraint("position >= 0"),
        CheckConstraint("duration_ms BETWEEN 1000 AND 60000"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), index=True
    )
    position: Mapped[int] = mapped_column()
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(server_default="5000")
    view_config: Mapped[dict[str, Any]] = mapped_column(JsonObject, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RenovationLog(Base):
    __tablename__ = "renovation_logs"
    __table_args__ = (
        CheckConstraint(LAYER_CHECK),
        CheckConstraint("status IN ('planned', 'in_progress', 'completed', 'cancelled')"),
        CheckConstraint("estimated_cost >= 0"),
        CheckConstraint("planned_end >= planned_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), index=True
    )
    spatial_element_id: Mapped[int | None] = mapped_column(
        ForeignKey("spatial_elements.id", ondelete="SET NULL"), index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    layer: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="planned")
    planned_start: Mapped[date | None] = mapped_column()
    planned_end: Mapped[date | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
