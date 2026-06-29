from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from app.services.instruction_graph import (
    InstructionGraph,
    InstructionGraphLimits,
    parse_instruction_graph,
)
from app.services.ldraw_model_parser import parse_ldraw_model
from instruction_fixture_factory import generated_large_repeated_model


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "instruction_graph"
STATIC_FIXTURES = (
    "flat_steps.mpd",
    "one_stepped_submodel.mpd",
    "nested_stepped_submodels.mpd",
    "repeated_submodel.mpd",
    "transformed_occurrences.mpd",
    "explicit_attachment_steps.mpd",
    "recursion_cycle.mpd",
    "excessive_nesting.mpd",
)
PARTS = {"3001", "3002", "3020"}
COLORS = {1, 2, 4}


def fixture(name: str) -> bytes:
    return (FIXTURE_ROOT / name).read_bytes()


def graph(name: str, limits: InstructionGraphLimits | None = None) -> InstructionGraph:
    return parse_instruction_graph(fixture(name), limits=limits)


@pytest.mark.parametrize("name", STATIC_FIXTURES)
def test_static_fixture_corpus_builds_a_graph(name: str) -> None:
    result = graph(name)
    assert result.root_occurrence_id == "occ-000001"
    assert result.model_definitions
    assert result.occurrences
    assert result.traversal_order == tuple(
        occurrence.occurrence_id for occurrence in result.occurrences
    )


def test_flat_steps_are_local_to_the_main_definition() -> None:
    result = graph("flat_steps.mpd")
    assert [step.step for step in result.model_definitions[0].local_steps] == [1, 2, 3]
    assert [node.local_step for node in result.instruction_nodes] == [1, 2, 3]


def test_nested_steps_remain_on_their_source_definitions() -> None:
    result = graph("nested_stepped_submodels.mpd")
    definitions = {
        definition.source_submodel_name: definition
        for definition in result.model_definitions
    }
    assert len(definitions["main.ldr"].local_steps) == 1
    assert len(definitions["level-one.ldr"].local_steps) == 2
    assert len(definitions["level-two.ldr"].local_steps) == 2
    assert [node.source_filename for node in definitions["level-two.ldr"].local_steps[1].nodes] == [
        "3020.dat"
    ]


def test_repeated_occurrences_are_distinct_and_deterministic() -> None:
    first = graph("repeated_submodel.mpd")
    second = graph("repeated_submodel.mpd")
    repeated = [
        occurrence
        for occurrence in first.occurrences
        if occurrence.source_submodel_name == "module.ldr"
    ]
    assert [occurrence.occurrence_id for occurrence in repeated] == [
        "occ-000002",
        "occ-000003",
    ]
    assert repeated[0].parent_occurrence_id == repeated[1].parent_occurrence_id == "occ-000001"
    assert asdict(first) == asdict(second)


def test_occurrence_transforms_and_inherited_colors_are_preserved() -> None:
    result = graph("transformed_occurrences.mpd")
    first, second = result.occurrences[1:]
    assert first.local_transform.translation == (10.0, 20.0, 30.0)
    assert first.local_transform.matrix == (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    assert second.local_transform.translation == (-10.0, 5.0, 7.0)
    assert second.local_transform.matrix == (0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    assert (first.effective_color, second.effective_color) == (1, 2)
    child_parts = [node for node in result.instruction_nodes if node.kind == "part_reference"]
    assert [node.effective_color for node in child_parts] == [1, 2]


def test_attachment_steps_are_in_the_parent_occurrence_timeline() -> None:
    result = graph("explicit_attachment_steps.mpd")
    children = result.occurrences[1:]
    assert [child.attachment_step for child in children] == [2, 3]
    attachments = [
        node for node in result.instruction_nodes if node.kind == "submodel_attachment"
    ]
    assert [node.occurrence_id for node in attachments] == ["occ-000001", "occ-000001"]
    assert [node.local_step for node in attachments] == [2, 3]
    assert [node.child_occurrence_id for node in attachments] == [
        child.occurrence_id for child in children
    ]


def test_cycles_are_reported_without_creating_a_cyclic_occurrence_graph() -> None:
    result = graph("recursion_cycle.mpd")
    assert len(result.occurrences) == 3
    assert result.maximum_nesting_depth == 2
    assert result.truncated is True
    assert [issue.code for issue in result.issues] == ["recursive_submodel_cycle"]
    assert result.instruction_nodes[-1].child_occurrence_id is None


def test_all_configurable_limits_return_structured_issues() -> None:
    depth = graph(
        "excessive_nesting.mpd",
        InstructionGraphLimits(max_nesting_depth=2),
    )
    occurrences = graph(
        "repeated_submodel.mpd",
        InstructionGraphLimits(max_expanded_occurrences=2),
    )
    nodes = graph(
        "flat_steps.mpd",
        InstructionGraphLimits(max_instruction_nodes=2),
    )
    assert depth.maximum_nesting_depth == 2
    assert len(occurrences.occurrences) == 2
    assert len(nodes.instruction_nodes) == 2
    assert depth.issues[0].code == "nesting_depth_limit_exceeded"
    assert occurrences.issues[0].code == "expanded_occurrence_limit_exceeded"
    assert nodes.issues[0].code == "instruction_node_limit_exceeded"
    assert depth.issues[0].configured_limit == 2
    assert occurrences.issues[0].configured_limit == 2
    assert nodes.issues[0].configured_limit == 2


@pytest.mark.parametrize(
    ("name", "expected_quantity"),
    [
        ("flat_steps.mpd", 3),
        ("one_stepped_submodel.mpd", 2),
        ("nested_stepped_submodels.mpd", 3),
        ("repeated_submodel.mpd", 2),
        ("transformed_occurrences.mpd", 2),
        ("explicit_attachment_steps.mpd", 3),
        ("recursion_cycle.mpd", 0),
        ("excessive_nesting.mpd", 1),
    ],
)
def test_instruction_fixtures_preserve_existing_bom_quantities(
    name: str, expected_quantity: int
) -> None:
    result = parse_ldraw_model(
        fixture(name), official_part_ids=PARTS, known_color_codes=COLORS
    )
    assert sum(item.quantity for item in result.bom) == expected_quantity


def test_generated_large_repeated_fixture_is_part_of_the_corpus() -> None:
    source = generated_large_repeated_model(100)
    result = parse_instruction_graph(source)
    bom = parse_ldraw_model(
        source, official_part_ids=PARTS, known_color_codes=COLORS
    )
    assert len(result.occurrences) == 101
    assert len(result.instruction_nodes) == 200
    assert sum(item.quantity for item in bom.bom) == 100
