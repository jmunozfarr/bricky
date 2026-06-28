from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models import LDrawColor, Part
from app.services.ldraw_catalog import get_catalog_status


class CatalogStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    library_installed: bool = Field(alias="libraryInstalled")
    indexed: bool
    stale: bool
    part_count: int = Field(alias="partCount")
    color_count: int = Field(alias="colorCount")
    indexed_at: datetime | None = Field(alias="indexedAt")


class PartCardResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    part_id: str = Field(alias="partId")
    name: str
    category: str
    author: str | None
    render_asset_url: str = Field(alias="renderAssetUrl")


class PartDetailResponse(PartCardResponse):
    org_classification: str | None = Field(alias="orgClassification")
    license: str | None
    keywords: list[str]
    is_shortcut: bool = Field(alias="isShortcut")


class PartsPageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[PartCardResponse]
    page: int
    page_size: int = Field(alias="pageSize")
    total_items: int = Field(alias="totalItems")
    total_pages: int = Field(alias="totalPages")


class CategoryResponse(BaseModel):
    name: str
    count: int


class ColorResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: int
    name: str
    value_hex: str = Field(alias="valueHex")
    edge_hex: str | None = Field(alias="edgeHex")
    alpha: int
    luminance: int | None
    finish: str | None


SessionDependency = Callable[[], Iterator[Session]]


def _render_asset_url(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or len(path.parts) != 2
        or path.parts[0] != "parts"
        or path.suffix.lower() != ".dat"
    ):
        raise ValueError("Indexed part path is not a safe catalog asset")
    return f"/api/ldraw/{quote(path.as_posix(), safe='/')}"


def _card(part: Part) -> PartCardResponse:
    try:
        asset_url = _render_asset_url(part.relative_path)
    except ValueError as error:
        raise HTTPException(status_code=500, detail="Indexed part has an invalid path") from error
    return PartCardResponse(
        part_id=part.part_id,
        name=part.name,
        category=part.category,
        author=part.author,
        render_asset_url=asset_url,
    )


def _escaped_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def create_catalog_router(
    library_root: Path, session_dependency: SessionDependency
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/catalog/status", response_model=CatalogStatusResponse)
    def catalog_status(session: Session = Depends(session_dependency)) -> CatalogStatusResponse:
        status = get_catalog_status(session, library_root)
        return CatalogStatusResponse(
            library_installed=status.library_installed,
            indexed=status.indexed,
            stale=status.stale,
            part_count=status.part_count,
            color_count=status.color_count,
            indexed_at=status.indexed_at,
        )

    @router.get("/parts", response_model=PartsPageResponse)
    def parts_search(
        query: str = Query(default="", max_length=200),
        category: str | None = Query(default=None, max_length=128),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=24, alias="pageSize", ge=1, le=100),
        session: Session = Depends(session_dependency),
    ) -> PartsPageResponse:
        filters = [Part.is_subpart.is_(False)]
        normalized_query = query.strip()
        if normalized_query:
            pattern = _escaped_pattern(normalized_query)
            filters.append(
                or_(
                    Part.part_id.ilike(pattern, escape="\\"),
                    Part.name.ilike(pattern, escape="\\"),
                )
            )
        if category:
            filters.append(func.lower(Part.category) == category.strip().lower())

        total_items = session.scalar(
            select(func.count()).select_from(Part).where(*filters)
        ) or 0
        ordering: list[object] = []
        if normalized_query:
            ordering.append(
                case(
                    (func.lower(Part.part_id) == normalized_query.lower(), 0),
                    else_=1,
                )
            )
        ordering.extend((func.lower(Part.name), Part.part_id))
        rows = session.scalars(
            select(Part)
            .where(*filters)
            .order_by(*ordering)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return PartsPageResponse(
            items=[_card(part) for part in rows],
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=math.ceil(total_items / page_size) if total_items else 0,
        )

    @router.get("/parts/categories", response_model=list[CategoryResponse])
    def categories(session: Session = Depends(session_dependency)) -> list[CategoryResponse]:
        rows = session.execute(
            select(Part.category, func.count(Part.id))
            .where(Part.is_subpart.is_(False))
            .group_by(Part.category)
            .order_by(func.lower(Part.category), Part.category)
        ).all()
        return [CategoryResponse(name=name, count=count) for name, count in rows]

    @router.get("/parts/{part_id}", response_model=PartDetailResponse)
    def part_detail(
        part_id: str, session: Session = Depends(session_dependency)
    ) -> PartDetailResponse:
        normalized_id = part_id.strip().lower()
        part = session.scalar(
            select(Part).where(
                func.lower(Part.part_id) == normalized_id,
                Part.is_subpart.is_(False),
            )
        )
        if part is None:
            raise HTTPException(status_code=404, detail="Part not found")
        card = _card(part)
        return PartDetailResponse(
            **card.model_dump(),
            org_classification=part.org_classification,
            license=part.license,
            keywords=[item.strip() for item in (part.keywords or "").split(",") if item.strip()],
            is_shortcut=part.is_shortcut,
        )

    @router.get("/colors", response_model=list[ColorResponse])
    def colors(session: Session = Depends(session_dependency)) -> list[ColorResponse]:
        rows = session.scalars(select(LDrawColor).order_by(LDrawColor.code)).all()
        return [
            ColorResponse(
                code=color.code,
                name=color.name,
                value_hex=color.value_hex,
                edge_hex=color.edge_hex,
                alpha=color.alpha,
                luminance=color.luminance,
                finish=color.finish,
            )
            for color in rows
        ]

    return router
