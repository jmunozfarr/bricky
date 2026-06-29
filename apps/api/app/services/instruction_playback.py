from __future__ import annotations

import base64
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache

from app.services.instruction_graph import (
    ExpandedInstructionNode,
    IDENTITY_TRANSFORM,
    InstructionGraph,
    InstructionGraphIssue,
    InstructionGraphLimits,
    LocalTransform,
    ModelDefinition,
    ModelOccurrence,
    parse_instruction_graph,
)
from app.services.ldraw_model_parser import _normalize_reference


PLAYBACK_CHILD_PAGE_SIZE = 50
PLAYBACK_CHILD_PAGE_SIZE_MAXIMUM = 100
DERIVED_SOURCE_FORMAT_VERSION = 1


@dataclass(frozen=True)
class PlaybackIssue:
    code: str
    message: str


@dataclass(frozen=True)
class PlaybackBreadcrumb:
    occurrence_id: str
    source_submodel_name: str


@dataclass(frozen=True)
class PlaybackChild:
    occurrence_id: str
    source_submodel_name: str
    attachment_step: int
    traversal_order: int
    repeated_definition_count: int
    repeated_definition_index: int


@dataclass(frozen=True)
class PlaybackStepSummary:
    step: int
    local_part_count: int
    child_attachment_count: int


@dataclass(frozen=True)
class PlaybackOccurrence:
    occurrence: ModelOccurrence
    breadcrumbs: tuple[PlaybackBreadcrumb, ...]
    local_step_count: int
    current_step: int
    previous_step: int | None
    next_step: int | None
    complete: bool
    empty: bool
    repeated_definition_count: int
    repeated_definition_index: int
    step_summary: PlaybackStepSummary
    children: tuple[PlaybackChild, ...]
    child_total: int
    child_offset: int
    child_limit: int


@dataclass(frozen=True)
class PlaybackData:
    graph: InstructionGraph
    available: bool
    issues: tuple[PlaybackIssue, ...]
    occurrence_by_id: dict[str, ModelOccurrence]
    definition_by_name: dict[str, ModelDefinition]
    nodes_by_occurrence: dict[str, tuple[ExpandedInstructionNode, ...]]
    repeated_definition_counts: dict[str, int]
    repeated_definition_indices: dict[str, int]


def _definition_key(name: str) -> str:
    return name.replace("\\", "/").lower()


def _playback_issue(issue: InstructionGraphIssue) -> PlaybackIssue:
    return PlaybackIssue(code=issue.code, message=issue.message)


def build_playback_data(graph: InstructionGraph) -> PlaybackData:
    occurrence_by_id = {
        occurrence.occurrence_id: occurrence for occurrence in graph.occurrences
    }
    definition_by_name = {
        _definition_key(definition.source_submodel_name): definition
        for definition in graph.model_definitions
    }
    mutable_nodes: defaultdict[str, list[ExpandedInstructionNode]] = defaultdict(list)
    for node in graph.instruction_nodes:
        mutable_nodes[node.occurrence_id].append(node)
    nodes_by_occurrence = {
        occurrence_id: tuple(nodes) for occurrence_id, nodes in mutable_nodes.items()
    }

    definition_counts = Counter(
        _definition_key(occurrence.source_submodel_name)
        for occurrence in graph.occurrences
    )
    seen: Counter[str] = Counter()
    repeated_indices: dict[str, int] = {}
    for occurrence in graph.occurrences:
        key = _definition_key(occurrence.source_submodel_name)
        seen[key] += 1
        repeated_indices[occurrence.occurrence_id] = seen[key]

    issues = [_playback_issue(issue) for issue in graph.issues]
    for node in graph.instruction_nodes:
        if _normalize_reference(node.source_filename) is None:
            issues.append(
                PlaybackIssue(
                    code="unsafe_render_reference",
                    message="Hierarchical playback rejected an unsafe render reference",
                )
            )
            break

    return PlaybackData(
        graph=graph,
        available=not graph.truncated and not issues,
        issues=tuple(issues),
        occurrence_by_id=occurrence_by_id,
        definition_by_name=definition_by_name,
        nodes_by_occurrence=nodes_by_occurrence,
        repeated_definition_counts=dict(definition_counts),
        repeated_definition_indices=repeated_indices,
    )


@lru_cache(maxsize=8)
def parse_playback_data(
    source_sha256: str,
    content: bytes,
    source_name: str,
    limits: InstructionGraphLimits,
) -> PlaybackData:
    """Cache immutable parsed playback data by the imported source identity."""

    del source_sha256
    return build_playback_data(
        parse_instruction_graph(content, source_name=source_name, limits=limits)
    )


def clear_playback_cache() -> None:
    parse_playback_data.cache_clear()


def playback_breadcrumbs(
    data: PlaybackData, occurrence_id: str
) -> tuple[PlaybackBreadcrumb, ...]:
    occurrence = data.occurrence_by_id.get(occurrence_id)
    if occurrence is None:
        raise KeyError(occurrence_id)
    reversed_items: list[PlaybackBreadcrumb] = []
    current: ModelOccurrence | None = occurrence
    while current is not None:
        reversed_items.append(
            PlaybackBreadcrumb(
                occurrence_id=current.occurrence_id,
                source_submodel_name=current.source_submodel_name,
            )
        )
        current = (
            data.occurrence_by_id.get(current.parent_occurrence_id)
            if current.parent_occurrence_id is not None
            else None
        )
    return tuple(reversed(reversed_items))


def playback_occurrence(
    data: PlaybackData,
    occurrence_id: str,
    *,
    current_step: int,
    child_offset: int = 0,
    child_limit: int = PLAYBACK_CHILD_PAGE_SIZE,
) -> PlaybackOccurrence:
    occurrence = data.occurrence_by_id.get(occurrence_id)
    if occurrence is None:
        raise KeyError(occurrence_id)
    definition = data.definition_by_name[_definition_key(occurrence.source_submodel_name)]
    step_count = len(definition.local_steps)
    if current_step < 1 or current_step > step_count:
        raise ValueError(f"Step must be between 1 and {step_count}")
    if child_offset < 0:
        raise ValueError("Child offset cannot be negative")
    if child_limit < 1 or child_limit > PLAYBACK_CHILD_PAGE_SIZE_MAXIMUM:
        raise ValueError(
            f"Child limit must be between 1 and {PLAYBACK_CHILD_PAGE_SIZE_MAXIMUM}"
        )

    nodes = data.nodes_by_occurrence.get(occurrence_id, ())
    step_nodes = tuple(node for node in nodes if node.local_step == current_step)
    children_at_step = [
        data.occurrence_by_id[child_id]
        for child_id in occurrence.child_occurrence_ids
        if data.occurrence_by_id[child_id].attachment_step == current_step
    ]
    children = tuple(
        PlaybackChild(
            occurrence_id=child.occurrence_id,
            source_submodel_name=child.source_submodel_name,
            attachment_step=child.attachment_step or current_step,
            traversal_order=child.traversal_order,
            repeated_definition_count=data.repeated_definition_counts[
                _definition_key(child.source_submodel_name)
            ],
            repeated_definition_index=data.repeated_definition_indices[
                child.occurrence_id
            ],
        )
        for child in children_at_step[child_offset : child_offset + child_limit]
    )
    return PlaybackOccurrence(
        occurrence=occurrence,
        breadcrumbs=playback_breadcrumbs(data, occurrence_id),
        local_step_count=step_count,
        current_step=current_step,
        previous_step=current_step - 1 if current_step > 1 else None,
        next_step=current_step + 1 if current_step < step_count else None,
        complete=current_step == step_count,
        empty=not nodes,
        repeated_definition_count=data.repeated_definition_counts[
            _definition_key(occurrence.source_submodel_name)
        ],
        repeated_definition_index=data.repeated_definition_indices[occurrence_id],
        step_summary=PlaybackStepSummary(
            step=current_step,
            local_part_count=sum(
                node.kind == "part_reference" for node in step_nodes
            ),
            child_attachment_count=len(children_at_step),
        ),
        children=children,
        child_total=len(children_at_step),
        child_offset=child_offset,
        child_limit=child_limit,
    )


def _format_number(value: float) -> str:
    return "0" if value == 0 else format(value, ".15g")


def _type_one_line(
    color: int | None, transform: LocalTransform, filename: str
) -> str:
    normalized = _normalize_reference(filename)
    if normalized is None:
        raise ValueError("Unsafe reference cannot be included in derived source")
    values = (*transform.translation, *transform.matrix)
    return " ".join(
        ("1", str(color if color is not None else 16))
        + tuple(_format_number(value) for value in values)
        + (normalized,)
    )


def _occurrence_filename(occurrence_id: str) -> str:
    return f"__bricky_{occurrence_id.replace('-', '_')}.ldr"


def _node_filename(instruction_node_id: str) -> str:
    return f"__bricky_{instruction_node_id.replace('-', '_')}.ldr"


def _encoded_name(name: str) -> str:
    return base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")


def _subtree_occurrences(
    data: PlaybackData, root_occurrence_id: str
) -> tuple[ModelOccurrence, ...]:
    root = data.occurrence_by_id.get(root_occurrence_id)
    if root is None:
        raise KeyError(root_occurrence_id)
    result: list[ModelOccurrence] = []
    stack = [root]
    while stack:
        occurrence = stack.pop()
        result.append(occurrence)
        stack.extend(
            reversed(
                [
                    data.occurrence_by_id[child_id]
                    for child_id in occurrence.child_occurrence_ids
                ]
            )
        )
    return tuple(result)


def derive_occurrence_source(data: PlaybackData, occurrence_id: str) -> bytes:
    if not data.available:
        raise ValueError("Instruction graph is not valid for hierarchical playback")
    occurrences = _subtree_occurrences(data, occurrence_id)
    occurrence_ids = {occurrence.occurrence_id for occurrence in occurrences}
    nodes = tuple(
        node
        for node in data.graph.instruction_nodes
        if node.occurrence_id in occurrence_ids
    )
    lines = [
        f"0 !BRICKY DERIVED_SOURCE {DERIVED_SOURCE_FORMAT_VERSION}",
        f"0 !BRICKY ROOT {occurrence_id}",
    ]
    for occurrence in occurrences:
        lines.append(
            " ".join(
                (
                    "0 !BRICKY OCCURRENCE",
                    occurrence.occurrence_id,
                    occurrence.parent_occurrence_id or "-",
                    str(occurrence.attachment_step or 0),
                    str(occurrence.traversal_order),
                    _encoded_name(occurrence.source_submodel_name),
                )
            )
        )
    for position, node in enumerate(nodes, start=1):
        if node.kind == "part_reference":
            lines.append(
                " ".join(
                    (
                        "0 !BRICKY PART",
                        node.instruction_node_id,
                        node.occurrence_id,
                        str(node.local_step),
                        str(position),
                    )
                )
            )

    for occurrence_index, occurrence in enumerate(occurrences):
        if occurrence_index > 0:
            lines.append(f"0 FILE {_occurrence_filename(occurrence.occurrence_id)}")
        else:
            lines.append(
                f"0 Name: {_occurrence_filename(occurrence.occurrence_id)}"
            )
        current_step = 1
        occurrence_nodes = data.nodes_by_occurrence.get(occurrence.occurrence_id, ())
        for node in occurrence_nodes:
            while current_step < node.local_step:
                lines.append("0 STEP")
                current_step += 1
            target = (
                _occurrence_filename(node.child_occurrence_id)
                if node.kind == "submodel_attachment"
                and node.child_occurrence_id is not None
                else _node_filename(node.instruction_node_id)
            )
            lines.append(_type_one_line(node.effective_color, node.local_transform, target))
        definition = data.definition_by_name[
            _definition_key(occurrence.source_submodel_name)
        ]
        while current_step < len(definition.local_steps):
            lines.append("0 STEP")
            current_step += 1

    for node in nodes:
        if node.kind != "part_reference":
            continue
        lines.extend(
            (
                f"0 FILE {_node_filename(node.instruction_node_id)}",
                "0 !LDRAW_ORG Model",
                _type_one_line(16, IDENTITY_TRANSFORM, node.source_filename),
            )
        )
    lines.append("0 NOFILE")
    return ("\n".join(lines) + "\n").encode("utf-8")
