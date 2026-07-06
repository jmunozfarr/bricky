"""Shared state and helpers for the model and instruction routers."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session, sessionmaker

from app.catalog_api import render_asset_url
from app.models import ImportedModel, InventoryItem, LDrawColor, ModelBomItem, Part
from app.schemas.models import (
    CoverageSummaryResponse,
    ModelBomItemResponse,
    ModelCoverageItemResponse,
    ModelSummaryResponse,
)
from app.services.instruction_graph import InstructionGraphLimits
from app.services.instruction_playback import (
    PlaybackData,
    RenderComplexityLimits,
    derive_occurrence_source,
    parse_playback_data,
)
from app.services.ldraw_library import get_library_status
from app.services.ldraw_model_parser import ModelParseError
from app.services.ldraw_pack import (
    PACKED_SOURCE_CACHE,
    PackedLDrawSource,
    pack_ldraw_source,
)
from app.services.local_workspace import resolve_local_workspace
from app.services.model_coverage import (
    CoverageItem,
    CoverageRequirement,
    CoverageSummary,
    InventoryQuantity,
    ModelCoverage,
    calculate_model_coverage,
    normalize_part_id,
)

SessionDependency = Callable[[], Iterator[Session]]

SCOPE_COMPLEXITY_DETAIL = {
    "code": "scope_complexity_limit",
    "message": "Complete subtree rendering exceeds the configured safety policy",
}


@dataclass(frozen=True)
class ModelsRouterContext:
    """Configuration and lookups shared by the model and instruction routes."""

    session_dependency: SessionDependency
    session_factory: sessionmaker[Session]
    library_root: Path
    storage_root: Path
    maximum_upload_bytes: int
    graph_limits: InstructionGraphLimits
    render_limits: RenderComplexityLimits

    def find_model(self, session: Session, model_id: object) -> ImportedModel | None:
        workspace = resolve_local_workspace(session)
        return session.scalar(
            select(ImportedModel).where(
                ImportedModel.public_id == model_id,
                ImportedModel.workspace_id == workspace.id,
            )
        )

    def playback_data_for(self, model: ImportedModel) -> PlaybackData:
        source_path = _managed_source_path(self.storage_root, model)
        if source_path is None or not source_path.is_file():
            raise HTTPException(status_code=404, detail="Model source not found")
        try:
            return parse_playback_data(
                model.source_sha256,
                model.original_filename,
                self.graph_limits,
                source_path.read_bytes,
            )
        except ModelParseError as error:
            raise HTTPException(
                status_code=422, detail=f"Instruction playback unavailable: {error}"
            ) from error

    def scene_identity(self, model: ImportedModel, occurrence_id: str, render_strategy: str) -> str:
        library = get_library_status(self.library_root)
        fingerprint = library.archive_sha256 or "unversioned-library"
        return hashlib.sha256(
            f"{model.source_sha256}:{occurrence_id}:{render_strategy}:complete:v3:{fingerprint}".encode(
                "ascii"
            )
        ).hexdigest()

    def packed_scene_for(
        self,
        model: ImportedModel,
        data: PlaybackData,
        occurrence_id: str,
        render_strategy: Literal["subtree", "local"],
    ) -> tuple[str, PackedLDrawSource]:
        cache_key = self.scene_identity(model, occurrence_id, render_strategy)
        cached = PACKED_SOURCE_CACHE.get(cache_key)
        if cached is not None:
            return cache_key, cached
        derived = derive_occurrence_source(
            data, occurrence_id, current_step=None, strategy=render_strategy
        )
        packed = pack_ldraw_source(derived, self.library_root)
        PACKED_SOURCE_CACHE.set(cache_key, packed, group=model.source_sha256)
        return cache_key, packed


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


def _summary(model: ImportedModel, coverage: CoverageSummary | None = None) -> ModelSummaryResponse:
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
    keys = sorted({(normalize_part_id(item.part_id), item.color_code) for item in requirements})
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
