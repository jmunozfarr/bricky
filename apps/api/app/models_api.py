from __future__ import annotations

import logging
import math
import shutil
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.catalog_api import render_asset_url
from app.models import (
    ImportedModel,
    LDrawColor,
    ModelBomItem,
    ModelImportIssue,
    Part,
)
from app.services.local_workspace import resolve_local_workspace
from app.services.model_import import (
    DuplicateModelError,
    ModelImportError,
    ModelTooLargeError,
    import_model,
)


LOGGER = logging.getLogger(__name__)
SessionDependency = Callable[[], Iterator[Session]]


class ModelSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_id: uuid.UUID = Field(alias="modelId")
    name: str
    original_filename: str = Field(alias="originalFilename")
    source_format: str = Field(alias="sourceFormat")
    import_status: str = Field(alias="importStatus")
    declared_step_count: int = Field(alias="declaredStepCount")
    total_part_quantity: int = Field(alias="totalPartQuantity")
    unique_part_color_count: int = Field(alias="uniquePartColorCount")
    unresolved_reference_count: int = Field(alias="unresolvedReferenceCount")
    created_at: datetime = Field(alias="createdAt")


class ModelsPageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[ModelSummaryResponse]
    page: int
    page_size: int = Field(alias="pageSize")
    total_items: int = Field(alias="totalItems")
    total_pages: int = Field(alias="totalPages")


class ModelBomItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    part_id: str = Field(alias="partId")
    part_name: str = Field(alias="partName")
    category: str
    color_code: int = Field(alias="colorCode")
    color_name: str = Field(alias="colorName")
    color_hex: str | None = Field(alias="colorHex")
    quantity: int
    catalog_available: bool = Field(alias="catalogAvailable")
    render_asset_url: str | None = Field(alias="renderAssetUrl")


class ModelIssueResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    severity: str
    code: str
    message: str
    referenced_filename: str | None = Field(alias="referencedFilename")


class ModelDetailResponse(ModelSummaryResponse):
    model_config = ConfigDict(populate_by_name=True)

    source_sha256: str = Field(alias="sourceSha256")
    source_url: str = Field(alias="sourceUrl")
    updated_at: datetime = Field(alias="updatedAt")
    bom: list[ModelBomItemResponse]
    issues: list[ModelIssueResponse]


def _summary(model: ImportedModel) -> ModelSummaryResponse:
    return ModelSummaryResponse(
        model_id=model.public_id,
        name=model.name,
        original_filename=model.original_filename,
        source_format=model.source_format,
        import_status=model.import_status,
        declared_step_count=model.declared_step_count,
        total_part_quantity=model.total_part_quantity,
        unique_part_color_count=model.unique_part_color_count,
        unresolved_reference_count=model.unresolved_reference_count,
        created_at=model.created_at,
    )


def _managed_source_path(storage_root: Path, model: ImportedModel) -> Path | None:
    relative = PurePosixPath(model.relative_storage_path)
    expected_prefix = ("originals", str(model.public_id))
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) != 3
        or relative.parts[:2] != expected_prefix
        or relative.name != model.safe_filename
    ):
        return None
    root = storage_root.resolve()
    candidate = (root / Path(*relative.parts)).resolve()
    if not candidate.is_relative_to(root):
        return None
    return candidate


def _bom_response(
    item: ModelBomItem, part: Part | None, color: LDrawColor | None
) -> ModelBomItemResponse:
    available = part is not None and not part.is_subpart
    asset_url: str | None = None
    if available and part is not None:
        try:
            asset_url = render_asset_url(part.relative_path)
        except ValueError:
            available = False
    return ModelBomItemResponse(
        part_id=item.part_id,
        part_name=part.name if part is not None else item.part_id,
        category=part.category if part is not None else "Unavailable",
        color_code=item.color_code,
        color_name=color.name if color is not None else f"Color {item.color_code}",
        color_hex=color.value_hex if color is not None else None,
        quantity=item.quantity,
        catalog_available=available,
        render_asset_url=asset_url,
    )


def create_models_router(
    session_dependency: SessionDependency,
    session_factory: sessionmaker[Session],
    storage_root: Path,
    maximum_upload_bytes: int,
) -> APIRouter:
    router = APIRouter(prefix="/api/models")

    @router.post("", response_model=ModelSummaryResponse, status_code=201)
    def upload_model(
        file: UploadFile = File(...),
        name: str | None = Form(default=None, max_length=256),
    ) -> ModelSummaryResponse:
        try:
            outcome = import_model(
                session_factory,
                storage_root,
                file.file,
                file.filename,
                name,
                maximum_upload_bytes,
            )
        except DuplicateModelError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(error),
                    "existingModelId": str(error.existing_model_id),
                },
            ) from error
        except ModelTooLargeError as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        except ModelImportError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            LOGGER.exception("Unexpected model import failure")
            raise HTTPException(status_code=500, detail="Model import failed") from error
        with session_factory() as session:
            model = session.scalar(
                select(ImportedModel).where(ImportedModel.public_id == outcome.public_id)
            )
            if model is None:
                raise HTTPException(status_code=500, detail="Imported model is unavailable")
            return _summary(model)

    @router.get("", response_model=ModelsPageResponse)
    def list_models(
        query: str = Query(default="", max_length=200),
        import_status: str | None = Query(default=None, alias="status", max_length=32),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=24, alias="pageSize", ge=1, le=100),
        session: Session = Depends(session_dependency),
    ) -> ModelsPageResponse:
        workspace = resolve_local_workspace(session)
        filters = [ImportedModel.workspace_id == workspace.id]
        normalized_query = query.strip()
        if normalized_query:
            escaped = normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    ImportedModel.name.ilike(pattern, escape="\\"),
                    ImportedModel.original_filename.ilike(pattern, escape="\\"),
                )
            )
        if import_status:
            normalized_status = import_status.strip().lower()
            if normalized_status not in {"ready", "ready_with_warnings", "failed"}:
                raise HTTPException(status_code=422, detail="Unknown model import status")
            filters.append(ImportedModel.import_status == normalized_status)
        total = session.scalar(
            select(func.count()).select_from(ImportedModel).where(*filters)
        ) or 0
        models = session.scalars(
            select(ImportedModel)
            .where(*filters)
            .order_by(ImportedModel.created_at.desc(), ImportedModel.public_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        session.commit()
        return ModelsPageResponse(
            items=[_summary(model) for model in models],
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

    def find_model(session: Session, model_id: uuid.UUID) -> ImportedModel | None:
        workspace = resolve_local_workspace(session)
        return session.scalar(
            select(ImportedModel).where(
                ImportedModel.public_id == model_id,
                ImportedModel.workspace_id == workspace.id,
            )
        )

    @router.get("/{model_id}", response_model=ModelDetailResponse)
    def model_detail(
        model_id: uuid.UUID, session: Session = Depends(session_dependency)
    ) -> ModelDetailResponse:
        model = find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        bom_rows = session.execute(
            select(ModelBomItem, Part, LDrawColor)
            .outerjoin(Part, func.lower(Part.part_id) == func.lower(ModelBomItem.part_id))
            .outerjoin(LDrawColor, LDrawColor.code == ModelBomItem.color_code)
            .where(ModelBomItem.model_id == model.id)
            .order_by(func.lower(ModelBomItem.part_id), ModelBomItem.color_code)
        ).all()
        issues = session.scalars(
            select(ModelImportIssue)
            .where(ModelImportIssue.model_id == model.id)
            .order_by(ModelImportIssue.id)
        ).all()
        session.commit()
        return ModelDetailResponse(
            **_summary(model).model_dump(),
            source_sha256=model.source_sha256,
            source_url=f"/api/models/{quote(str(model.public_id), safe='')}/source",
            updated_at=model.updated_at,
            bom=[_bom_response(*row) for row in bom_rows],
            issues=[
                ModelIssueResponse(
                    severity=issue.severity,
                    code=issue.code,
                    message=issue.message,
                    referenced_filename=issue.referenced_filename,
                )
                for issue in issues
            ],
        )

    @router.get("/{model_id}/source", response_class=FileResponse)
    def model_source(
        model_id: uuid.UUID, session: Session = Depends(session_dependency)
    ) -> FileResponse:
        model = find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        source_path = _managed_source_path(storage_root, model)
        session.commit()
        if source_path is None or not source_path.is_file():
            raise HTTPException(status_code=404, detail="Model source not found")
        encoded_filename = quote(model.safe_filename, safe="")
        return FileResponse(
            source_path,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"},
        )

    @router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_model(
        model_id: uuid.UUID, session: Session = Depends(session_dependency)
    ) -> Response:
        model = find_model(session, model_id)
        if model is None:
            session.commit()
            return Response(status_code=204)
        source_path = _managed_source_path(storage_root, model)
        model_directory = source_path.parent if source_path is not None else None
        session.execute(delete(ImportedModel).where(ImportedModel.id == model.id))
        session.commit()
        if model_directory is not None and model_directory.is_dir():
            shutil.rmtree(model_directory)
        return Response(status_code=204)

    return router
