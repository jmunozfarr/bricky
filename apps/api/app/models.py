from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Part(Base):
    __tablename__ = "parts"
    __table_args__ = (
        Index("ix_parts_name", "name"),
        Index("ix_parts_category_visible", "category", "is_subpart"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(512))
    relative_path: Mapped[str] = mapped_column(String(512), unique=True)
    author: Mapped[str | None] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(128), index=True)
    org_classification: Mapped[str | None] = mapped_column(String(256))
    license: Mapped[str | None] = mapped_column(String(512))
    keywords: Mapped[str | None] = mapped_column(Text)
    is_subpart: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_shortcut: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LDrawColor(Base):
    __tablename__ = "ldraw_colors"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    value_hex: Mapped[str] = mapped_column(String(7))
    edge_hex: Mapped[str | None] = mapped_column(String(7))
    alpha: Mapped[int] = mapped_column(Integer, default=255)
    luminance: Mapped[int | None] = mapped_column(Integer)
    finish: Mapped[str | None] = mapped_column(String(64))


class LDrawPrimitive(Base):
    """Rebuildable index of p/ primitive filenames, relative to p/ and lowercase."""

    __tablename__ = "ldraw_primitives"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)


class CatalogIndexState(Base):
    __tablename__ = "catalog_index_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    library_fingerprint: Mapped[str] = mapped_column(String(64))
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    part_count: Mapped[int] = mapped_column(Integer)
    color_count: Mapped[int] = mapped_column(Integer)
    indexer_version: Mapped[str] = mapped_column(String(32))


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "part_id",
            "color_code",
            name="uq_inventory_workspace_part_color",
        ),
        CheckConstraint("quantity > 0", name="ck_inventory_quantity_positive"),
        Index("ix_inventory_workspace_part", "workspace_id", "part_id"),
        Index("ix_inventory_workspace_color", "workspace_id", "color_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    part_id: Mapped[str] = mapped_column(String(64), index=True)
    color_code: Mapped[int] = mapped_column(Integer, index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ImportedModel(Base):
    __tablename__ = "imported_models"
    __table_args__ = (
        UniqueConstraint("workspace_id", "source_sha256", name="uq_models_workspace_source_sha256"),
        Index("ix_models_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), default=uuid.uuid4, unique=True, index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(256))
    original_filename: Mapped[str] = mapped_column(String(255))
    safe_filename: Mapped[str] = mapped_column(String(255))
    source_format: Mapped[str] = mapped_column(String(8))
    relative_storage_path: Mapped[str] = mapped_column(String(512))
    source_sha256: Mapped[str] = mapped_column(String(64))
    import_status: Mapped[str] = mapped_column(String(32), index=True)
    declared_step_count: Mapped[int] = mapped_column(Integer)
    total_part_quantity: Mapped[int] = mapped_column(Integer)
    unique_part_color_count: Mapped[int] = mapped_column(Integer)
    unresolved_reference_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModelBomItem(Base):
    __tablename__ = "model_bom_items"
    __table_args__ = (
        UniqueConstraint("model_id", "part_id", "color_code", name="uq_model_bom_part_color"),
        CheckConstraint("quantity > 0", name="ck_model_bom_quantity_positive"),
        Index("ix_model_bom_model_part", "model_id", "part_id"),
        Index("ix_model_bom_model_color", "model_id", "color_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(
        ForeignKey("imported_models.id", ondelete="CASCADE"), index=True
    )
    part_id: Mapped[str] = mapped_column(String(64), index=True)
    color_code: Mapped[int] = mapped_column(Integer, index=True)
    quantity: Mapped[int] = mapped_column(Integer)


class ModelImportIssue(Base):
    __tablename__ = "model_import_issues"
    __table_args__ = (Index("ix_model_issues_model_severity", "model_id", "severity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(
        ForeignKey("imported_models.id", ondelete="CASCADE"), index=True
    )
    severity: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(512))
    referenced_filename: Mapped[str | None] = mapped_column(String(255))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
