from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from app.services.ldraw_model_parser import (
    _STEP_DIRECTIVE,
    _normalize_reference,
    _split_sections,
    decode_model_source,
)


DEFAULT_MAX_NESTING_DEPTH = 32
DEFAULT_MAX_EXPANDED_OCCURRENCES = 10_000
DEFAULT_MAX_INSTRUCTION_NODES = 100_000


@dataclass(frozen=True)
class InstructionGraphLimits:
    max_nesting_depth: int = DEFAULT_MAX_NESTING_DEPTH
    max_expanded_occurrences: int = DEFAULT_MAX_EXPANDED_OCCURRENCES
    max_instruction_nodes: int = DEFAULT_MAX_INSTRUCTION_NODES

    def __post_init__(self) -> None:
        if self.max_nesting_depth < 0:
            raise ValueError("Maximum nesting depth cannot be negative")
        if self.max_expanded_occurrences < 1:
            raise ValueError("Maximum expanded occurrences must be positive")
        if self.max_instruction_nodes < 1:
            raise ValueError("Maximum instruction nodes must be positive")


@dataclass(frozen=True)
class LocalTransform:
    translation: tuple[float, float, float]
    matrix: tuple[float, float, float, float, float, float, float, float, float]


IDENTITY_TRANSFORM = LocalTransform(
    translation=(0.0, 0.0, 0.0),
    matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
)


@dataclass(frozen=True)
class LocalInstructionNode:
    node_index: int
    kind: Literal["part_reference", "submodel_reference"]
    source_filename: str
    color_code: int
    local_transform: LocalTransform


@dataclass(frozen=True)
class LocalStepDefinition:
    step: int
    nodes: tuple[LocalInstructionNode, ...]


@dataclass(frozen=True)
class ModelDefinition:
    source_submodel_name: str
    local_steps: tuple[LocalStepDefinition, ...]


@dataclass(frozen=True)
class ModelOccurrence:
    occurrence_id: str
    parent_occurrence_id: str | None
    source_submodel_name: str
    local_transform: LocalTransform
    effective_color: int | None
    attachment_step: int | None
    depth: int
    traversal_order: int
    child_occurrence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExpandedInstructionNode:
    instruction_node_id: str
    occurrence_id: str
    local_step: int
    node_index: int
    kind: Literal["part_reference", "submodel_attachment"]
    source_filename: str
    effective_color: int | None
    local_transform: LocalTransform
    child_occurrence_id: str | None


@dataclass(frozen=True)
class InstructionGraphIssue:
    severity: Literal["warning"]
    code: str
    message: str
    source_submodel_name: str | None = None
    source_filename: str | None = None
    occurrence_id: str | None = None
    configured_limit: int | None = None


@dataclass(frozen=True)
class InstructionGraph:
    root_occurrence_id: str
    model_definitions: tuple[ModelDefinition, ...]
    occurrences: tuple[ModelOccurrence, ...]
    instruction_nodes: tuple[ExpandedInstructionNode, ...]
    maximum_nesting_depth: int
    traversal_order: tuple[str, ...]
    issues: tuple[InstructionGraphIssue, ...]
    truncated: bool


@dataclass(frozen=True)
class _SourceNode:
    step: int
    node_index: int
    kind: Literal["part_reference", "submodel_reference"]
    source_filename: str
    normalized_filename: str | None
    color_code: int
    local_transform: LocalTransform


@dataclass(frozen=True)
class _SourceDefinition:
    key: str
    source_name: str
    steps: tuple[LocalStepDefinition, ...]
    nodes: tuple[_SourceNode, ...]


@dataclass
class _OccurrenceBuilder:
    occurrence_id: str
    parent_occurrence_id: str | None
    definition_key: str
    source_name: str
    local_transform: LocalTransform
    effective_color: int | None
    attachment_step: int | None
    depth: int
    traversal_order: int
    child_occurrence_ids: list[str] = field(default_factory=list)


@dataclass
class _TraversalFrame:
    occurrence: _OccurrenceBuilder
    ancestry: tuple[str, ...]
    next_node_index: int = 0


def _parse_type_one(line: str) -> tuple[int, LocalTransform, str]:
    tokens = line.split()
    if len(tokens) < 15 or tokens[0] != "1":
        raise ValueError("malformed type-1 reference")
    color_code = int(tokens[1])
    values = tuple(float(token) for token in tokens[2:14])
    if len(values) != 12 or not all(math.isfinite(value) for value in values):
        raise ValueError("type-1 numeric fields must be finite")
    filename = " ".join(tokens[14:]).strip()
    if not filename:
        raise ValueError("type-1 filename is missing")
    return (
        color_code,
        LocalTransform(
            translation=(values[0], values[1], values[2]),
            matrix=(
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
                values[8],
                values[9],
                values[10],
                values[11],
            ),
        ),
        filename,
    )


def _effective_color(color_code: int, inherited_color: int | None) -> int | None:
    return inherited_color if color_code == 16 else color_code


def parse_instruction_graph(
    content: bytes,
    *,
    source_name: str = "model.ldr",
    limits: InstructionGraphLimits | None = None,
) -> InstructionGraph:
    """Build a bounded source-definition and expanded-occurrence graph.

    This parser is deliberately independent from BOM/catalog resolution. It recognizes
    MPD FILE sections, type-1 references, and STEP/ROTSTEP boundaries only.
    """

    active_limits = limits or InstructionGraphLimits()
    text, _encoding = decode_model_source(content)
    sections, main_key, main_name = _split_sections(text)
    issues: list[InstructionGraphIssue] = []
    issue_keys: set[tuple[str, str | None, str | None, str | None]] = set()

    def add_issue(
        code: str,
        message: str,
        *,
        source_model: str | None = None,
        filename: str | None = None,
        occurrence_id: str | None = None,
        configured_limit: int | None = None,
    ) -> None:
        key = (code, source_model, filename, occurrence_id)
        if key in issue_keys:
            return
        issue_keys.add(key)
        issues.append(
            InstructionGraphIssue(
                severity="warning",
                code=code,
                message=message,
                source_submodel_name=source_model,
                source_filename=filename,
                occurrence_id=occurrence_id,
                configured_limit=configured_limit,
            )
        )

    definitions: dict[str, _SourceDefinition] = {}
    public_definitions: list[ModelDefinition] = []
    for section_key, section in sections.items():
        section_name = section.name or source_name
        step = 1
        nodes_in_step = 0
        source_nodes: list[_SourceNode] = []
        steps: list[list[LocalInstructionNode]] = [[]]
        for line in section.lines:
            stripped = line.strip()
            if _STEP_DIRECTIVE.match(stripped):
                step += 1
                nodes_in_step = 0
                steps.append([])
                continue
            if not stripped or stripped.split(maxsplit=1)[0] != "1":
                continue
            try:
                color_code, transform, filename = _parse_type_one(stripped)
            except (ValueError, OverflowError):
                add_issue(
                    "malformed_type1_reference",
                    "Malformed type-1 reference was excluded from the instruction graph",
                    source_model=section_name,
                )
                continue
            normalized = _normalize_reference(filename)
            kind: Literal["part_reference", "submodel_reference"] = (
                "submodel_reference"
                if normalized is not None and normalized in sections
                else "part_reference"
            )
            nodes_in_step += 1
            public_node = LocalInstructionNode(
                node_index=nodes_in_step,
                kind=kind,
                source_filename=normalized or filename,
                color_code=color_code,
                local_transform=transform,
            )
            steps[-1].append(public_node)
            source_nodes.append(
                _SourceNode(
                    step=step,
                    node_index=nodes_in_step,
                    kind=kind,
                    source_filename=normalized or filename,
                    normalized_filename=normalized,
                    color_code=color_code,
                    local_transform=transform,
                )
            )
        local_steps = tuple(
            LocalStepDefinition(step=index, nodes=tuple(step_nodes))
            for index, step_nodes in enumerate(steps, start=1)
        )
        definition = _SourceDefinition(
            key=section_key,
            source_name=section_name,
            steps=local_steps,
            nodes=tuple(source_nodes),
        )
        definitions[section_key] = definition
        public_definitions.append(
            ModelDefinition(source_submodel_name=section_name, local_steps=local_steps)
        )

    root_definition = definitions[main_key]
    root = _OccurrenceBuilder(
        occurrence_id="occ-000001",
        parent_occurrence_id=None,
        definition_key=main_key,
        source_name=main_name or source_name,
        local_transform=IDENTITY_TRANSFORM,
        effective_color=None,
        attachment_step=None,
        depth=0,
        traversal_order=1,
    )
    occurrences: list[_OccurrenceBuilder] = [root]
    expanded_nodes: list[ExpandedInstructionNode] = []
    frames = [_TraversalFrame(occurrence=root, ancestry=(main_key,))]
    truncated = False

    while frames:
        frame = frames[-1]
        definition = definitions[frame.occurrence.definition_key]
        if frame.next_node_index >= len(definition.nodes):
            frames.pop()
            continue
        if len(expanded_nodes) >= active_limits.max_instruction_nodes:
            add_issue(
                "instruction_node_limit_exceeded",
                "Instruction graph expansion stopped at the configured node limit",
                source_model=frame.occurrence.source_name,
                occurrence_id=frame.occurrence.occurrence_id,
                configured_limit=active_limits.max_instruction_nodes,
            )
            truncated = True
            break

        source_node = definition.nodes[frame.next_node_index]
        frame.next_node_index += 1
        node_color = _effective_color(
            source_node.color_code, frame.occurrence.effective_color
        )
        child_id: str | None = None
        child_frame: _TraversalFrame | None = None

        if (
            source_node.kind == "submodel_reference"
            and source_node.normalized_filename is not None
        ):
            child_key = source_node.normalized_filename
            child_depth = frame.occurrence.depth + 1
            if child_key in frame.ancestry:
                add_issue(
                    "recursive_submodel_cycle",
                    "Recursive MPD submodel cycle was stopped at the attachment",
                    source_model=frame.occurrence.source_name,
                    filename=source_node.source_filename,
                    occurrence_id=frame.occurrence.occurrence_id,
                )
                truncated = True
            elif child_depth > active_limits.max_nesting_depth:
                add_issue(
                    "nesting_depth_limit_exceeded",
                    "Submodel expansion stopped at the configured nesting depth",
                    source_model=frame.occurrence.source_name,
                    filename=source_node.source_filename,
                    occurrence_id=frame.occurrence.occurrence_id,
                    configured_limit=active_limits.max_nesting_depth,
                )
                truncated = True
            elif len(occurrences) >= active_limits.max_expanded_occurrences:
                add_issue(
                    "expanded_occurrence_limit_exceeded",
                    "Submodel expansion stopped at the configured occurrence limit",
                    source_model=frame.occurrence.source_name,
                    filename=source_node.source_filename,
                    occurrence_id=frame.occurrence.occurrence_id,
                    configured_limit=active_limits.max_expanded_occurrences,
                )
                truncated = True
            else:
                child_definition = definitions[child_key]
                child_id = f"occ-{len(occurrences) + 1:06d}"
                child = _OccurrenceBuilder(
                    occurrence_id=child_id,
                    parent_occurrence_id=frame.occurrence.occurrence_id,
                    definition_key=child_key,
                    source_name=child_definition.source_name,
                    local_transform=source_node.local_transform,
                    effective_color=node_color,
                    attachment_step=source_node.step,
                    depth=child_depth,
                    traversal_order=len(occurrences) + 1,
                )
                occurrences.append(child)
                frame.occurrence.child_occurrence_ids.append(child_id)
                child_frame = _TraversalFrame(
                    occurrence=child,
                    ancestry=(*frame.ancestry, child_key),
                )

        expanded_nodes.append(
            ExpandedInstructionNode(
                instruction_node_id=f"node-{len(expanded_nodes) + 1:06d}",
                occurrence_id=frame.occurrence.occurrence_id,
                local_step=source_node.step,
                node_index=source_node.node_index,
                kind=(
                    "submodel_attachment"
                    if source_node.kind == "submodel_reference"
                    else "part_reference"
                ),
                source_filename=source_node.source_filename,
                effective_color=node_color,
                local_transform=source_node.local_transform,
                child_occurrence_id=child_id,
            )
        )
        if child_frame is not None:
            frames.append(child_frame)

    frozen_occurrences = tuple(
        ModelOccurrence(
            occurrence_id=occurrence.occurrence_id,
            parent_occurrence_id=occurrence.parent_occurrence_id,
            source_submodel_name=occurrence.source_name,
            local_transform=occurrence.local_transform,
            effective_color=occurrence.effective_color,
            attachment_step=occurrence.attachment_step,
            depth=occurrence.depth,
            traversal_order=occurrence.traversal_order,
            child_occurrence_ids=tuple(occurrence.child_occurrence_ids),
        )
        for occurrence in occurrences
    )
    return InstructionGraph(
        root_occurrence_id=root.occurrence_id,
        model_definitions=tuple(public_definitions),
        occurrences=frozen_occurrences,
        instruction_nodes=tuple(expanded_nodes),
        maximum_nesting_depth=max(
            (occurrence.depth for occurrence in frozen_occurrences), default=0
        ),
        traversal_order=tuple(
            occurrence.occurrence_id for occurrence in frozen_occurrences
        ),
        issues=tuple(issues),
        truncated=truncated,
    )
