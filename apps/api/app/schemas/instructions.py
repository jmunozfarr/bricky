from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.instruction_graph import InstructionGraph, InstructionGraphLimits
from app.services.instruction_playback import RenderComplexity


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
    complexity: RenderComplexityResponse | None
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


class BuildSceneResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    url: str
    cache_key: str = Field(alias="cacheKey")
    render_strategy: Literal["subtree", "local"] = Field(alias="renderStrategy")
    delivery: Literal["packed", "external"]
    complexity: RenderComplexityResponse


class BuildStepPartResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_part_id: str = Field(alias="sourcePartId")
    part_id: str = Field(alias="partId")
    alias_applied: bool = Field(alias="aliasApplied")
    instruction_node_ids: list[str] = Field(alias="instructionNodeIds")
    part_name: str = Field(alias="partName")
    color_code: int | None = Field(alias="colorCode")
    color_name: str = Field(alias="colorName")
    color_hex: str | None = Field(alias="colorHex")
    quantity_this_step: int = Field(alias="quantityThisStep")
    owned_quantity: int = Field(alias="ownedQuantity")
    model_required_quantity: int = Field(alias="modelRequiredQuantity")
    model_missing_quantity: int = Field(alias="modelMissingQuantity")
    catalog_available: bool = Field(alias="catalogAvailable")


class BuildStepResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    step: int
    parts: list[BuildStepPartResponse]
    direct_geometry_command_count: int = Field(alias="directGeometryCommandCount")
    attachments: list[PlaybackChildResponse]


class BuildManifestResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_id: uuid.UUID = Field(alias="modelId")
    model_name: str = Field(alias="modelName")
    occurrence_id: str = Field(alias="occurrenceId")
    parent_occurrence_id: str | None = Field(alias="parentOccurrenceId")
    source_submodel_name: str = Field(alias="sourceSubmodelName")
    attachment_step: int | None = Field(alias="attachmentStep")
    breadcrumbs: list[PlaybackBreadcrumbResponse]
    repeated_definition_count: int = Field(alias="repeatedDefinitionCount")
    repeated_definition_index: int = Field(alias="repeatedDefinitionIndex")
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
