from __future__ import annotations

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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
