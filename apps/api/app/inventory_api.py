from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from typing_extensions import Annotated

from app.catalog_api import render_asset_url
from app.models import InventoryItem, LDrawColor, Part
from app.services.local_workspace import resolve_local_workspace


class InventorySummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_quantity: int = Field(alias="totalQuantity")
    unique_items: int = Field(alias="uniqueItems")
    unique_parts: int = Field(alias="uniqueParts")


class InventoryItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    part_id: str = Field(alias="partId")
    part_name: str = Field(alias="partName")
    category: str
    color_code: int = Field(alias="colorCode")
    color_name: str = Field(alias="colorName")
    color_hex: str = Field(alias="colorHex")
    alpha: int
    quantity: int
    render_asset_url: str | None = Field(alias="renderAssetUrl")
    updated_at: datetime = Field(alias="updatedAt")
    catalog_available: bool = Field(alias="catalogAvailable")


class InventoryPageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[InventoryItemResponse]
    page: int
    page_size: int = Field(alias="pageSize")
    total_items: int = Field(alias="totalItems")
    total_pages: int = Field(alias="totalPages")


Quantity = Annotated[StrictInt, Field(ge=1, le=999_999)]


class InventoryQuantityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: Quantity


SessionDependency = Callable[[], Iterator[Session]]


def _escaped_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _response(
    item: InventoryItem, part: Part | None, color: LDrawColor | None
) -> InventoryItemResponse:
    available = part is not None and not part.is_subpart
    asset_url: str | None = None
    if available and part is not None:
        try:
            asset_url = render_asset_url(part.relative_path)
        except ValueError:
            available = False
    return InventoryItemResponse(
        part_id=item.part_id,
        part_name=part.name if part is not None else item.part_id,
        category=part.category if part is not None else "Unavailable",
        color_code=item.color_code,
        color_name=color.name if color is not None else f"Color {item.color_code}",
        color_hex=color.value_hex if color is not None else "#808080",
        alpha=color.alpha if color is not None else 255,
        quantity=item.quantity,
        render_asset_url=asset_url,
        updated_at=item.updated_at,
        catalog_available=available,
    )


def _item_query(workspace_id: int):
    return (
        select(InventoryItem, Part, LDrawColor)
        .outerjoin(Part, func.lower(Part.part_id) == func.lower(InventoryItem.part_id))
        .outerjoin(LDrawColor, LDrawColor.code == InventoryItem.color_code)
        .where(InventoryItem.workspace_id == workspace_id)
    )


def create_inventory_router(session_dependency: SessionDependency) -> APIRouter:
    router = APIRouter(prefix="/api/inventory")

    @router.get("/summary", response_model=InventorySummaryResponse)
    def summary(session: Session = Depends(session_dependency)) -> InventorySummaryResponse:
        workspace = resolve_local_workspace(session)
        total_quantity, unique_items, unique_parts = session.execute(
            select(
                func.coalesce(func.sum(InventoryItem.quantity), 0),
                func.count(InventoryItem.id),
                func.count(func.distinct(InventoryItem.part_id)),
            ).where(InventoryItem.workspace_id == workspace.id)
        ).one()
        session.commit()
        return InventorySummaryResponse(
            total_quantity=total_quantity,
            unique_items=unique_items,
            unique_parts=unique_parts,
        )

    @router.get("/items", response_model=InventoryPageResponse)
    def items(
        query: str = Query(default="", max_length=200),
        category: str | None = Query(default=None, max_length=128),
        color_code: int | None = Query(default=None, alias="colorCode", ge=0),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=24, alias="pageSize", ge=1, le=100),
        session: Session = Depends(session_dependency),
    ) -> InventoryPageResponse:
        workspace = resolve_local_workspace(session)
        filters = [InventoryItem.workspace_id == workspace.id]
        normalized_query = query.strip()
        if normalized_query:
            pattern = _escaped_pattern(normalized_query)
            filters.append(
                or_(
                    InventoryItem.part_id.ilike(pattern, escape="\\"),
                    Part.name.ilike(pattern, escape="\\"),
                )
            )
        if category:
            filters.append(func.lower(Part.category) == category.strip().lower())
        if color_code is not None:
            filters.append(InventoryItem.color_code == color_code)

        total_items = session.scalar(
            select(func.count())
            .select_from(InventoryItem)
            .outerjoin(Part, func.lower(Part.part_id) == func.lower(InventoryItem.part_id))
            .where(*filters)
        ) or 0
        ordering: list[object] = []
        if normalized_query:
            ordering.append(
                case(
                    (func.lower(InventoryItem.part_id) == normalized_query.lower(), 0),
                    else_=1,
                )
            )
        ordering.extend(
            (func.lower(func.coalesce(Part.name, InventoryItem.part_id)), InventoryItem.part_id, InventoryItem.color_code)
        )
        rows = session.execute(
            _item_query(workspace.id)
            .where(*filters)
            .order_by(*ordering)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        session.commit()
        return InventoryPageResponse(
            items=[_response(item, part, color) for item, part, color in rows],
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=math.ceil(total_items / page_size) if total_items else 0,
        )

    @router.get("/items/{part_id}", response_model=list[InventoryItemResponse])
    def variants(
        part_id: str, session: Session = Depends(session_dependency)
    ) -> list[InventoryItemResponse]:
        workspace = resolve_local_workspace(session)
        rows = session.execute(
            _item_query(workspace.id)
            .where(func.lower(InventoryItem.part_id) == part_id.strip().lower())
            .order_by(InventoryItem.color_code)
        ).all()
        session.commit()
        return [_response(item, part, color) for item, part, color in rows]

    @router.put(
        "/items/{part_id}/{color_code}", response_model=InventoryItemResponse
    )
    def set_quantity(
        payload: InventoryQuantityRequest,
        part_id: str,
        color_code: int = Path(ge=0),
        session: Session = Depends(session_dependency),
    ) -> InventoryItemResponse:
        part = session.scalar(
            select(Part).where(
                func.lower(Part.part_id) == part_id.strip().lower(),
                Part.is_subpart.is_(False),
            )
        )
        if part is None:
            raise HTTPException(status_code=404, detail="Catalog part not found")
        color = session.scalar(select(LDrawColor).where(LDrawColor.code == color_code))
        if color is None:
            raise HTTPException(status_code=404, detail="LDraw color not found")
        workspace = resolve_local_workspace(session)
        session.execute(
            insert(InventoryItem)
            .values(
                workspace_id=workspace.id,
                part_id=part.part_id,
                color_code=color.code,
                quantity=payload.quantity,
            )
            .on_conflict_do_update(
                index_elements=[
                    InventoryItem.workspace_id,
                    InventoryItem.part_id,
                    InventoryItem.color_code,
                ],
                set_={"quantity": payload.quantity, "updated_at": func.now()},
            )
        )
        session.commit()
        row = session.execute(
            _item_query(workspace.id).where(
                InventoryItem.part_id == part.part_id,
                InventoryItem.color_code == color.code,
            )
        ).one()
        return _response(*row)

    @router.delete(
        "/items/{part_id}/{color_code}", status_code=status.HTTP_204_NO_CONTENT
    )
    def delete_item(
        part_id: str,
        color_code: int = Path(ge=0),
        session: Session = Depends(session_dependency),
    ) -> Response:
        workspace = resolve_local_workspace(session)
        session.execute(
            delete(InventoryItem).where(
                InventoryItem.workspace_id == workspace.id,
                func.lower(InventoryItem.part_id) == part_id.strip().lower(),
                InventoryItem.color_code == color_code,
            )
        )
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
