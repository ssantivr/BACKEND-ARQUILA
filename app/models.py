from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
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
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

JsonObject = JSON().with_variant(JSONB(), "postgresql")
# SQLite only numbers a primary key by itself when it is a plain INTEGER.
BigIdentifier = BigInteger().with_variant(Integer(), "sqlite")


def same_project(
    columns: list[str], target: str, name: str, ondelete: str, **options: Any
) -> ForeignKeyConstraint:
    """A reference to a row of the same project, as migration 027 declares it.

    The first column points at `target.id`; the last one, the project, at `target.project_id`.
    """
    return ForeignKeyConstraint(
        columns, [f"{target}.id", f"{target}.project_id"], name=name, ondelete=ondelete, **options
    )


@compiles(ForeignKeyConstraint, "sqlite")
def _foreign_key_for_sqlite(constraint: ForeignKeyConstraint, compiler: Any, **kw: Any) -> str:
    # SQLite has no ON DELETE SET NULL (column). The single-column key on the same column already
    # empties it, and a composite key with an empty column is not checked: the result is the same.
    if not (constraint.ondelete or "").upper().startswith("SET NULL ("):
        return compiler.visit_foreign_key_constraint(constraint, **kw)

    ondelete, constraint.ondelete = constraint.ondelete, None

    try:
        return compiler.visit_foreign_key_constraint(constraint, **kw)
    finally:
        constraint.ondelete = ondelete


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
    display_name: Mapped[str | None] = mapped_column(String(120))
    avatar_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL", use_alter=True)
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    projects: Mapped[list["Project"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["UserSession"]] = relationship(cascade="all, delete-orphan")
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        cascade="all, delete-orphan"
    )
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")
    notifications: Mapped[list["Notification"]] = relationship(cascade="all, delete-orphan")
    preferences: Mapped["UserPreferences | None"] = relationship(cascade="all, delete-orphan")


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
        CheckConstraint("progress BETWEEN 0 AND 100"),
        CheckConstraint(
            "project_type IN ('house', 'apartment_building', 'commercial', 'mixed_use')"
        ),
        CheckConstraint("stage IN ('draft', 'in_progress', 'completed', 'archived')"),
        # Projects and files point at each other, so this key is added once both tables exist.
        ForeignKeyConstraint(
            ["cover_file_id", "id"],
            ["files.id", "files.project_id"],
            name="fk_projects_cover_same_project",
            ondelete="SET NULL (cover_file_id)",
            use_alter=True,
        ),
    )

    # Explicit, because id is also a column of the cover's foreign key, and SQLAlchemy does not
    # number a column that is part of one by itself.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    roof: Mapped[str] = mapped_column(String(10), server_default="gable")
    progress: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    project_type: Mapped[str | None] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(20), server_default="draft")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cover_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL", use_alter=True)
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped[User] = relationship(back_populates="projects")
    terrains: Mapped[list["Terrain"]] = relationship(cascade="all, delete-orphan")
    files: Mapped[list["File"]] = relationship(
        cascade="all, delete-orphan", foreign_keys="File.project_id"
    )
    plans: Mapped[list["Plan"]] = relationship(cascade="all, delete-orphan")
    elevations: Mapped[list["Elevation"]] = relationship(cascade="all, delete-orphan")
    materials: Mapped[list["Material"]] = relationship(cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(cascade="all, delete-orphan")
    conversations: Mapped[list["AIConversation"]] = relationship(cascade="all, delete-orphan")
    properties: Mapped[list["Property"]] = relationship(cascade="all, delete-orphan")
    spatial_elements: Mapped[list["SpatialElement"]] = relationship(cascade="all, delete-orphan")
    walkthrough_steps: Mapped[list["WalkthroughStep"]] = relationship(cascade="all, delete-orphan")
    renovation_logs: Mapped[list["RenovationLog"]] = relationship(cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship(cascade="all, delete-orphan")
    versions: Mapped[list["ProjectVersion"]] = relationship(cascade="all, delete-orphan")
    activity: Mapped[list["ActivityEntry"]] = relationship(cascade="all, delete-orphan")
    scene_settings: Mapped["SceneSettings | None"] = relationship(cascade="all, delete-orphan")
    walkthrough_points: Mapped[list["WalkthroughPoint"]] = relationship(
        cascade="all, delete-orphan"
    )


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
    __table_args__ = (
        CheckConstraint("size_bytes >= 0"),
        UniqueConstraint("id", "project_id", name="uq_files_id_project"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Empty for a profile picture, which belongs to the user in uploaded_by.
    project_id: Mapped[int | None] = mapped_column(
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
    __table_args__ = (
        CheckConstraint(SURFACE_CHECK),
        UniqueConstraint("id", "project_id", name="uq_plans_id_project"),
        same_project(
            ["file_id", "project_id"],
            "files",
            "fk_plans_file_same_project",
            "SET NULL (file_id)",
        ),
    )

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

    # foreign_keys: the keys of the same project also join on project_id, which a plan must not
    # copy onto its rooms and components.
    rooms: Mapped[list["Room"]] = relationship(
        cascade="all, delete-orphan", foreign_keys="Room.plan_id"
    )
    components: Mapped[list["StructuralComponent"]] = relationship(
        cascade="all, delete-orphan", foreign_keys="StructuralComponent.plan_id"
    )


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("width_m > 0"),
        CheckConstraint("depth_m > 0"),
        CheckConstraint("height_m > 0"),
        CheckConstraint(SURFACE_CHECK),
        CheckConstraint(ROOM_CATEGORY_CHECK),
        UniqueConstraint("id", "project_id", name="uq_rooms_id_project"),
        same_project(["plan_id", "project_id"], "plans", "fk_rooms_plan_same_project", "CASCADE"),
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

    spatial_elements: Mapped[list["SpatialElement"]] = relationship(
        overlaps="spatial_elements", foreign_keys="SpatialElement.room_id"
    )
    walkthrough_steps: Mapped[list["WalkthroughStep"]] = relationship(
        overlaps="walkthrough_steps", foreign_keys="WalkthroughStep.room_id"
    )
    renovation_logs: Mapped[list["RenovationLog"]] = relationship(
        overlaps="renovation_logs", foreign_keys="RenovationLog.room_id"
    )


class StructuralComponent(Base):
    __tablename__ = "structural_components"
    __table_args__ = (
        CheckConstraint("kind IN ('column', 'beam', 'wall')"),
        CheckConstraint("width_m > 0"),
        CheckConstraint("depth_m > 0"),
        CheckConstraint("height_m > 0"),
        CheckConstraint(SURFACE_CHECK),
        same_project(
            ["plan_id", "project_id"],
            "plans",
            "fk_structural_components_plan_same_project",
            "CASCADE",
        ),
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
    __table_args__ = (
        CheckConstraint("orientation IN ('north', 'south', 'east', 'west')"),
        same_project(
            ["file_id", "project_id"],
            "files",
            "fk_elevations_file_same_project",
            "SET NULL (file_id)",
        ),
    )

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
        UniqueConstraint("id", "project_id", name="uq_spatial_elements_id_project"),
        same_project(
            ["room_id", "project_id"],
            "rooms",
            "fk_spatial_elements_room_same_project",
            "SET NULL (room_id)",
        ),
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

    renovation_logs: Mapped[list["RenovationLog"]] = relationship(
        overlaps="renovation_logs", foreign_keys="RenovationLog.spatial_element_id"
    )


class WalkthroughStep(Base):
    __tablename__ = "walkthrough_steps"
    __table_args__ = (
        CheckConstraint("position >= 0"),
        CheckConstraint("duration_ms BETWEEN 1000 AND 60000"),
        same_project(
            ["room_id", "project_id"],
            "rooms",
            "fk_walkthrough_steps_room_same_project",
            "SET NULL (room_id)",
        ),
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
        same_project(
            ["room_id", "project_id"],
            "rooms",
            "fk_renovation_logs_room_same_project",
            "SET NULL (room_id)",
        ),
        same_project(
            ["spatial_element_id", "project_id"],
            "spatial_elements",
            "fk_renovation_logs_spatial_element_same_project",
            "SET NULL (spatial_element_id)",
        ),
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


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('todo', 'in_progress', 'done')"),
        CheckConstraint("progress BETWEEN 0 AND 100"),
        CheckConstraint("status <> 'done' OR progress = 100"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="todo")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_date: Mapped[date | None] = mapped_column()
    progress: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ProjectVersion(Base):
    __tablename__ = "project_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_number"),
        CheckConstraint("version_number > 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column()
    label: Mapped[str | None] = mapped_column(String(160))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JsonObject, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ActivityEntry(Base):
    __tablename__ = "activity_log"
    __table_args__ = (CheckConstraint("entity_id IS NULL OR entity_type IS NOT NULL"),)

    id: Mapped[int] = mapped_column(BigIdentifier, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column()
    detail: Mapped[dict[str, Any]] = mapped_column(JsonObject, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint("theme IN ('light', 'dark', 'auto')"),
        CheckConstraint("units IN ('metric', 'imperial')"),
        CheckConstraint("density IN ('compact', 'comfortable', 'spacious')"),
        CheckConstraint("preview_quality IN ('low', 'medium', 'high')"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(String(10), default="auto")
    units: Mapped[str] = mapped_column(String(10), default="metric")
    density: Mapped[str] = mapped_column(String(20), default="comfortable")
    reduce_motion: Mapped[bool] = mapped_column(Boolean, default=False)
    camera_defaults: Mapped[dict[str, Any]] = mapped_column(JsonObject, default=dict)
    preview_quality: Mapped[str] = mapped_column(String(10), default="medium")
    notifications: Mapped[dict[str, Any]] = mapped_column(JsonObject, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class SceneSettings(Base):
    __tablename__ = "scene_settings"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    lighting: Mapped[dict[str, Any]] = mapped_column(JsonObject, default=dict)
    camera_presets: Mapped[list[Any]] = mapped_column(JsonObject, default=list)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class WalkthroughPoint(Base):
    __tablename__ = "walkthrough_points"
    __table_args__ = (CheckConstraint("sort_order >= 0"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    position: Mapped[list[float]] = mapped_column(JsonObject)
    target: Mapped[list[float]] = mapped_column(JsonObject)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
