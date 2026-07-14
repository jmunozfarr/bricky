from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path as FilesystemPath
from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import Select, SQLColumnExpression, case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog_api import render_asset_url
from app.models import InventoryItem, LDrawColor, Part
from app.schemas.inventory import (
    ImportBucketSummaryResponse,
    ImportPreviewRowResponse,
    ImportRowIssueResponse,
    InventoryImportApplyResponse,
    InventoryImportPreviewResponse,
)
from app.services.inventory_import import (
    DEFAULT_MAX_CSV_UPLOAD_BYTES,
    BucketSummary,
    ImportPlan,
    InventoryImportError,
    InventoryImportTooLargeError,
    PlannedChange,
    Strategy,
    apply_import_plan,
    build_import_plan,
    parse_inventory_csv,
    read_csv_upload,
    summarize_changes,
)
from app.services.ldraw_aliases import OfficialPartRecord, cached_moved_alias_resolver
from app.services.ldraw_library import get_library_status
from app.services.local_workspace import resolve_local_workspace
from app.services.model_coverage import normalize_part_id

LOGGER = logging.getLogger(__name__)

_PREVIEW_ROW_CAP = 500
_PREVIEW_ISSUE_CAP = 100
_CHANGE_ORDER = {"create": 1, "update": 2, "unchanged": 3}


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


def _item_query(workspace_id: int) -> Select[tuple[InventoryItem, Part, LDrawColor]]:
    return (
        select(InventoryItem, Part, LDrawColor)
        .outerjoin(Part, func.lower(Part.part_id) == func.lower(InventoryItem.part_id))
        .outerjoin(LDrawColor, LDrawColor.code == InventoryItem.color_code)
        .where(InventoryItem.workspace_id == workspace_id)
    )


def _canonical_alias_map(
    session: Session, library_root: FilesystemPath, part_ids: set[str]
) -> dict[str, str]:
    """Map raw part IDs to canonical official IDs via validated Moved-to aliases."""
    if not part_ids:
        return {}
    fingerprint = get_library_status(library_root).archive_sha256 or "unversioned-library"

    def load_official_records() -> list[OfficialPartRecord]:
        return [
            OfficialPartRecord(
                part_id=part.part_id,
                description=part.name,
                relative_path=part.relative_path,
            )
            for part in session.scalars(select(Part).where(Part.is_subpart.is_(False)))
        ]

    resolver = cached_moved_alias_resolver(library_root, fingerprint, load_official_records)
    return {
        source: resolution.canonical_part_id
        for source, resolution in resolver.resolve_many(part_ids).items()
        if resolution.status == "resolved"
    }


def _plan_from_upload(
    session: Session,
    library_root: FilesystemPath,
    file: UploadFile,
    strategy: Strategy,
    maximum_bytes: int,
) -> tuple[ImportPlan, int, str]:
    """Shared preview/apply path: one parse and one plan per uploaded file."""
    raw_filename = (file.filename or "").replace("\\", "/")
    file_name = PurePosixPath(raw_filename).name[:255]
    if PurePosixPath(file_name).suffix.lower() != ".csv":
        raise InventoryImportError("Only .csv files are supported")
    data = read_csv_upload(file.file, maximum_bytes)
    parsed = parse_inventory_csv(data)
    workspace = resolve_local_workspace(session)
    plan = build_import_plan(
        session,
        workspace.id,
        parsed,
        strategy,
        lambda part_ids: _canonical_alias_map(session, library_root, part_ids),
    )
    return plan, workspace.id, file_name


def _preview_row_sort_key(change: PlannedChange) -> tuple[int, str, int]:
    rank = 0 if change.unknown_reason is not None else _CHANGE_ORDER[change.change]
    return (rank, change.normalized_part_id, change.color_code)


def _bucket_response(summary: BucketSummary) -> ImportBucketSummaryResponse:
    return ImportBucketSummaryResponse(
        row_count=summary.row_count,
        create_count=summary.create_count,
        update_count=summary.update_count,
        unchanged_count=summary.unchanged_count,
        quantity_delta=summary.quantity_delta,
        missing_part_count=summary.missing_part_count,
        missing_color_count=summary.missing_color_count,
    )


def _preview_row(
    change: PlannedChange, part: Part | None, color: LDrawColor | None
) -> ImportPreviewRowResponse:
    asset_url: str | None = None
    if part is not None:
        try:
            asset_url = render_asset_url(part.relative_path)
        except ValueError:
            asset_url = None
    return ImportPreviewRowResponse(
        part_id=change.part_id,
        source_part_id=change.source_part_ids[0],
        canonicalized_from=change.canonicalized_from,
        color_code=change.color_code,
        quantity=change.quantity,
        current_quantity=change.current_quantity,
        resulting_quantity=change.resulting_quantity,
        change=change.change,
        unknown_reason=change.unknown_reason,
        part_name=part.name if part is not None else None,
        color_name=color.name if color is not None else None,
        color_hex=color.value_hex if color is not None else None,
        alpha=color.alpha if color is not None else None,
        render_asset_url=asset_url,
    )


def _preview_response(
    session: Session, plan: ImportPlan, file_name: str
) -> InventoryImportPreviewResponse:
    known = summarize_changes(change for change in plan.changes if change.unknown_reason is None)
    unknown = summarize_changes(
        change for change in plan.changes if change.unknown_reason is not None
    )
    ordered = sorted(plan.changes, key=_preview_row_sort_key)
    capped = ordered[:_PREVIEW_ROW_CAP]

    parts_by_normalized: dict[str, Part] = {}
    colors_by_code: dict[int, LDrawColor] = {}
    if capped:
        parts_by_normalized = {
            normalize_part_id(part.part_id): part
            for part in session.scalars(
                select(Part).where(
                    func.lower(Part.part_id).in_(
                        sorted({change.normalized_part_id for change in capped})
                    ),
                    Part.is_subpart.is_(False),
                )
            )
        }
        colors_by_code = {
            color.code: color
            for color in session.scalars(
                select(LDrawColor).where(
                    LDrawColor.code.in_(sorted({change.color_code for change in capped}))
                )
            )
        }

    return InventoryImportPreviewResponse(
        file_name=file_name,
        strategy=plan.strategy,
        total_data_rows=plan.total_data_rows,
        planned_row_count=len(plan.changes),
        duplicate_row_count=plan.duplicate_row_count,
        alias_canonicalized_count=sum(
            1 for change in plan.changes if change.canonicalized_from is not None
        ),
        ignored_columns=list(plan.ignored_columns),
        invalid_row_count=len(plan.issues),
        known=_bucket_response(known),
        unknown=_bucket_response(unknown),
        rows=[
            _preview_row(
                change,
                parts_by_normalized.get(change.normalized_part_id),
                colors_by_code.get(change.color_code),
            )
            for change in capped
        ],
        rows_truncated=len(ordered) > len(capped),
        issues=[
            ImportRowIssueResponse(
                line_number=issue.line_number, code=issue.code, message=issue.message
            )
            for issue in plan.issues[:_PREVIEW_ISSUE_CAP]
        ],
        issues_truncated=len(plan.issues) > _PREVIEW_ISSUE_CAP,
    )


def create_inventory_router(
    library_root: FilesystemPath,
    session_dependency: SessionDependency,
    import_max_upload_bytes: int = DEFAULT_MAX_CSV_UPLOAD_BYTES,
) -> APIRouter:
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

        total_items = (
            session.scalar(
                select(func.count())
                .select_from(InventoryItem)
                .outerjoin(Part, func.lower(Part.part_id) == func.lower(InventoryItem.part_id))
                .where(*filters)
            )
            or 0
        )
        ordering: list[SQLColumnExpression[Any]] = []
        if normalized_query:
            ordering.append(
                case(
                    (func.lower(InventoryItem.part_id) == normalized_query.lower(), 0),
                    else_=1,
                )
            )
        ordering.extend(
            (
                func.lower(func.coalesce(Part.name, InventoryItem.part_id)),
                InventoryItem.part_id,
                InventoryItem.color_code,
            )
        )
        rows = session.execute(
            _item_query(workspace.id)
            .where(*filters)
            .order_by(*ordering)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
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
        return [_response(item, part, color) for item, part, color in rows]

    @router.put("/items/{part_id}/{color_code}", response_model=InventoryItemResponse)
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

    @router.delete("/items/{part_id}/{color_code}", status_code=status.HTTP_204_NO_CONTENT)
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

    @router.post("/import/preview", response_model=InventoryImportPreviewResponse)
    def preview_import(
        file: UploadFile = File(...),
        strategy: Strategy = Form(...),
        session: Session = Depends(session_dependency),
    ) -> InventoryImportPreviewResponse:
        try:
            plan, _workspace_id, file_name = _plan_from_upload(
                session, library_root, file, strategy, import_max_upload_bytes
            )
            return _preview_response(session, plan, file_name)
        except InventoryImportTooLargeError as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        except InventoryImportError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            LOGGER.exception("Unexpected inventory import preview failure")
            raise HTTPException(
                status_code=500, detail="Inventory import preview failed"
            ) from error

    @router.post("/import/apply", response_model=InventoryImportApplyResponse)
    def apply_import(
        file: UploadFile = File(...),
        strategy: Strategy = Form(...),
        include_unknown: bool = Form(alias="includeUnknown"),
        session: Session = Depends(session_dependency),
    ) -> InventoryImportApplyResponse:
        try:
            plan, workspace_id, _file_name = _plan_from_upload(
                session, library_root, file, strategy, import_max_upload_bytes
            )
            counts = apply_import_plan(session, workspace_id, plan, include_unknown=include_unknown)
            session.commit()
            return InventoryImportApplyResponse(
                strategy=plan.strategy,
                include_unknown=include_unknown,
                applied_row_count=counts.applied_rows,
                created_count=counts.created,
                updated_count=counts.updated,
                unchanged_count=counts.unchanged,
                skipped_unknown_row_count=counts.skipped_unknown,
                invalid_row_count=len(plan.issues),
                quantity_delta=counts.quantity_delta,
            )
        except InventoryImportTooLargeError as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        except InventoryImportError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            LOGGER.exception("Unexpected inventory import apply failure")
            raise HTTPException(status_code=500, detail="Inventory import failed") from error

    return router
