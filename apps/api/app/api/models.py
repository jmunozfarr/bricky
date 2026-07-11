"""Model CRUD, coverage, and source routes."""

from __future__ import annotations

import logging
import math
import shutil
import uuid
from typing import Literal
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.api.helpers import (
    ModelsRouterContext,
    _bom_response,
    _coverage_by_model,
    _coverage_item_response,
    _coverage_summary,
    _inventory_for_requirements,
    _summary,
)
from app.models import (
    ImportedModel,
    LDrawColor,
    ModelBomItem,
    ModelImportIssue,
    ModelReferenceResolution,
    Part,
)
from app.schemas.models import (
    ModelCoverageItemResponse,
    ModelCoverageResponse,
    ModelDetailResponse,
    ModelIssueResponse,
    ModelResolutionRequest,
    ModelResolutionResponse,
    ModelsPageResponse,
    ModelsReadinessResponse,
    ModelSummaryResponse,
)
from app.services.instruction_playback import clear_playback_cache
from app.services.ldraw_model_parser import normalize_reference
from app.services.ldraw_pack import PACKED_SOURCE_CACHE
from app.services.local_workspace import resolve_local_workspace
from app.services.model_coverage import (
    CoverageRequirement,
    calculate_model_coverage,
    normalize_part_id,
)
from app.services.model_import import (
    DuplicateModelError,
    ModelImportError,
    ModelTooLargeError,
    import_model,
    managed_source_path,
)
from app.services.model_reprocess import (
    ModelReprocessError,
    ModelSourceIntegrityError,
    reprocess_model,
)

LOGGER = logging.getLogger(__name__)


def _detail_response(session: Session, model: ImportedModel) -> ModelDetailResponse:
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
    resolutions = session.scalars(
        select(ModelReferenceResolution)
        .where(ModelReferenceResolution.model_id == model.id)
        .order_by(ModelReferenceResolution.source_reference)
    ).all()
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
                occurrence_count=issue.occurrence_count,
            )
            for issue in issues
        ],
        resolutions=[
            ModelResolutionResponse(
                source_reference=resolution.source_reference,
                action=resolution.action,
                part_id=resolution.target_part_id,
                color_code=resolution.color_code,
            )
            for resolution in resolutions
        ],
    )


def register_model_routes(router: APIRouter, context: ModelsRouterContext) -> None:
    @router.post("", response_model=ModelSummaryResponse, status_code=201)
    def upload_model(
        file: UploadFile = File(...),
        name: str | None = Form(default=None, max_length=256),
    ) -> ModelSummaryResponse:
        try:
            outcome = import_model(
                context.session_factory,
                context.storage_root,
                context.library_root,
                file.file,
                file.filename,
                name,
                context.maximum_upload_bytes,
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
        with context.session_factory() as session:
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
        session: Session = Depends(context.session_dependency),
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
        total = session.scalar(select(func.count()).select_from(ImportedModel).where(*filters)) or 0
        models = session.scalars(
            select(ImportedModel)
            .where(*filters)
            .order_by(ImportedModel.created_at.desc(), ImportedModel.public_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        requirements_by_model: dict[int, list[CoverageRequirement]] = {
            model.id: [] for model in models
        }
        if requirements_by_model:
            for model_id, part_id, color_code, quantity in session.execute(
                select(
                    ModelBomItem.model_id,
                    ModelBomItem.part_id,
                    ModelBomItem.color_code,
                    ModelBomItem.quantity,
                ).where(ModelBomItem.model_id.in_(requirements_by_model))
            ):
                requirements_by_model[model_id].append(
                    CoverageRequirement(
                        part_id=part_id,
                        color_code=color_code,
                        required_quantity=quantity,
                    )
                )
        coverage_by_model = _coverage_by_model(session, workspace.id, requirements_by_model)
        return ModelsPageResponse(
            items=[_summary(model, coverage_by_model[model.id].summary) for model in models],
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

    @router.get("/readiness-summary", response_model=ModelsReadinessResponse)
    def readiness_summary(
        session: Session = Depends(context.session_dependency),
    ) -> ModelsReadinessResponse:
        workspace = resolve_local_workspace(session)
        model_ids = list(
            session.scalars(
                select(ImportedModel.id).where(ImportedModel.workspace_id == workspace.id)
            )
        )
        requirements_by_model: dict[int, list[CoverageRequirement]] = {
            model_id: [] for model_id in model_ids
        }
        if model_ids:
            for model_id, part_id, color_code, quantity in session.execute(
                select(
                    ModelBomItem.model_id,
                    ModelBomItem.part_id,
                    ModelBomItem.color_code,
                    ModelBomItem.quantity,
                ).where(ModelBomItem.model_id.in_(model_ids))
            ):
                requirements_by_model[model_id].append(
                    CoverageRequirement(part_id, color_code, quantity)
                )
        coverages = _coverage_by_model(session, workspace.id, requirements_by_model)
        summaries = [coverage.summary for coverage in coverages.values()]
        fully_buildable = sum(summary.fully_buildable for summary in summaries)
        return ModelsReadinessResponse(
            total_models=len(model_ids),
            fully_buildable_models=fully_buildable,
            incomplete_models=len(model_ids) - fully_buildable,
            total_missing_quantity=sum(summary.total_missing_quantity for summary in summaries),
        )

    @router.get("/{model_id}/coverage", response_model=ModelCoverageResponse)
    def model_coverage(
        model_id: uuid.UUID,
        coverage_status: Literal["complete", "partial", "missing"] | None = Query(
            default=None, alias="status"
        ),
        query: str = Query(default="", max_length=200),
        session: Session = Depends(context.session_dependency),
    ) -> ModelCoverageResponse:
        model = context.find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        workspace = resolve_local_workspace(session)
        bom_rows = session.execute(
            select(ModelBomItem, Part, LDrawColor)
            .outerjoin(Part, func.lower(Part.part_id) == func.lower(ModelBomItem.part_id))
            .outerjoin(LDrawColor, LDrawColor.code == ModelBomItem.color_code)
            .where(ModelBomItem.model_id == model.id)
        ).all()
        requirements = [
            CoverageRequirement(
                part_id=item.part_id,
                color_code=item.color_code,
                required_quantity=item.quantity,
            )
            for item, _part, _color in bom_rows
        ]
        coverage = calculate_model_coverage(
            requirements,
            _inventory_for_requirements(session, workspace.id, requirements),
        )
        metadata = {
            (normalize_part_id(item.part_id), item.color_code): (part, color)
            for item, part, color in bom_rows
        }
        normalized_query = query.strip().lower()
        response_items: list[ModelCoverageItemResponse] = []
        for item in sorted(
            coverage.items,
            key=lambda entry: (
                {"missing": 0, "partial": 1, "complete": 2}[entry.status],
                normalize_part_id(entry.part_id),
                entry.color_code,
            ),
        ):
            part, color = metadata[(normalize_part_id(item.part_id), item.color_code)]
            if coverage_status is not None and item.status != coverage_status:
                continue
            part_name = part.name if part is not None else item.part_id
            if (
                normalized_query
                and normalized_query not in item.part_id.lower()
                and normalized_query not in part_name.lower()
            ):
                continue
            response_items.append(_coverage_item_response(item, part, color))
        return ModelCoverageResponse(
            model_id=model.public_id,
            summary=_coverage_summary(coverage.summary),
            items=response_items,
        )

    @router.get("/{model_id}", response_model=ModelDetailResponse)
    def model_detail(
        model_id: uuid.UUID, session: Session = Depends(context.session_dependency)
    ) -> ModelDetailResponse:
        model = context.find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        return _detail_response(session, model)

    def _reprocessed_detail(session: Session, model_id: uuid.UUID) -> ModelDetailResponse:
        try:
            reprocess_model(
                context.session_factory,
                context.storage_root,
                context.library_root,
                model_id,
            )
        except ModelSourceIntegrityError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ModelReprocessError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ModelImportError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        # The reprocess ran in its own session; drop any instance this request
        # already loaded so the response reflects the re-derived columns.
        session.expire_all()
        model = context.find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        return _detail_response(session, model)

    @router.post("/{model_id}/reprocess", response_model=ModelDetailResponse)
    def reprocess_imported_model(
        model_id: uuid.UUID, session: Session = Depends(context.session_dependency)
    ) -> ModelDetailResponse:
        return _reprocessed_detail(session, model_id)

    @router.put("/{model_id}/resolutions", response_model=ModelDetailResponse)
    def upsert_reference_resolution(
        model_id: uuid.UUID,
        payload: ModelResolutionRequest,
        session: Session = Depends(context.session_dependency),
    ) -> ModelDetailResponse:
        model = context.find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        source_reference = normalize_reference(payload.source_reference)
        if source_reference is None:
            raise HTTPException(status_code=422, detail="Unsafe or invalid source reference")
        target_part_id: str | None = None
        color_code = payload.color_code
        if payload.action == "map":
            requested_part = (payload.part_id or "").strip()
            if not requested_part:
                raise HTTPException(
                    status_code=422, detail="A mapped resolution requires a part id"
                )
            part = session.scalar(
                select(Part).where(
                    func.lower(Part.part_id) == requested_part.lower(),
                    Part.is_subpart.is_(False),
                )
            )
            if part is None:
                raise HTTPException(status_code=422, detail="Unknown official part id")
            target_part_id = part.part_id
            if color_code is not None and (
                color_code in (16, 24)
                or session.scalar(select(LDrawColor).where(LDrawColor.code == color_code)) is None
            ):
                raise HTTPException(status_code=422, detail="Unknown or non-physical color code")
        else:
            color_code = None
        existing = session.scalar(
            select(ModelReferenceResolution).where(
                ModelReferenceResolution.model_id == model.id,
                ModelReferenceResolution.source_reference == source_reference,
            )
        )
        if existing is None:
            session.add(
                ModelReferenceResolution(
                    model_id=model.id,
                    source_reference=source_reference,
                    action=payload.action,
                    target_part_id=target_part_id,
                    color_code=color_code,
                )
            )
        else:
            existing.action = payload.action
            existing.target_part_id = target_part_id
            existing.color_code = color_code
        session.commit()
        return _reprocessed_detail(session, model_id)

    @router.delete("/{model_id}/resolutions", response_model=ModelDetailResponse)
    def delete_reference_resolution(
        model_id: uuid.UUID,
        source: str = Query(min_length=1, max_length=255),
        session: Session = Depends(context.session_dependency),
    ) -> ModelDetailResponse:
        model = context.find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        source_reference = normalize_reference(source)
        if source_reference is None:
            raise HTTPException(status_code=422, detail="Unsafe or invalid source reference")
        existing = session.scalar(
            select(ModelReferenceResolution).where(
                ModelReferenceResolution.model_id == model.id,
                ModelReferenceResolution.source_reference == source_reference,
            )
        )
        if existing is None:
            return _detail_response(session, model)
        session.delete(existing)
        session.commit()
        return _reprocessed_detail(session, model_id)

    @router.get("/{model_id}/source", response_class=FileResponse)
    def model_source(
        model_id: uuid.UUID,
        request: Request,
        session: Session = Depends(context.session_dependency),
    ) -> Response:
        model = context.find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        source_path = managed_source_path(context.storage_root, model)
        if source_path is None or not source_path.is_file():
            raise HTTPException(status_code=404, detail="Model source not found")
        # Imported sources are immutable, so the stored hash is the ETag.
        etag = f'"{model.source_sha256}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        encoded_filename = quote(model.safe_filename, safe="")
        return FileResponse(
            source_path,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}",
                "ETag": etag,
            },
        )

    @router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_model(
        model_id: uuid.UUID, session: Session = Depends(context.session_dependency)
    ) -> Response:
        model = context.find_model(session, model_id)
        if model is None:
            session.commit()
            return Response(status_code=204)
        source_path = managed_source_path(context.storage_root, model)
        model_directory = source_path.parent if source_path is not None else None
        session.execute(delete(ImportedModel).where(ImportedModel.id == model.id))
        session.commit()
        clear_playback_cache()
        PACKED_SOURCE_CACHE.evict_group(model.source_sha256)
        if model_directory is not None and model_directory.is_dir():
            shutil.rmtree(model_directory)
        return Response(status_code=204)
