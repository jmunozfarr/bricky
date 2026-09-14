from __future__ import annotations

import base64
import threading
from collections import Counter, OrderedDict, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.services.instruction_graph import (
    IDENTITY_TRANSFORM,
    ExpandedInstructionNode,
    InstructionGraph,
    InstructionGraphIssue,
    InstructionGraphLimits,
    LocalDirectGeometry,
    LocalTransform,
    ModelDefinition,
    ModelOccurrence,
    parse_instruction_graph,
)
from app.services.ldraw_model_parser import _normalize_reference

PLAYBACK_CHILD_PAGE_SIZE = 50
PLAYBACK_CHILD_PAGE_SIZE_MAXIMUM = 100
DERIVED_SOURCE_FORMAT_VERSION = 2
# Calibrated against the UCS Millennium Falcon stress model (5 768 nodes,
# 433 occurrences, 1.18 MB derived source) and LDCad-exported Technic
# flagships (42083: 9 509 nodes; 8386: 239 246 direct geometry commands and
# a 23.7 MB derived source from baked flex-part quads), all of which must
# render as complete subtrees. A direct
# geometry command is one quad/line — hundreds of times cheaper than a part
# reference node, which expands into a full part mesh — so its budget is
# far larger than the node budget.
DEFAULT_RENDER_MAX_EXPANDED_INSTRUCTION_NODES = 12_000
DEFAULT_RENDER_MAX_EXPANDED_OCCURRENCES = 600
DEFAULT_RENDER_MAX_DIRECT_GEOMETRY_COMMANDS = 300_000
DEFAULT_RENDER_MAX_DERIVED_SOURCE_BYTES = 32 * 1_024 * 1_024

RenderStrategy = Literal["subtree", "local"]


@dataclass(frozen=True)
class RenderComplexityLimits:
    max_expanded_instruction_nodes: int = DEFAULT_RENDER_MAX_EXPANDED_INSTRUCTION_NODES
    max_expanded_occurrences: int = DEFAULT_RENDER_MAX_EXPANDED_OCCURRENCES
    max_direct_geometry_commands: int = DEFAULT_RENDER_MAX_DIRECT_GEOMETRY_COMMANDS
    max_derived_source_bytes: int = DEFAULT_RENDER_MAX_DERIVED_SOURCE_BYTES

    def __post_init__(self) -> None:
        if (
            min(
                self.max_expanded_instruction_nodes,
                self.max_expanded_occurrences,
                self.max_direct_geometry_commands,
                self.max_derived_source_bytes,
            )
            < 1
        ):
            raise ValueError("Render complexity limits must be positive")


@dataclass(frozen=True)
class RenderComplexity:
    expanded_instruction_node_count: int
    expanded_occurrence_count: int
    direct_geometry_command_count: int
    estimated_derived_source_bytes: int


@dataclass(frozen=True)
class RenderStrategySelection:
    recommended_strategy: RenderStrategy
    reason: Literal["within_scope_complexity_limits", "scope_complexity_limit"]
    complexity: RenderComplexity


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
    direct_geometry_command_count: int


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
    render_complexity_by_occurrence: dict[str, RenderComplexity]


def _definition_key(name: str) -> str:
    return name.replace("\\", "/").lower()


def _playback_issue(issue: InstructionGraphIssue) -> PlaybackIssue:
    return PlaybackIssue(code=issue.code, message=issue.message)


def build_playback_data(graph: InstructionGraph) -> PlaybackData:
    occurrence_by_id = {occurrence.occurrence_id: occurrence for occurrence in graph.occurrences}
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
        _definition_key(occurrence.source_submodel_name) for occurrence in graph.occurrences
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
        render_complexity_by_occurrence={},
    )


_PLAYBACK_CACHE_SIZE = 8
_PLAYBACK_CACHE_LOCK = threading.Lock()
_PLAYBACK_CACHE: OrderedDict[tuple[str, str, InstructionGraphLimits], PlaybackData] = OrderedDict()


def parse_playback_data(
    source_sha256: str,
    source_name: str,
    limits: InstructionGraphLimits,
    load_content: Callable[[], bytes],
) -> PlaybackData:
    """Cache immutable parsed playback data by the imported source identity.

    Keyed by the source hash so cache hits never read or re-hash the model
    bytes; `load_content` runs only on a miss. Parsing happens outside the
    lock — two concurrent first requests may parse twice, which beats
    serializing every playback lookup behind one large parse.
    """

    key = (source_sha256, source_name, limits)
    with _PLAYBACK_CACHE_LOCK:
        cached = _PLAYBACK_CACHE.get(key)
        if cached is not None:
            _PLAYBACK_CACHE.move_to_end(key)
            return cached
    data = build_playback_data(
        parse_instruction_graph(load_content(), source_name=source_name, limits=limits)
    )
    with _PLAYBACK_CACHE_LOCK:
        _PLAYBACK_CACHE[key] = data
        _PLAYBACK_CACHE.move_to_end(key)
        while len(_PLAYBACK_CACHE) > _PLAYBACK_CACHE_SIZE:
            _PLAYBACK_CACHE.popitem(last=False)
    return data


def clear_playback_cache() -> None:
    with _PLAYBACK_CACHE_LOCK:
        _PLAYBACK_CACHE.clear()


def playback_breadcrumbs(data: PlaybackData, occurrence_id: str) -> tuple[PlaybackBreadcrumb, ...]:
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
        raise ValueError(f"Child limit must be between 1 and {PLAYBACK_CHILD_PAGE_SIZE_MAXIMUM}")

    nodes = data.nodes_by_occurrence.get(occurrence_id, ())
    step_nodes = tuple(node for node in nodes if node.local_step == current_step)
    step_definition = definition.local_steps[current_step - 1]
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
            repeated_definition_index=data.repeated_definition_indices[child.occurrence_id],
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
        empty=not nodes and not any(step.direct_geometry for step in definition.local_steps),
        repeated_definition_count=data.repeated_definition_counts[
            _definition_key(occurrence.source_submodel_name)
        ],
        repeated_definition_index=data.repeated_definition_indices[occurrence_id],
        step_summary=PlaybackStepSummary(
            step=current_step,
            local_part_count=sum(node.kind == "part_reference" for node in step_nodes),
            child_attachment_count=len(children_at_step),
            direct_geometry_command_count=len(step_definition.direct_geometry),
        ),
        children=children,
        child_total=len(children_at_step),
        child_offset=child_offset,
        child_limit=child_limit,
    )


def _format_number(value: float) -> str:
    return "0" if value == 0 else format(value, ".15g")


def _type_one_line(color: int | None, transform: LocalTransform, filename: str) -> str:
    normalized = _normalize_reference(filename)
    if normalized is None:
        raise ValueError("Unsafe reference cannot be included in derived source")
    values = (*transform.translation, *transform.matrix)
    return " ".join(
        (
            "1",
            str(color if color is not None else 16),
            *(_format_number(value) for value in values),
            normalized,
        )
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
                [data.occurrence_by_id[child_id] for child_id in occurrence.child_occurrence_ids]
            )
        )
    return tuple(result)


def _visible_subtree_occurrences(
    data: PlaybackData, root_occurrence_id: str, current_step: int
) -> tuple[ModelOccurrence, ...]:
    root = data.occurrence_by_id[root_occurrence_id]
    result = [root]
    for child_id in root.child_occurrence_ids:
        child = data.occurrence_by_id[child_id]
        if child.attachment_step is not None and child.attachment_step <= current_step:
            result.extend(_subtree_occurrences(data, child_id))
    return tuple(result)


def _direct_geometry_line(command: LocalDirectGeometry) -> str:
    return " ".join(
        (
            str(command.command_type),
            command.color_token,
            *command.coordinate_tokens,
        )
    )


def _definition_render_lines(
    definition: ModelDefinition,
    *,
    maximum_step: int | None = None,
    include_submodel_references: bool = True,
) -> list[str]:
    lines: list[str] = []
    for step in definition.local_steps:
        if step.step > 1:
            lines.append("0 STEP")
        items: list[tuple[int, str]] = []
        if maximum_step is None or step.step <= maximum_step:
            items.extend((meta.source_order, meta.text) for meta in step.render_meta)
            items.extend(
                (geometry.source_order, _direct_geometry_line(geometry))
                for geometry in step.direct_geometry
            )
        for node in step.nodes:
            if not include_submodel_references and node.kind == "submodel_reference":
                continue
            items.append(
                (
                    node.source_order,
                    _type_one_line(node.color_code, node.local_transform, node.source_filename),
                )
            )
        lines.extend(text for _order, text in sorted(items, key=lambda item: item[0]))
    return lines


def _referenced_embedded_definitions(
    data: PlaybackData, part_nodes: tuple[ExpandedInstructionNode, ...]
) -> tuple[ModelDefinition, ...]:
    result: list[ModelDefinition] = []
    seen: set[str] = set()
    pending = [node.source_filename for node in part_nodes]
    while pending:
        name = pending.pop()
        key = _definition_key(name)
        definition = data.definition_by_name.get(key)
        if definition is None or key in seen:
            continue
        seen.add(key)
        result.append(definition)
        for step in definition.local_steps:
            pending.extend(node.source_filename for node in step.nodes)
    return tuple(result)


def _is_embedded_custom_attachment(data: PlaybackData, node: ExpandedInstructionNode) -> bool:
    return (
        node.kind == "submodel_attachment"
        and node.source_filename.lower().endswith(".dat")
        and _definition_key(node.source_filename) in data.definition_by_name
    )


def _serialize_occurrence_source(
    data: PlaybackData,
    occurrence_id: str,
    *,
    current_step: int,
    strategy: RenderStrategy,
) -> bytes:
    if not data.available:
        raise ValueError("Instruction graph is not valid for hierarchical playback")
    root = data.occurrence_by_id.get(occurrence_id)
    if root is None:
        raise KeyError(occurrence_id)
    root_definition = data.definition_by_name[_definition_key(root.source_submodel_name)]
    if current_step < 1 or current_step > len(root_definition.local_steps):
        raise ValueError(f"Step must be between 1 and {len(root_definition.local_steps)}")
    occurrences = (
        _visible_subtree_occurrences(data, occurrence_id, current_step)
        if strategy == "subtree"
        else (root,)
    )
    occurrence_ids = {occurrence.occurrence_id for occurrence in occurrences}
    nodes = tuple(
        node
        for node in data.graph.instruction_nodes
        if node.occurrence_id in occurrence_ids
        and (node.occurrence_id != occurrence_id or node.local_step <= current_step)
        and (
            strategy == "subtree"
            or node.kind == "part_reference"
            or _is_embedded_custom_attachment(data, node)
        )
    )
    render_leaf_nodes = tuple(
        node
        for node in nodes
        if node.kind == "part_reference"
        or (strategy == "local" and _is_embedded_custom_attachment(data, node))
    )
    lines = [
        f"0 !BRICKY DERIVED_SOURCE {DERIVED_SOURCE_FORMAT_VERSION}",
        f"0 !BRICKY ROOT {occurrence_id}",
        f"0 !BRICKY RENDER_STRATEGY {strategy}",
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
    for position, node in enumerate(render_leaf_nodes, start=1):
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

    root_has_direct_geometry = any(step.direct_geometry for step in root_definition.local_steps)
    needs_color_context_wrapper = root.effective_color is not None and root_has_direct_geometry
    if needs_color_context_wrapper:
        lines.append("0 !BRICKY ROOT_WRAPPED 1")
        lines.extend(
            (
                "0 Name: __bricky_scope.ldr",
                _type_one_line(
                    root.effective_color,
                    IDENTITY_TRANSFORM,
                    _occurrence_filename(root.occurrence_id),
                ),
            )
        )
    for occurrence_index, occurrence in enumerate(occurrences):
        if occurrence_index == 0 and not needs_color_context_wrapper:
            lines.append(f"0 Name: {_occurrence_filename(occurrence.occurrence_id)}")
        else:
            lines.append(f"0 FILE {_occurrence_filename(occurrence.occurrence_id)}")
        # Occurrence wrappers must always parse to a named scene group. A
        # Part/Subpart type inherited from a .dat-defined submodel would make
        # LDrawLoader flatten the wrapper into parent geometry instead.
        lines.append("0 !LDRAW_ORG Model")
        occurrence_nodes = tuple(
            node for node in nodes if node.occurrence_id == occurrence.occurrence_id
        )
        definition = data.definition_by_name[_definition_key(occurrence.source_submodel_name)]
        for local_step in definition.local_steps:
            if local_step.step > 1:
                lines.append("0 STEP")
            items: list[tuple[int, str]] = []
            geometry_visible = (
                occurrence.occurrence_id != occurrence_id or local_step.step <= current_step
            )
            if geometry_visible:
                items.extend(
                    (meta.source_order, meta.text)
                    for meta in local_step.render_meta
                    if not meta.text.upper().startswith("0 !LDRAW_ORG")
                )
                items.extend(
                    (geometry.source_order, _direct_geometry_line(geometry))
                    for geometry in local_step.direct_geometry
                )
            for node in occurrence_nodes:
                if node.local_step != local_step.step:
                    continue
                custom_attachment = _is_embedded_custom_attachment(data, node)
                if (
                    strategy == "local"
                    and node.kind == "submodel_attachment"
                    and not custom_attachment
                ):
                    continue
                if node.kind == "submodel_attachment" and node.child_occurrence_id is None:
                    continue
                target = (
                    _occurrence_filename(node.child_occurrence_id)
                    if node.kind == "submodel_attachment"
                    and node.child_occurrence_id is not None
                    and not (strategy == "local" and custom_attachment)
                    else _node_filename(node.instruction_node_id)
                )
                items.append(
                    (
                        node.source_order,
                        _type_one_line(node.effective_color, node.local_transform, target),
                    )
                )
            lines.extend(text for _order, text in sorted(items, key=lambda item: item[0]))

    for node in render_leaf_nodes:
        lines.extend(
            (
                f"0 FILE {_node_filename(node.instruction_node_id)}",
                "0 !LDRAW_ORG Model",
                _type_one_line(16, IDENTITY_TRANSFORM, node.source_filename),
            )
        )
    for definition in _referenced_embedded_definitions(data, render_leaf_nodes):
        # Reference lines are normalized to forward slashes, but LDrawLoader
        # keys embedded files by the exact FILE name; a raw backslash name
        # (e.g. "s\42056s01.dat") would never match and the loader would fall
        # back to fetching the file from the library, where it 404s.
        lines.extend(
            (
                f"0 FILE {definition.source_submodel_name.replace('\\', '/')}",
                *_definition_render_lines(definition),
            )
        )
    lines.append("0 NOFILE")
    return ("\n".join(lines) + "\n").encode("utf-8")


def occurrence_render_complexity(data: PlaybackData, occurrence_id: str) -> RenderComplexity:
    cached = data.render_complexity_by_occurrence.get(occurrence_id)
    if cached is not None:
        return cached
    occurrences = _subtree_occurrences(data, occurrence_id)
    occurrence_ids = {occurrence.occurrence_id for occurrence in occurrences}
    nodes = tuple(
        node for node in data.graph.instruction_nodes if node.occurrence_id in occurrence_ids
    )
    direct_geometry_count = sum(
        len(step.direct_geometry)
        for occurrence in occurrences
        for step in data.definition_by_name[
            _definition_key(occurrence.source_submodel_name)
        ].local_steps
    )
    direct_geometry_bytes = sum(
        len(_direct_geometry_line(geometry).encode("utf-8")) + 1
        for occurrence in occurrences
        for step in data.definition_by_name[
            _definition_key(occurrence.source_submodel_name)
        ].local_steps
        for geometry in step.direct_geometry
    )
    render_meta_bytes = sum(
        len(meta.text.encode("utf-8")) + 1
        for occurrence in occurrences
        for step in data.definition_by_name[
            _definition_key(occurrence.source_submodel_name)
        ].local_steps
        for meta in step.render_meta
    )
    step_boundary_bytes = sum(
        max(
            0,
            len(
                data.definition_by_name[
                    _definition_key(occurrence.source_submodel_name)
                ].local_steps
            )
            - 1,
        )
        * len("0 STEP\n")
        for occurrence in occurrences
    )
    # This estimate mirrors the stable manifest/reference wrapper structure without
    # allocating a potentially multi-megabyte derived source merely to classify it.
    source_size = (
        128
        + len(occurrences) * 110
        + sum(90 if node.kind == "submodel_attachment" else 150 for node in nodes)
        + direct_geometry_bytes
        + render_meta_bytes
        + step_boundary_bytes
    )
    complexity = RenderComplexity(
        expanded_instruction_node_count=len(nodes),
        expanded_occurrence_count=len(occurrences),
        direct_geometry_command_count=direct_geometry_count,
        estimated_derived_source_bytes=source_size,
    )
    data.render_complexity_by_occurrence[occurrence_id] = complexity
    return complexity


def select_render_strategy(
    data: PlaybackData,
    occurrence_id: str,
    limits: RenderComplexityLimits | None = None,
) -> RenderStrategySelection:
    active_limits = limits or RenderComplexityLimits()
    complexity = occurrence_render_complexity(data, occurrence_id)
    over_limit = (
        complexity.expanded_instruction_node_count > active_limits.max_expanded_instruction_nodes
        or complexity.expanded_occurrence_count > active_limits.max_expanded_occurrences
        or complexity.direct_geometry_command_count > active_limits.max_direct_geometry_commands
        or complexity.estimated_derived_source_bytes > active_limits.max_derived_source_bytes
    )
    return RenderStrategySelection(
        recommended_strategy="local" if over_limit else "subtree",
        reason=("scope_complexity_limit" if over_limit else "within_scope_complexity_limits"),
        complexity=complexity,
    )


def derive_occurrence_source(
    data: PlaybackData,
    occurrence_id: str,
    *,
    current_step: int | None = None,
    strategy: RenderStrategy = "subtree",
) -> bytes:
    occurrence = data.occurrence_by_id.get(occurrence_id)
    if occurrence is None:
        raise KeyError(occurrence_id)
    definition = data.definition_by_name[_definition_key(occurrence.source_submodel_name)]
    return _serialize_occurrence_source(
        data,
        occurrence_id,
        current_step=current_step or len(definition.local_steps),
        strategy=strategy,
    )
