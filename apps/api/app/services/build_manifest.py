"""Build-manifest assembly for one instruction occurrence.

Extracted from the models router: everything after the route's existence
and availability guards. Router-owned concerns (scene identity, packed
scene caching, inventory lookup) are injected as callables so this module
never imports from `app.api`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import quote

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.models import ImportedModel, InventoryItem, LDrawColor, ModelBomItem, Part
from app.schemas.instructions import (
    BuildManifestResponse,
    BuildSceneResponse,
    BuildStepPartResponse,
    BuildStepResponse,
    PlaybackBreadcrumbResponse,
    PlaybackChildResponse,
    _render_complexity_response,
)
from app.services.instruction_playback import (
    PlaybackData,
    RenderComplexityLimits,
    playback_breadcrumbs,
    select_render_strategy,
)
from app.services.ldraw_aliases import OfficialPartRecord, cached_moved_alias_resolver
from app.services.ldraw_library import get_library_status
from app.services.ldraw_pack import LDrawPackError, LDrawPackLimitError, PackedLDrawSource
from app.services.local_workspace import resolve_local_workspace
from app.services.model_coverage import (
    CoverageRequirement,
    InventoryQuantity,
    calculate_model_coverage,
    normalize_part_id,
)

LOGGER = logging.getLogger(__name__)

SceneIdentity = Callable[[ImportedModel, str, str], str]
PackedSceneFor = Callable[
    [ImportedModel, PlaybackData, str, Literal["subtree", "local"]],
    tuple[str, PackedLDrawSource],
]
InventoryForRequirements = Callable[
    [Session, int, "list[CoverageRequirement]"], "list[InventoryQuantity]"
]


def assemble_build_manifest(
    session: Session,
    model: ImportedModel,
    data: PlaybackData,
    occurrence_id: str,
    *,
    library_root: Path,
    render_limits: RenderComplexityLimits,
    scene_identity: SceneIdentity,
    packed_scene_for: PackedSceneFor,
    inventory_for_requirements: InventoryForRequirements,
) -> BuildManifestResponse:
    occurrence = data.occurrence_by_id[occurrence_id]
    definition = data.definition_by_name[occurrence.source_submodel_name.replace("\\", "/").lower()]
    selection = select_render_strategy(data, occurrence_id, render_limits)
    render_strategy = selection.recommended_strategy
    nodes = data.nodes_by_occurrence.get(occurrence_id, ())

    def source_part_id(filename: str) -> str:
        name = PurePosixPath(filename.replace("\\", "/")).name
        return name[:-4].lower() if name.lower().endswith(".dat") else name.lower()

    part_nodes = [node for node in nodes if node.kind == "part_reference"]
    source_part_ids = sorted({source_part_id(node.source_filename) for node in part_nodes})
    color_codes = sorted(
        {node.effective_color for node in part_nodes if node.effective_color is not None}
    )
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

    alias_resolver = cached_moved_alias_resolver(library_root, fingerprint, load_official_records)
    alias_resolutions = alias_resolver.resolve_many(set(source_part_ids))
    canonical_by_source = {
        source_id: (resolution.canonical_part_id if resolution.status == "resolved" else source_id)
        for source_id, resolution in alias_resolutions.items()
    }
    referenced_part_ids = sorted(
        {normalize_part_id(part_id) for part_id in source_part_ids}
        | {normalize_part_id(part_id) for part_id in canonical_by_source.values()}
    )
    catalog_parts = (
        {
            normalize_part_id(part.part_id): part
            for part in session.scalars(
                select(Part).where(func.lower(Part.part_id).in_(referenced_part_ids))
            )
        }
        if referenced_part_ids
        else {}
    )
    colors = {
        color.code: color
        for color in session.scalars(select(LDrawColor).where(LDrawColor.code.in_(color_codes)))
    }

    bom_rows = list(session.scalars(select(ModelBomItem).where(ModelBomItem.model_id == model.id)))
    requirements = [
        CoverageRequirement(item.part_id, item.color_code, item.quantity) for item in bom_rows
    ]
    workspace = resolve_local_workspace(session)
    coverage = calculate_model_coverage(
        requirements,
        inventory_for_requirements(session, workspace.id, requirements),
    )
    coverage_by_key = {
        (normalize_part_id(item.part_id), item.color_code): item for item in coverage.items
    }
    inventory_keys = sorted(
        {
            (candidate, node.effective_color)
            for node in part_nodes
            if node.effective_color is not None
            for source_id in (source_part_id(node.source_filename),)
            for candidate in {
                normalize_part_id(source_id),
                normalize_part_id(canonical_by_source.get(source_id, source_id)),
            }
        }
    )
    raw_inventory = (
        {
            (normalize_part_id(part_id), color_code): quantity
            for part_id, color_code, quantity in session.execute(
                select(
                    InventoryItem.part_id,
                    InventoryItem.color_code,
                    InventoryItem.quantity,
                ).where(
                    InventoryItem.workspace_id == workspace.id,
                    tuple_(
                        func.lower(func.trim(InventoryItem.part_id)),
                        InventoryItem.color_code,
                    ).in_(inventory_keys),
                )
            )
        }
        if inventory_keys
        else {}
    )

    children_by_step: dict[int, list[PlaybackChildResponse]] = {}
    for child_id in occurrence.child_occurrence_ids:
        child = data.occurrence_by_id[child_id]
        if child.attachment_step is None:
            continue
        children_by_step.setdefault(child.attachment_step, []).append(
            PlaybackChildResponse(
                occurrence_id=child.occurrence_id,
                source_submodel_name=child.source_submodel_name,
                attachment_step=child.attachment_step,
                traversal_order=child.traversal_order,
                repeated_definition_count=data.repeated_definition_counts[
                    child.source_submodel_name.replace("\\", "/").lower()
                ],
                repeated_definition_index=data.repeated_definition_indices[child.occurrence_id],
            )
        )

    steps: list[BuildStepResponse] = []
    for local_step in definition.local_steps:
        grouped: dict[tuple[str, int | None], list[str]] = {}
        for node in part_nodes:
            if node.local_step != local_step.step:
                continue
            key = (source_part_id(node.source_filename), node.effective_color)
            grouped.setdefault(key, []).append(node.instruction_node_id)
        response_parts: list[BuildStepPartResponse] = []
        for (part_id, color_code), node_ids in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1] or -1)
        ):
            canonical_part_id = canonical_by_source.get(part_id, part_id)
            part = catalog_parts.get(normalize_part_id(canonical_part_id))
            color = colors.get(color_code) if color_code is not None else None
            coverage_item = (
                coverage_by_key.get((normalize_part_id(canonical_part_id), color_code))
                if color_code is not None
                else None
            )
            owned = (
                coverage_item.owned_quantity
                if coverage_item is not None
                else raw_inventory.get((normalize_part_id(part_id), color_code), 0)
            )
            required = (
                coverage_item.required_quantity if coverage_item is not None else len(node_ids)
            )
            missing = (
                coverage_item.missing_quantity
                if coverage_item is not None
                else max(required - owned, 0)
            )
            response_parts.append(
                BuildStepPartResponse(
                    source_part_id=part_id,
                    part_id=(
                        coverage_item.part_id if coverage_item is not None else canonical_part_id
                    ),
                    alias_applied=(
                        normalize_part_id(canonical_part_id) != normalize_part_id(part_id)
                    ),
                    instruction_node_ids=node_ids,
                    part_name=part.name if part is not None else part_id,
                    color_code=color_code,
                    color_name=(
                        color.name
                        if color is not None
                        else "Inherited colour"
                        if color_code is None
                        else f"Color {color_code}"
                    ),
                    color_hex=color.value_hex if color is not None else None,
                    quantity_this_step=len(node_ids),
                    owned_quantity=owned,
                    model_required_quantity=required,
                    model_missing_quantity=missing,
                    catalog_available=part is not None and not part.is_subpart,
                )
            )
        steps.append(
            BuildStepResponse(
                step=local_step.step,
                parts=response_parts,
                direct_geometry_command_count=len(local_step.direct_geometry),
                attachments=children_by_step.get(local_step.step, []),
            )
        )

    encoded_occurrence = quote(occurrence_id, safe="")
    cache_key = scene_identity(model, occurrence_id, render_strategy)
    delivery: Literal["packed", "external"] = "external"
    try:
        cache_key, _packed = packed_scene_for(model, data, occurrence_id, render_strategy)
        delivery = "packed"
    except LDrawPackError, LDrawPackLimitError:
        LOGGER.info(
            "Packed scene unavailable for model %s occurrence %s; using external assets",
            model.public_id,
            occurrence_id,
        )
    scene_url = (
        f"/api/models/{quote(str(model.public_id), safe='')}/"
        f"instruction-occurrences/{encoded_occurrence}/source"
        f"?mode={render_strategy}&delivery={delivery}&v={cache_key}"
    )
    return BuildManifestResponse(
        model_id=model.public_id,
        model_name=model.name,
        occurrence_id=occurrence.occurrence_id,
        parent_occurrence_id=occurrence.parent_occurrence_id,
        source_submodel_name=occurrence.source_submodel_name,
        attachment_step=occurrence.attachment_step,
        breadcrumbs=[
            PlaybackBreadcrumbResponse(
                occurrence_id=item.occurrence_id,
                source_submodel_name=item.source_submodel_name,
            )
            for item in playback_breadcrumbs(data, occurrence_id)
        ],
        repeated_definition_count=data.repeated_definition_counts[
            occurrence.source_submodel_name.replace("\\", "/").lower()
        ],
        repeated_definition_index=data.repeated_definition_indices[occurrence_id],
        scene=BuildSceneResponse(
            url=scene_url,
            cache_key=cache_key,
            render_strategy=render_strategy,
            delivery=delivery,
            complexity=_render_complexity_response(selection.complexity),
        ),
        steps=steps,
    )
