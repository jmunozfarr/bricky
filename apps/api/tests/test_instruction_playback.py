from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from instruction_fixture_factory import generated_large_repeated_model

from app.services.instruction_graph import InstructionGraphLimits, parse_instruction_graph
from app.services.instruction_playback import (
    PlaybackData,
    RenderComplexityLimits,
    build_playback_data,
    derive_occurrence_source,
    playback_breadcrumbs,
    playback_occurrence,
    select_render_strategy,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "instruction_graph"


def data(name: str, limits: InstructionGraphLimits | None = None) -> PlaybackData:
    source = (FIXTURE_ROOT / name).read_bytes()
    return build_playback_data(parse_instruction_graph(source, limits=limits))


def test_flat_and_nested_occurrences_use_definition_local_steps() -> None:
    flat = playback_occurrence(data("flat_steps.mpd"), "occ-000001", current_step=2)
    nested_data = data("nested_stepped_submodels.mpd")
    nested = playback_occurrence(nested_data, "occ-000002", current_step=2)

    assert flat.local_step_count == 3
    assert flat.previous_step == 1 and flat.next_step == 3
    assert flat.step_summary.local_part_count == 1
    assert nested.local_step_count == 2
    assert nested.children[0].occurrence_id == "occ-000003"
    assert nested.children[0].attachment_step == 2
    assert [item.occurrence_id for item in nested.breadcrumbs] == [
        "occ-000001",
        "occ-000002",
    ]


def test_explicit_attachment_children_are_returned_only_at_their_parent_step() -> None:
    playback = data("explicit_attachment_steps.mpd")

    first = playback_occurrence(playback, "occ-000001", current_step=1)
    second = playback_occurrence(playback, "occ-000001", current_step=2)
    third = playback_occurrence(playback, "occ-000001", current_step=3)

    assert first.children == ()
    assert [child.occurrence_id for child in second.children] == ["occ-000002"]
    assert [child.occurrence_id for child in third.children] == ["occ-000003"]


def test_repeated_definitions_keep_occurrence_identity_and_indices() -> None:
    playback = data("repeated_submodel.mpd")
    root = playback_occurrence(playback, "occ-000001", current_step=1)

    assert [child.occurrence_id for child in root.children] == [
        "occ-000002",
        "occ-000003",
    ]
    assert [child.repeated_definition_index for child in root.children] == [1, 2]
    assert [child.repeated_definition_count for child in root.children] == [2, 2]


def test_transformed_occurrences_have_unique_derived_sections() -> None:
    playback = data("transformed_occurrences.mpd")
    source = derive_occurrence_source(playback, "occ-000001").decode()

    assert "__bricky_occ_000002.ldr" in source
    assert "__bricky_occ_000003.ldr" in source
    assert "1 1 10 20 30 1 0 0 0 1 0 0 0 1 __bricky_occ_000002.ldr" in source
    assert "1 2 -10 5 7 0 -1 0 1 0 0 0 0 1 __bricky_occ_000003.ldr" in source


def test_child_scope_source_uses_local_coordinates_and_only_its_subtree() -> None:
    playback = data("nested_stepped_submodels.mpd")
    source = derive_occurrence_source(playback, "occ-000002").decode()

    assert "0 !BRICKY ROOT occ-000002" in source
    assert "0 Name: __bricky_occ_000002.ldr" in source
    assert "0 FILE __bricky_occ_000003.ldr" in source
    assert "0 FILE __bricky_occ_000001.ldr" not in source
    assert source.index("0 Name: __bricky_occ_000002.ldr") < source.index(
        "0 FILE __bricky_occ_000003.ldr"
    )


def test_source_bytes_are_not_mutated_by_derivation() -> None:
    source = (FIXTURE_ROOT / "repeated_submodel.mpd").read_bytes()
    before = hashlib.sha256(source).hexdigest()
    playback = build_playback_data(parse_instruction_graph(source))

    derived = derive_occurrence_source(playback, "occ-000001")

    assert hashlib.sha256(source).hexdigest() == before
    assert derived != source


def test_cycle_and_limit_graphs_reject_playback_cleanly() -> None:
    cycle = data("recursion_cycle.mpd")
    limited = data(
        "excessive_nesting.mpd",
        InstructionGraphLimits(max_nesting_depth=2),
    )

    assert cycle.available is False
    assert limited.available is False
    assert cycle.issues[0].code == "recursive_submodel_cycle"
    assert limited.issues[0].code == "nesting_depth_limit_exceeded"
    with pytest.raises(ValueError, match="not valid"):
        derive_occurrence_source(cycle, "occ-000001")


def test_generated_child_navigation_is_paginated_without_losing_identity() -> None:
    playback = build_playback_data(parse_instruction_graph(generated_large_repeated_model(100)))
    page = playback_occurrence(
        playback,
        "occ-000001",
        current_step=1,
        child_offset=20,
        child_limit=10,
    )

    assert page.child_total == 100
    assert len(page.children) == 10
    assert page.children[0].occurrence_id == "occ-000022"
    assert page.children[-1].occurrence_id == "occ-000031"


def test_unknown_occurrence_and_step_boundaries_are_rejected() -> None:
    playback = data("flat_steps.mpd")
    with pytest.raises(KeyError):
        playback_breadcrumbs(playback, "occ-999999")
    with pytest.raises(ValueError, match="between 1 and 3"):
        playback_occurrence(playback, "occ-000001", current_step=4)


def test_direct_geometry_is_step_aware_and_keeps_occurrence_color_context() -> None:
    playback = data("direct_geometry_flex.mpd")

    child_step_one = derive_occurrence_source(
        playback, "occ-000002", current_step=1, strategy="local"
    ).decode()
    child_step_two = derive_occurrence_source(
        playback, "occ-000002", current_step=2, strategy="local"
    ).decode()
    parent = derive_occurrence_source(
        playback, "occ-000001", current_step=1, strategy="subtree"
    ).decode()

    assert "1 4 0 0 0 1 0 0 0 1 0 0 0 1 __bricky_occ_000002.ldr" in child_step_one
    assert "2 24 0 0 0 10 0 0" in child_step_one
    assert "3 16 0 0 0 10 0 0 0 10 0" in child_step_one
    assert "4 16 0 0 0 0 10 0 10 10 0 10 0 0" not in child_step_one
    assert "4 16 0 0 0 0 10 0 10 10 0 10 0 0" in child_step_two
    assert "5 24 0 0 0 10 0 0 0 10 0 10 10 0" in child_step_two
    assert "1 4 10 20 30 0 -1 0 1 0 0 0 0 1 __bricky_occ_000002.ldr" in parent
    assert "5 24 0 0 0 10 0 0 0 10 0 10 10 0" in parent
    assert (
        child_step_one.index("0 BFC CERTIFY CCW")
        < child_step_one.index("__bricky_node_000002.ldr")
        < child_step_one.index("2 24 0 0 0 10 0 0")
    )


def test_local_strategy_excludes_children_but_retains_navigation_metadata() -> None:
    playback = data("direct_geometry_flex.mpd")
    root = playback_occurrence(playback, "occ-000001", current_step=1)
    source = derive_occurrence_source(
        playback, "occ-000001", current_step=1, strategy="local"
    ).decode()

    assert root.children[0].occurrence_id == "occ-000002"
    assert "__bricky_occ_000002.ldr" not in source
    assert "0 !BRICKY RENDER_STRATEGY local" in source


def test_render_strategy_policy_is_deterministic_at_each_boundary() -> None:
    small = data("direct_geometry_flex.mpd")
    selection = select_render_strategy(small, "occ-000001")
    assert selection.recommended_strategy == "subtree"

    exact = RenderComplexityLimits(
        max_expanded_instruction_nodes=selection.complexity.expanded_instruction_node_count,
        max_expanded_occurrences=selection.complexity.expanded_occurrence_count,
        max_direct_geometry_commands=selection.complexity.direct_geometry_command_count,
        max_derived_source_bytes=selection.complexity.estimated_derived_source_bytes,
    )
    assert select_render_strategy(small, "occ-000001", exact).recommended_strategy == "subtree"
    over = RenderComplexityLimits(
        max_expanded_instruction_nodes=selection.complexity.expanded_instruction_node_count,
        max_expanded_occurrences=selection.complexity.expanded_occurrence_count,
        max_direct_geometry_commands=selection.complexity.direct_geometry_command_count,
        max_derived_source_bytes=selection.complexity.estimated_derived_source_bytes - 1,
    )
    assert select_render_strategy(small, "occ-000001", over).recommended_strategy == "local"


def test_generated_small_and_large_scopes_select_expected_strategies() -> None:
    small = build_playback_data(parse_instruction_graph(generated_large_repeated_model(100)))
    large = build_playback_data(parse_instruction_graph(generated_large_repeated_model(1_000)))
    assert select_render_strategy(small, "occ-000001").recommended_strategy == "subtree"
    assert select_render_strategy(large, "occ-000001").recommended_strategy == "local"


def test_local_step_two_contains_each_cumulative_root_part_exactly_once() -> None:
    # These extracted placements reproduce an authored overlap in an independent
    # LDraw editor. This fixture validates source structure, not visual accuracy.
    source = (FIXTURE_ROOT / "falcon_step_02_isolated.ldr").read_bytes()
    playback = build_playback_data(parse_instruction_graph(source))
    step_one = derive_occurrence_source(
        playback, "occ-000001", current_step=1, strategy="local"
    ).decode()
    step_two = derive_occurrence_source(
        playback, "occ-000001", current_step=2, strategy="local"
    ).decode()

    assert step_one.count("0 !BRICKY PART ") == 2
    assert step_one.count("0 FILE __bricky_node_") == 2
    assert "32531.dat" in step_one and "6558.dat" in step_one
    assert "3703.dat" not in step_one and "32532.dat" not in step_one

    manifest_ids = [
        line.split()[3] for line in step_two.splitlines() if line.startswith("0 !BRICKY PART ")
    ]
    wrapper_definitions = [
        line.split()[2]
        for line in step_two.splitlines()
        if line.startswith("0 FILE __bricky_node_")
    ]
    placement_lines = [
        line for line in step_two.splitlines() if line.startswith("1 ") and "__bricky_node_" in line
    ]
    assert manifest_ids == [
        "node-000001",
        "node-000002",
        "node-000003",
        "node-000004",
    ]
    assert len(set(manifest_ids)) == len(set(wrapper_definitions)) == 4
    assert len(placement_lines) == 4
    assert placement_lines == [
        "1 0 0 0 0 1 0 0 0 1 0 0 0 1 __bricky_node_000001.ldr",
        "1 0 0 10 -50 0 0 1 0 1 0 -1 0 0 __bricky_node_000002.ldr",
        "1 72 -140 0 -50 -1 0 0 0 1 0 0 0 -1 __bricky_node_000003.ldr",
        "1 0 0 0 -120 -1 0 0 0 1 0 0 0 -1 __bricky_node_000004.ldr",
    ]
    for filename in ("32531.dat", "6558.dat", "3703.dat", "32532.dat"):
        assert step_two.count(filename) == 1
        assert f"1 16 0 0 0 1 0 0 0 1 0 0 0 1 {filename}" in step_two
    assert step_two.count("0 !BRICKY OCCURRENCE ") == 1
    assert "__bricky_occ_000002" not in step_two
