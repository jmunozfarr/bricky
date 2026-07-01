from __future__ import annotations

import hashlib
import logging
import math
import shutil
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal
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
from sqlalchemy import delete, func, or_, select, tuple_
from sqlalchemy.orm import Session, sessionmaker

from app.catalog_api import render_asset_url
from app.models import (
    ImportedModel,
    InventoryItem,
    LDrawColor,
    ModelBomItem,
    ModelImportIssue,
    Part,
)
from app.services.instruction_graph import (
    InstructionGraph,
    InstructionGraphLimits,
    parse_instruction_graph,
)
from app.services.instruction_playback import (
    PLAYBACK_CHILD_PAGE_SIZE,
    PLAYBACK_CHILD_PAGE_SIZE_MAXIMUM,
    PlaybackData,
    RenderComplexity,
    RenderComplexityLimits,
    clear_playback_cache,
    derive_occurrence_source,
    parse_playback_data,
    playback_occurrence,
    select_render_strategy,
)
from app.services.ldraw_model_parser import ModelParseError
from app.services.local_workspace import resolve_local_workspace
from app.services.model_coverage import (
    CoverageItem,
    CoverageRequirement,
    CoverageStatus,
    CoverageSummary,
    InventoryQuantity,
    ModelCoverage,
    calculate_model_coverage,
    normalize_part_id,
)
from app.services.model_import import (
    DuplicateModelError,
    ModelImportError,
    ModelTooLargeError,
    import_model,
)


LOGGER = logging.getLogger(__name__)
SessionDependency = Callable[[], Iterator[Session]]


class CoverageSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_required_quantity: int = Field(alias="totalRequiredQuantity")
    total_available_quantity: int = Field(alias="totalAvailableQuantity")
    total_missing_quantity: int = Field(alias="totalMissingQuantity")
    unique_item_count: int = Field(alias="uniqueItemCount")
    complete_item_count: int = Field(alias="completeItemCount")
    partial_item_count: int = Field(alias="partialItemCount")
    missing_item_count: int = Field(alias="missingItemCount")
    piece_coverage_percentage: float = Field(alias="pieceCoveragePercentage")
    fully_buildable: bool = Field(alias="fullyBuildable")


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
    coverage: CoverageSummaryResponse | None = None


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


class ModelCoverageItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    part_id: str = Field(alias="partId")
    part_name: str = Field(alias="partName")
    category: str
    color_code: int = Field(alias="colorCode")
    color_name: str = Field(alias="colorName")
    color_hex: str | None = Field(alias="colorHex")
    required_quantity: int = Field(alias="requiredQuantity")
    owned_quantity: int = Field(alias="ownedQuantity")
    available_quantity: int = Field(alias="availableQuantity")
    missing_quantity: int = Field(alias="missingQuantity")
    coverage_percentage: float = Field(alias="coveragePercentage")
    status: CoverageStatus
    catalog_available: bool = Field(alias="catalogAvailable")
    render_asset_url: str | None = Field(alias="renderAssetUrl")


class ModelCoverageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_id: uuid.UUID = Field(alias="modelId")
    summary: CoverageSummaryResponse
    items: list[ModelCoverageItemResponse]


class ModelsReadinessResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_models: int = Field(alias="totalModels")
    fully_buildable_models: int = Field(alias="fullyBuildableModels")
    incomplete_models: int = Field(alias="incompleteModels")
    total_missing_quantity: int = Field(alias="totalMissingQuantity")


class InstructionTransformResponse(BaseModel):
    translation: tuple[float, float, float]
    matrix: tuple[float, float, float, float, float, float, float, float, float]


class LocalInstructionNodeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    node_index: int = Field(alias="nodeIndex")
    kind: Literal["part_reference", "submodel_reference"]
    source_filename: str = Field(alias="sourceFilename")
    color_code: int = Field(alias="colorCode")
    local_transform: InstructionTransformResponse = Field(alias="localTransform")
    source_order: int = Field(alias="sourceOrder")


class LocalDirectGeometryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    command_type: Literal[2, 3, 4, 5] = Field(alias="commandType")
    color_token: str = Field(alias="colorToken")
    coordinates: tuple[float, ...]
    local_step: int = Field(alias="localStep")
    source_order: int = Field(alias="sourceOrder")
    source_submodel_name: str = Field(alias="sourceSubmodelName")


class LocalStepDefinitionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    step: int
    nodes: list[LocalInstructionNodeResponse]
    direct_geometry: list[LocalDirectGeometryResponse] = Field(alias="directGeometry")


class ModelDefinitionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_submodel_name: str = Field(alias="sourceSubmodelName")
    local_steps: list[LocalStepDefinitionResponse] = Field(alias="localSteps")


class ModelOccurrenceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    occurrence_id: str = Field(alias="occurrenceId")
    parent_occurrence_id: str | None = Field(alias="parentOccurrenceId")
    source_submodel_name: str = Field(alias="sourceSubmodelName")
    local_transform: InstructionTransformResponse = Field(alias="localTransform")
    effective_color: int | None = Field(alias="effectiveColor")
    attachment_step: int | None = Field(alias="attachmentStep")
    depth: int
    traversal_order: int = Field(alias="traversalOrder")
    child_occurrence_ids: list[str] = Field(alias="childOccurrenceIds")


class ExpandedInstructionNodeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    instruction_node_id: str = Field(alias="instructionNodeId")
    occurrence_id: str = Field(alias="occurrenceId")
    local_step: int = Field(alias="localStep")
    node_index: int = Field(alias="nodeIndex")
    kind: Literal["part_reference", "submodel_attachment"]
    source_filename: str = Field(alias="sourceFilename")
    effective_color: int | None = Field(alias="effectiveColor")
    local_transform: InstructionTransformResponse = Field(alias="localTransform")
    child_occurrence_id: str | None = Field(alias="childOccurrenceId")
    source_order: int = Field(alias="sourceOrder")


class InstructionGraphIssueResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    severity: str
    code: str
    message: str
    source_submodel_name: str | None = Field(alias="sourceSubmodelName")
    source_filename: str | None = Field(alias="sourceFilename")
    occurrence_id: str | None = Field(alias="occurrenceId")
    configured_limit: int | None = Field(alias="configuredLimit")


class InstructionGraphLimitsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    maximum_nesting_depth: int = Field(alias="maximumNestingDepth")
    maximum_expanded_occurrences: int = Field(alias="maximumExpandedOccurrences")
    maximum_instruction_nodes: int = Field(alias="maximumInstructionNodes")


class InstructionGraphResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_id: uuid.UUID = Field(alias="modelId")
    root_occurrence_id: str = Field(alias="rootOccurrenceId")
    model_definitions: list[ModelDefinitionResponse] = Field(alias="modelDefinitions")
    occurrences: list[ModelOccurrenceResponse]
    instruction_nodes: list[ExpandedInstructionNodeResponse] = Field(alias="instructionNodes")
    maximum_nesting_depth: int = Field(alias="maximumNestingDepth")
    traversal_order: list[str] = Field(alias="traversalOrder")
    model_definition_count: int = Field(alias="modelDefinitionCount")
    expanded_occurrence_count: int = Field(alias="expandedOccurrenceCount")
    instruction_node_count: int = Field(alias="instructionNodeCount")
    issues: list[InstructionGraphIssueResponse]
    truncated: bool
    limits: InstructionGraphLimitsResponse


class InstructionPlaybackIssueResponse(BaseModel):
    code: str
    message: str


class InstructionPlaybackSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_id: uuid.UUID = Field(alias="modelId")
    available: bool
    root_occurrence_id: str | None = Field(alias="rootOccurrenceId")
    fallback_reason: str | None = Field(alias="fallbackReason")
    issues: list[InstructionPlaybackIssueResponse]
    recommended_render_strategy: Literal["subtree", "local"] | None = Field(
        alias="recommendedRenderStrategy"
    )
    render_strategy_reason: str = Field(alias="renderStrategyReason")
    complexity: "RenderComplexityResponse | None"
    flattened_rendering_allowed: bool = Field(alias="flattenedRenderingAllowed")


class RenderComplexityResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expanded_instruction_node_count: int = Field(alias="expandedInstructionNodeCount")
    expanded_occurrence_count: int = Field(alias="expandedOccurrenceCount")
    direct_geometry_command_count: int = Field(alias="directGeometryCommandCount")
    estimated_derived_source_bytes: int = Field(alias="estimatedDerivedSourceBytes")


class PlaybackBreadcrumbResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    occurrence_id: str = Field(alias="occurrenceId")
    source_submodel_name: str = Field(alias="sourceSubmodelName")


class PlaybackChildResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    occurrence_id: str = Field(alias="occurrenceId")
    source_submodel_name: str = Field(alias="sourceSubmodelName")
    attachment_step: int = Field(alias="attachmentStep")
    traversal_order: int = Field(alias="traversalOrder")
    repeated_definition_count: int = Field(alias="repeatedDefinitionCount")
    repeated_definition_index: int = Field(alias="repeatedDefinitionIndex")


class PlaybackStepSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    step: int
    local_part_count: int = Field(alias="localPartCount")
    child_attachment_count: int = Field(alias="childAttachmentCount")
    direct_geometry_command_count: int = Field(alias="directGeometryCommandCount")


class InstructionPlaybackOccurrenceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_id: uuid.UUID = Field(alias="modelId")
    occurrence_id: str = Field(alias="occurrenceId")
    parent_occurrence_id: str | None = Field(alias="parentOccurrenceId")
    source_submodel_name: str = Field(alias="sourceSubmodelName")
    attachment_step: int | None = Field(alias="attachmentStep")
    depth: int
    traversal_order: int = Field(alias="traversalOrder")
    breadcrumbs: list[PlaybackBreadcrumbResponse]
    local_step_count: int = Field(alias="localStepCount")
    current_step: int = Field(alias="currentStep")
    previous_step: int | None = Field(alias="previousStep")
    next_step: int | None = Field(alias="nextStep")
    complete: bool
    empty: bool
    repeated_definition_count: int = Field(alias="repeatedDefinitionCount")
    repeated_definition_index: int = Field(alias="repeatedDefinitionIndex")
    step_summary: PlaybackStepSummaryResponse = Field(alias="stepSummary")
    children: list[PlaybackChildResponse]
    child_total: int = Field(alias="childTotal")
    child_offset: int = Field(alias="childOffset")
    child_limit: int = Field(alias="childLimit")
    scene_source_url: str = Field(alias="sceneSourceUrl")
    render_strategy: Literal["subtree", "local"] = Field(alias="renderStrategy")
    recommended_render_strategy: Literal["subtree", "local"] = Field(
        alias="recommendedRenderStrategy"
    )
    render_strategy_reason: str = Field(alias="renderStrategyReason")
    complexity: RenderComplexityResponse


def _render_complexity_response(
    complexity: RenderComplexity,
) -> RenderComplexityResponse:
    return RenderComplexityResponse(
        expanded_instruction_node_count=complexity.expanded_instruction_node_count,
        expanded_occurrence_count=complexity.expanded_occurrence_count,
        direct_geometry_command_count=complexity.direct_geometry_command_count,
        estimated_derived_source_bytes=complexity.estimated_derived_source_bytes,
    )


def _instruction_graph_response(
    model_id: uuid.UUID,
    graph: InstructionGraph,
    limits: InstructionGraphLimits,
) -> InstructionGraphResponse:
    return InstructionGraphResponse(
        model_id=model_id,
        root_occurrence_id=graph.root_occurrence_id,
        model_definitions=[
            ModelDefinitionResponse(
                source_submodel_name=definition.source_submodel_name,
                local_steps=[
                    LocalStepDefinitionResponse(
                        step=step.step,
                        nodes=[
                            LocalInstructionNodeResponse(
                                node_index=node.node_index,
                                kind=node.kind,
                                source_filename=node.source_filename,
                                color_code=node.color_code,
                                local_transform=InstructionTransformResponse(
                                    translation=node.local_transform.translation,
                                    matrix=node.local_transform.matrix,
                                ),
                                source_order=node.source_order,
                            )
                            for node in step.nodes
                        ],
                        direct_geometry=[
                            LocalDirectGeometryResponse(
                                command_type=geometry.command_type,
                                color_token=geometry.color_token,
                                coordinates=geometry.coordinates,
                                local_step=geometry.local_step,
                                source_order=geometry.source_order,
                                source_submodel_name=geometry.source_submodel_name,
                            )
                            for geometry in step.direct_geometry
                        ],
                    )
                    for step in definition.local_steps
                ],
            )
            for definition in graph.model_definitions
        ],
        occurrences=[
            ModelOccurrenceResponse(
                occurrence_id=occurrence.occurrence_id,
                parent_occurrence_id=occurrence.parent_occurrence_id,
                source_submodel_name=occurrence.source_submodel_name,
                local_transform=InstructionTransformResponse(
                    translation=occurrence.local_transform.translation,
                    matrix=occurrence.local_transform.matrix,
                ),
                effective_color=occurrence.effective_color,
                attachment_step=occurrence.attachment_step,
                depth=occurrence.depth,
                traversal_order=occurrence.traversal_order,
                child_occurrence_ids=list(occurrence.child_occurrence_ids),
            )
            for occurrence in graph.occurrences
        ],
        instruction_nodes=[
            ExpandedInstructionNodeResponse(
                instruction_node_id=node.instruction_node_id,
                occurrence_id=node.occurrence_id,
                local_step=node.local_step,
                node_index=node.node_index,
                kind=node.kind,
                source_filename=node.source_filename,
                effective_color=node.effective_color,
                local_transform=InstructionTransformResponse(
                    translation=node.local_transform.translation,
                    matrix=node.local_transform.matrix,
                ),
                child_occurrence_id=node.child_occurrence_id,
                source_order=node.source_order,
            )
            for node in graph.instruction_nodes
        ],
        maximum_nesting_depth=graph.maximum_nesting_depth,
        traversal_order=list(graph.traversal_order),
        model_definition_count=len(graph.model_definitions),
        expanded_occurrence_count=len(graph.occurrences),
        instruction_node_count=len(graph.instruction_nodes),
        issues=[
            InstructionGraphIssueResponse(
                severity=issue.severity,
                code=issue.code,
                message=issue.message,
                source_submodel_name=issue.source_submodel_name,
                source_filename=issue.source_filename,
                occurrence_id=issue.occurrence_id,
                configured_limit=issue.configured_limit,
            )
            for issue in graph.issues
        ],
        truncated=graph.truncated,
        limits=InstructionGraphLimitsResponse(
            maximum_nesting_depth=limits.max_nesting_depth,
            maximum_expanded_occurrences=limits.max_expanded_occurrences,
            maximum_instruction_nodes=limits.max_instruction_nodes,
        ),
    )


def _coverage_summary(summary: CoverageSummary) -> CoverageSummaryResponse:
    return CoverageSummaryResponse(
        total_required_quantity=summary.total_required_quantity,
        total_available_quantity=summary.total_available_quantity,
        total_missing_quantity=summary.total_missing_quantity,
        unique_item_count=summary.unique_item_count,
        complete_item_count=summary.complete_item_count,
        partial_item_count=summary.partial_item_count,
        missing_item_count=summary.missing_item_count,
        piece_coverage_percentage=summary.piece_coverage_percentage,
        fully_buildable=summary.fully_buildable,
    )


def _summary(
    model: ImportedModel, coverage: CoverageSummary | None = None
) -> ModelSummaryResponse:
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
        coverage=_coverage_summary(coverage) if coverage is not None else None,
    )


def _inventory_for_requirements(
    session: Session,
    workspace_id: int,
    requirements: list[CoverageRequirement],
) -> list[InventoryQuantity]:
    keys = sorted(
        {
            (normalize_part_id(item.part_id), item.color_code)
            for item in requirements
        }
    )
    if not keys:
        return []
    rows = session.execute(
        select(
            InventoryItem.part_id,
            InventoryItem.color_code,
            InventoryItem.quantity,
        ).where(
            InventoryItem.workspace_id == workspace_id,
            tuple_(
                func.lower(func.trim(InventoryItem.part_id)),
                InventoryItem.color_code,
            ).in_(keys),
        )
    ).all()
    return [
        InventoryQuantity(
            part_id=part_id,
            color_code=color_code,
            owned_quantity=quantity,
        )
        for part_id, color_code, quantity in rows
    ]


def _coverage_by_model(
    session: Session,
    workspace_id: int,
    requirements_by_model: dict[int, list[CoverageRequirement]],
) -> dict[int, ModelCoverage]:
    all_requirements = [
        requirement
        for requirements in requirements_by_model.values()
        for requirement in requirements
    ]
    inventory = _inventory_for_requirements(session, workspace_id, all_requirements)
    return {
        model_id: calculate_model_coverage(requirements, inventory)
        for model_id, requirements in requirements_by_model.items()
    }


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


def _coverage_item_response(
    item: CoverageItem, part: Part | None, color: LDrawColor | None
) -> ModelCoverageItemResponse:
    catalog_available = part is not None and not part.is_subpart
    asset_url: str | None = None
    if catalog_available and part is not None:
        try:
            asset_url = render_asset_url(part.relative_path)
        except ValueError:
            catalog_available = False
    return ModelCoverageItemResponse(
        part_id=item.part_id,
        part_name=part.name if part is not None else item.part_id,
        category=part.category if part is not None else "Unavailable",
        color_code=item.color_code,
        color_name=color.name if color is not None else f"Color {item.color_code}",
        color_hex=color.value_hex if color is not None else None,
        required_quantity=item.required_quantity,
        owned_quantity=item.owned_quantity,
        available_quantity=item.available_quantity,
        missing_quantity=item.missing_quantity,
        coverage_percentage=item.coverage_percentage,
        status=item.status,
        catalog_available=catalog_available,
        render_asset_url=asset_url,
    )


def create_models_router(
    session_dependency: SessionDependency,
    session_factory: sessionmaker[Session],
    library_root: Path,
    storage_root: Path,
    maximum_upload_bytes: int,
    instruction_graph_limits: InstructionGraphLimits | None = None,
    render_complexity_limits: RenderComplexityLimits | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/models")
    active_graph_limits = instruction_graph_limits or InstructionGraphLimits()
    active_render_limits = render_complexity_limits or RenderComplexityLimits()

    @router.post("", response_model=ModelSummaryResponse, status_code=201)
    def upload_model(
        file: UploadFile = File(...),
        name: str | None = Form(default=None, max_length=256),
    ) -> ModelSummaryResponse:
        try:
            outcome = import_model(
                session_factory,
                storage_root,
                library_root,
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
        coverage_by_model = _coverage_by_model(
            session, workspace.id, requirements_by_model
        )
        session.commit()
        return ModelsPageResponse(
            items=[
                _summary(model, coverage_by_model[model.id].summary)
                for model in models
            ],
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

    @router.get("/readiness-summary", response_model=ModelsReadinessResponse)
    def readiness_summary(
        session: Session = Depends(session_dependency),
    ) -> ModelsReadinessResponse:
        workspace = resolve_local_workspace(session)
        model_ids = list(
            session.scalars(
                select(ImportedModel.id).where(
                    ImportedModel.workspace_id == workspace.id
                )
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
        session.commit()
        return ModelsReadinessResponse(
            total_models=len(model_ids),
            fully_buildable_models=fully_buildable,
            incomplete_models=len(model_ids) - fully_buildable,
            total_missing_quantity=sum(
                summary.total_missing_quantity for summary in summaries
            ),
        )

    def find_model(session: Session, model_id: uuid.UUID) -> ImportedModel | None:
        workspace = resolve_local_workspace(session)
        return session.scalar(
            select(ImportedModel).where(
                ImportedModel.public_id == model_id,
                ImportedModel.workspace_id == workspace.id,
            )
        )

    def playback_data_for(model: ImportedModel) -> PlaybackData:
        source_path = _managed_source_path(storage_root, model)
        if source_path is None or not source_path.is_file():
            raise HTTPException(status_code=404, detail="Model source not found")
        try:
            return parse_playback_data(
                model.source_sha256,
                source_path.read_bytes(),
                model.original_filename,
                active_graph_limits,
            )
        except ModelParseError as error:
            raise HTTPException(
                status_code=422, detail=f"Instruction playback unavailable: {error}"
            ) from error

    @router.get("/{model_id}/coverage", response_model=ModelCoverageResponse)
    def model_coverage(
        model_id: uuid.UUID,
        coverage_status: Literal["complete", "partial", "missing"] | None = Query(
            default=None, alias="status"
        ),
        query: str = Query(default="", max_length=200),
        session: Session = Depends(session_dependency),
    ) -> ModelCoverageResponse:
        model = find_model(session, model_id)
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
            part, color = metadata[
                (normalize_part_id(item.part_id), item.color_code)
            ]
            if coverage_status is not None and item.status != coverage_status:
                continue
            part_name = part.name if part is not None else item.part_id
            if normalized_query and normalized_query not in item.part_id.lower() and normalized_query not in part_name.lower():
                continue
            response_items.append(_coverage_item_response(item, part, color))
        session.commit()
        return ModelCoverageResponse(
            model_id=model.public_id,
            summary=_coverage_summary(coverage.summary),
            items=response_items,
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

    @router.get(
        "/{model_id}/instruction-playback",
        response_model=InstructionPlaybackSummaryResponse,
    )
    def model_instruction_playback(
        model_id: uuid.UUID, session: Session = Depends(session_dependency)
    ) -> InstructionPlaybackSummaryResponse:
        model = find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        data = playback_data_for(model)
        session.commit()
        fallback_reason = None
        selection = (
            select_render_strategy(
                data, data.graph.root_occurrence_id, active_render_limits
            )
            if data.available
            else None
        )
        if not data.available:
            fallback_reason = (
                data.issues[0].message
                if data.issues
                else "The instruction graph is incomplete"
            )
        return InstructionPlaybackSummaryResponse(
            model_id=model.public_id,
            available=data.available,
            root_occurrence_id=(
                data.graph.root_occurrence_id if data.available else None
            ),
            fallback_reason=fallback_reason,
            issues=[
                InstructionPlaybackIssueResponse(
                    code=issue.code, message=issue.message
                )
                for issue in data.issues
            ],
            recommended_render_strategy=(
                selection.recommended_strategy if selection is not None else None
            ),
            render_strategy_reason=(
                selection.reason
                if selection is not None
                else "instruction_graph_unavailable"
            ),
            complexity=(
                _render_complexity_response(selection.complexity)
                if selection is not None
                else None
            ),
            flattened_rendering_allowed=(
                selection is None or selection.recommended_strategy == "subtree"
            ),
        )

    @router.get(
        "/{model_id}/instruction-occurrences/{occurrence_id}",
        response_model=InstructionPlaybackOccurrenceResponse,
    )
    def model_instruction_occurrence(
        model_id: uuid.UUID,
        occurrence_id: str,
        step: int = Query(default=1, ge=1),
        child_offset: int = Query(default=0, alias="childOffset", ge=0),
        child_limit: int = Query(
            default=PLAYBACK_CHILD_PAGE_SIZE,
            alias="childLimit",
            ge=1,
            le=PLAYBACK_CHILD_PAGE_SIZE_MAXIMUM,
        ),
        requested_strategy: Literal["recommended", "subtree", "local"] = Query(
            default="recommended", alias="renderStrategy"
        ),
        session: Session = Depends(session_dependency),
    ) -> InstructionPlaybackOccurrenceResponse:
        model = find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        data = playback_data_for(model)
        if occurrence_id not in data.occurrence_by_id:
            raise HTTPException(status_code=404, detail="Instruction occurrence not found")
        if not data.available:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Hierarchical playback is unavailable",
                    "issues": [
                        {"code": issue.code, "message": issue.message}
                        for issue in data.issues
                    ],
                },
            )
        try:
            result = playback_occurrence(
                data,
                occurrence_id,
                current_step=step,
                child_offset=child_offset,
                child_limit=child_limit,
            )
            selection = select_render_strategy(
                data, occurrence_id, active_render_limits
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        render_strategy = (
            selection.recommended_strategy
            if requested_strategy == "recommended"
            else requested_strategy
        )
        if (
            render_strategy == "subtree"
            and selection.recommended_strategy == "local"
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "scope_complexity_limit",
                    "message": "Complete subtree rendering exceeds the configured safety policy",
                },
            )
        session.commit()
        occurrence = result.occurrence
        encoded_occurrence = quote(occurrence_id, safe="")
        return InstructionPlaybackOccurrenceResponse(
            model_id=model.public_id,
            occurrence_id=occurrence.occurrence_id,
            parent_occurrence_id=occurrence.parent_occurrence_id,
            source_submodel_name=occurrence.source_submodel_name,
            attachment_step=occurrence.attachment_step,
            depth=occurrence.depth,
            traversal_order=occurrence.traversal_order,
            breadcrumbs=[
                PlaybackBreadcrumbResponse(
                    occurrence_id=item.occurrence_id,
                    source_submodel_name=item.source_submodel_name,
                )
                for item in result.breadcrumbs
            ],
            local_step_count=result.local_step_count,
            current_step=result.current_step,
            previous_step=result.previous_step,
            next_step=result.next_step,
            complete=result.complete,
            empty=result.empty,
            repeated_definition_count=result.repeated_definition_count,
            repeated_definition_index=result.repeated_definition_index,
            step_summary=PlaybackStepSummaryResponse(
                step=result.step_summary.step,
                local_part_count=result.step_summary.local_part_count,
                child_attachment_count=result.step_summary.child_attachment_count,
                direct_geometry_command_count=(
                    result.step_summary.direct_geometry_command_count
                ),
            ),
            children=[
                PlaybackChildResponse(
                    occurrence_id=child.occurrence_id,
                    source_submodel_name=child.source_submodel_name,
                    attachment_step=child.attachment_step,
                    traversal_order=child.traversal_order,
                    repeated_definition_count=child.repeated_definition_count,
                    repeated_definition_index=child.repeated_definition_index,
                )
                for child in result.children
            ],
            child_total=result.child_total,
            child_offset=result.child_offset,
            child_limit=result.child_limit,
            scene_source_url=(
                f"/api/models/{quote(str(model.public_id), safe='')}/"
                f"instruction-occurrences/{encoded_occurrence}/source"
                f"?mode={render_strategy}&step={result.current_step}"
            ),
            render_strategy=render_strategy,
            recommended_render_strategy=selection.recommended_strategy,
            render_strategy_reason=selection.reason,
            complexity=_render_complexity_response(selection.complexity),
        )

    @router.get(
        "/{model_id}/instruction-occurrences/{occurrence_id}/source",
        response_class=Response,
    )
    def model_instruction_occurrence_source(
        model_id: uuid.UUID,
        occurrence_id: str,
        mode: Literal["subtree", "local"] = Query(default="subtree"),
        step: int | None = Query(default=None, ge=1),
        session: Session = Depends(session_dependency),
    ) -> Response:
        model = find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        data = playback_data_for(model)
        if occurrence_id not in data.occurrence_by_id:
            raise HTTPException(status_code=404, detail="Instruction occurrence not found")
        if not data.available:
            raise HTTPException(
                status_code=409, detail="Hierarchical playback is unavailable"
            )
        try:
            selection = select_render_strategy(
                data, occurrence_id, active_render_limits
            )
            if mode == "subtree" and selection.recommended_strategy == "local":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "scope_complexity_limit",
                        "message": "Complete subtree rendering exceeds the configured safety policy",
                    },
                )
            content = derive_occurrence_source(
                data, occurrence_id, current_step=step, strategy=mode
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        session.commit()
        etag = hashlib.sha256(
            f"{model.source_sha256}:{occurrence_id}:{mode}:{step or 'complete'}:v2".encode("ascii")
        ).hexdigest()
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={
                "Cache-Control": "private, max-age=3600",
                "ETag": f'"{etag}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get(
        "/{model_id}/instruction-graph", response_model=InstructionGraphResponse
    )
    def model_instruction_graph(
        model_id: uuid.UUID, session: Session = Depends(session_dependency)
    ) -> InstructionGraphResponse:
        model = find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        source_path = _managed_source_path(storage_root, model)
        session.commit()
        if source_path is None or not source_path.is_file():
            raise HTTPException(status_code=404, detail="Model source not found")
        try:
            graph = parse_instruction_graph(
                source_path.read_bytes(),
                source_name=model.original_filename,
                limits=active_graph_limits,
            )
        except ModelParseError as error:
            raise HTTPException(
                status_code=422, detail=f"Instruction graph unavailable: {error}"
            ) from error
        return _instruction_graph_response(model.public_id, graph, active_graph_limits)

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
        clear_playback_cache()
        if model_directory is not None and model_directory.is_dir():
            shutil.rmtree(model_directory)
        return Response(status_code=204)

    return router
