from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.services.instruction_graph import InstructionGraphLimits, parse_instruction_graph
from app.services.instruction_playback import (
    build_playback_data,
    derive_occurrence_source,
    playback_breadcrumbs,
    playback_occurrence,
)
from instruction_fixture_factory import generated_large_repeated_model


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "instruction_graph"


def data(name: str, limits: InstructionGraphLimits | None = None):
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
    playback = build_playback_data(
        parse_instruction_graph(generated_large_repeated_model(100))
    )
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
