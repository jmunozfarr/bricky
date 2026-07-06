from __future__ import annotations

import uuid
from typing import Literal

from app.schemas import CamelModel
from app.services.instruction_graph import InstructionGraph, InstructionGraphLimits
from app.services.instruction_playback import RenderComplexity


class InstructionTransformResponse(CamelModel):
    translation: tuple[float, float, float]
    matrix: tuple[float, float, float, float, float, float, float, float, float]


class LocalInstructionNodeResponse(CamelModel):
    node_index: int
    kind: Literal["part_reference", "submodel_reference"]
    source_filename: str
    color_code: int
    local_transform: InstructionTransformResponse
    source_order: int


class LocalDirectGeometryResponse(CamelModel):
    command_type: Literal[2, 3, 4, 5]
    color_token: str
    coordinates: tuple[float, ...]
    local_step: int
    source_order: int
    source_submodel_name: str


class LocalStepDefinitionResponse(CamelModel):
    step: int
    nodes: list[LocalInstructionNodeResponse]
    direct_geometry: list[LocalDirectGeometryResponse]


class ModelDefinitionResponse(CamelModel):
    source_submodel_name: str
    local_steps: list[LocalStepDefinitionResponse]


class ModelOccurrenceResponse(CamelModel):
    occurrence_id: str
    parent_occurrence_id: str | None
    source_submodel_name: str
    local_transform: InstructionTransformResponse
    effective_color: int | None
    attachment_step: int | None
    depth: int
    traversal_order: int
    child_occurrence_ids: list[str]


class ExpandedInstructionNodeResponse(CamelModel):
    instruction_node_id: str
    occurrence_id: str
    local_step: int
    node_index: int
    kind: Literal["part_reference", "submodel_attachment"]
    source_filename: str
    effective_color: int | None
    local_transform: InstructionTransformResponse
    child_occurrence_id: str | None
    source_order: int


class InstructionGraphIssueResponse(CamelModel):
    severity: str
    code: str
    message: str
    source_submodel_name: str | None
    source_filename: str | None
    occurrence_id: str | None
    configured_limit: int | None


class InstructionGraphLimitsResponse(CamelModel):
    maximum_nesting_depth: int
    maximum_expanded_occurrences: int
    maximum_instruction_nodes: int


class InstructionGraphResponse(CamelModel):
    model_id: uuid.UUID
    root_occurrence_id: str
    model_definitions: list[ModelDefinitionResponse]
    occurrences: list[ModelOccurrenceResponse]
    instruction_nodes: list[ExpandedInstructionNodeResponse]
    maximum_nesting_depth: int
    traversal_order: list[str]
    model_definition_count: int
    expanded_occurrence_count: int
    instruction_node_count: int
    issues: list[InstructionGraphIssueResponse]
    truncated: bool
    limits: InstructionGraphLimitsResponse


class InstructionPlaybackIssueResponse(CamelModel):
    code: str
    message: str


class InstructionPlaybackSummaryResponse(CamelModel):
    model_id: uuid.UUID
    available: bool
    root_occurrence_id: str | None
    fallback_reason: str | None
    issues: list[InstructionPlaybackIssueResponse]
    recommended_render_strategy: Literal["subtree", "local"] | None
    render_strategy_reason: str
    complexity: RenderComplexityResponse | None
    flattened_rendering_allowed: bool


class RenderComplexityResponse(CamelModel):
    expanded_instruction_node_count: int
    expanded_occurrence_count: int
    direct_geometry_command_count: int
    estimated_derived_source_bytes: int


class PlaybackBreadcrumbResponse(CamelModel):
    occurrence_id: str
    source_submodel_name: str


class PlaybackChildResponse(CamelModel):
    occurrence_id: str
    source_submodel_name: str
    attachment_step: int
    traversal_order: int
    repeated_definition_count: int
    repeated_definition_index: int


class PlaybackStepSummaryResponse(CamelModel):
    step: int
    local_part_count: int
    child_attachment_count: int
    direct_geometry_command_count: int


class InstructionPlaybackOccurrenceResponse(CamelModel):
    model_id: uuid.UUID
    occurrence_id: str
    parent_occurrence_id: str | None
    source_submodel_name: str
    attachment_step: int | None
    depth: int
    traversal_order: int
    breadcrumbs: list[PlaybackBreadcrumbResponse]
    local_step_count: int
    current_step: int
    previous_step: int | None
    next_step: int | None
    complete: bool
    empty: bool
    repeated_definition_count: int
    repeated_definition_index: int
    step_summary: PlaybackStepSummaryResponse
    children: list[PlaybackChildResponse]
    child_total: int
    child_offset: int
    child_limit: int
    scene_source_url: str
    render_strategy: Literal["subtree", "local"]
    recommended_render_strategy: Literal["subtree", "local"]
    render_strategy_reason: str
    complexity: RenderComplexityResponse


class BuildSceneResponse(CamelModel):
    url: str
    cache_key: str
    render_strategy: Literal["subtree", "local"]
    delivery: Literal["packed", "external"]
    complexity: RenderComplexityResponse


class BuildStepPartResponse(CamelModel):
    source_part_id: str
    part_id: str
    alias_applied: bool
    instruction_node_ids: list[str]
    part_name: str
    color_code: int | None
    color_name: str
    color_hex: str | None
    quantity_this_step: int
    owned_quantity: int
    model_required_quantity: int
    model_missing_quantity: int
    catalog_available: bool


class BuildStepResponse(CamelModel):
    step: int
    parts: list[BuildStepPartResponse]
    direct_geometry_command_count: int
    attachments: list[PlaybackChildResponse]


class BuildManifestResponse(CamelModel):
    model_id: uuid.UUID
    model_name: str
    occurrence_id: str
    parent_occurrence_id: str | None
    source_submodel_name: str
    attachment_step: int | None
    breadcrumbs: list[PlaybackBreadcrumbResponse]
    repeated_definition_count: int
    repeated_definition_index: int
    scene: BuildSceneResponse
    steps: list[BuildStepResponse]


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
