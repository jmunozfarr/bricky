from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Set as AbstractSet

import pytest

from app.services.ldraw_model_parser import (
    ModelParseError,
    ParsedModel,
    ReferenceResolution,
    parse_ldraw_model,
)

PARTS = {"3001", "3002", "3020"}
COLORS = {1, 2, 4, 5}
IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"


def ref(color: int, filename: str) -> str:
    return f"1 {color} {IDENTITY} {filename}"


def parse(
    text: str | bytes,
    primitives: AbstractSet[str] = frozenset(),
    resolutions: Mapping[str, ReferenceResolution] | None = None,
) -> ParsedModel:
    content = text if isinstance(text, bytes) else text.encode()
    return parse_ldraw_model(
        content,
        official_part_ids=PARTS,
        known_color_codes=COLORS,
        known_primitive_names=primitives,
        reference_resolutions=resolutions,
    )


def quantities(result: ParsedModel) -> list[tuple[str, int, int]]:
    return [(item.part_id, item.color_code, item.quantity) for item in result.bom]


def test_simple_ldr_colors_geometry_and_deterministic_bom() -> None:
    result = parse(
        "\n".join(
            [
                "0 Simple",
                ref(4, "3002.dat"),
                "2 24 0 0 0 1 1 1",
                ref(1, "3001.dat"),
                ref(4, "3001.dat"),
            ]
        )
    )
    assert quantities(result) == [("3001", 1, 1), ("3001", 4, 1), ("3002", 4, 1)]
    assert result.declared_step_count == 1


@pytest.mark.parametrize(
    ("source", "steps"),
    [
        (f"0 Model\n{ref(4, '3001.dat')}\n0 STEP", 2),
        (f"0 Model\n0 STEP\n{ref(4, '3001.dat')}\n0 ROTSTEP 0 0 0 REL", 3),
    ],
)
def test_top_level_steps(source: str, steps: int) -> None:
    assert parse(source).declared_step_count == steps


def test_mpd_nested_repeated_submodels_and_color_inheritance() -> None:
    source = "\n".join(
        [
            "0 FILE main.ldr",
            ref(4, "SUB\\ONE.LDR"),
            ref(4, "sub/one.ldr"),
            "0 FILE sub/one.ldr",
            ref(16, "nested.ldr"),
            "0 FILE nested.ldr",
            ref(16, "3001.dat"),
            "0 NOFILE",
        ]
    )
    result = parse(source)
    assert quantities(result) == [("3001", 4, 2)]
    assert result.main_file_name == "main.ldr"


def test_explicit_nested_color_overrides_parent() -> None:
    result = parse(
        "\n".join(
            [
                "0 FILE main.ldr",
                ref(4, "sub.ldr"),
                "0 FILE sub.ldr",
                ref(2, "3001.dat"),
            ]
        )
    )
    assert quantities(result) == [("3001", 2, 1)]


def test_color_24_and_unknown_color_create_warnings_without_losing_unknown() -> None:
    result = parse(f"0 Model\n{ref(24, '3001.dat')}\n{ref(99, '3002.dat')}")
    assert quantities(result) == [("3002", 99, 1)]
    assert {issue.code for issue in result.issues} == {
        "edge_color_not_physical",
        "unknown_color",
    }


def test_unresolved_malformed_and_cycle_are_nonfatal() -> None:
    result = parse(
        "\n".join(
            [
                "0 FILE main.ldr",
                ref(4, "missing.ldr"),
                "1 4 nope",
                ref(4, "loop.ldr"),
                "0 FILE loop.ldr",
                ref(16, "main.ldr"),
            ]
        )
    )
    assert quantities(result) == []
    assert {issue.code for issue in result.issues} == {
        "unresolved_reference",
        "malformed_type1_reference",
        "recursive_submodel_cycle",
    }


def test_embedded_section_shadowing_official_part_maps_without_expansion() -> None:
    result = parse(
        "\n".join(
            [
                "0 FILE main.ldr",
                ref(4, "3001.dat"),
                "0 FILE 3001.dat",
                ref(16, "3002.dat"),
            ]
        )
    )
    assert quantities(result) == [("3001", 4, 1)]
    assert len(result.issues) == 1
    assert result.issues[0].code == "custom_part_auto_mapped"
    assert result.issues[0].severity == "info"


def test_set_wrapper_and_bent_customs_auto_map_to_official_parts() -> None:
    result = parse(
        "\n".join(
            [
                "0 FILE main.ldr",
                ref(4, "42083 - 3020.dat"),
                ref(1, "3001_bended.dat"),
                ref(4, "sub.ldr"),
                "0 FILE sub.ldr",
                ref(2, "42083 - 3020.dat"),
                "0 FILE 42083 - 3020.dat",
                "3 16 0 0 0 1 0 0 0 1 0",
            ]
        )
    )
    assert quantities(result) == [("3001", 1, 1), ("3020", 2, 1), ("3020", 4, 1)]
    mapped = {
        (issue.code, issue.severity, issue.referenced_filename, issue.occurrence_count)
        for issue in result.issues
    }
    assert mapped == {
        ("custom_part_auto_mapped", "info", "42083 - 3020.dat", 2),
        ("custom_part_auto_mapped", "info", "3001_bended.dat", 1),
    }


def test_unmappable_custom_wrapper_keeps_warning_with_count() -> None:
    result = parse(
        "\n".join(
            [
                "0 FILE main.ldr",
                ref(4, "42083 - ldcflexaxlemid.dat"),
                ref(2, "42083 - ldcflexaxlemid.dat"),
                "0 FILE 42083 - ldcflexaxlemid.dat",
                "3 16 0 0 0 1 0 0 0 1 0",
            ]
        )
    )
    assert quantities(result) == []
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.code == "unsupported_custom_part"
    assert issue.severity == "warning"
    assert issue.occurrence_count == 2


def test_auto_mapped_wrapper_with_undetermined_color_is_not_counted() -> None:
    result = parse(
        "\n".join(
            [
                "0 FILE main.ldr",
                ref(16, "42083 - 3020.dat"),
                ref(4, "3001.dat"),
                "0 FILE 42083 - 3020.dat",
                "3 16 0 0 0 1 0 0 0 1 0",
            ]
        )
    )
    assert quantities(result) == [("3001", 4, 1)]
    assert {issue.code for issue in result.issues} == {"undetermined_color"}


def test_bare_primitive_references_are_rendering_only() -> None:
    source = "\n".join(
        [
            "0 Model",
            ref(4, "3001.dat"),
            ref(16, "axlehol8.dat"),
            ref(0, "4-4cyli.dat"),
        ]
    )
    with_index = parse(source, primitives={"axlehol8.dat", "4-4cyli.dat"})
    assert quantities(with_index) == [("3001", 4, 1)]
    assert with_index.issues == ()

    without_index = parse(source)
    assert quantities(without_index) == [("3001", 4, 1)]
    assert {issue.code for issue in without_index.issues} == {"unresolved_reference"}


def test_official_part_shadows_primitive_name() -> None:
    result = parse(f"0 Model\n{ref(4, '3001.dat')}", primitives={"3001.dat"})
    assert quantities(result) == [("3001", 4, 1)]


def test_submodel_reference_with_color_16_at_top_level_is_standard() -> None:
    result = parse(
        "\n".join(
            [
                "0 FILE main.ldr",
                ref(16, "body.ldr"),
                "0 FILE body.ldr",
                ref(4, "3001.dat"),
            ]
        )
    )
    assert quantities(result) == [("3001", 4, 1)]
    assert result.issues == ()


def test_leaf_color_16_without_parent_still_warns_and_is_dropped() -> None:
    result = parse(f"0 Model\n{ref(16, '3001.dat')}\n{ref(4, '3002.dat')}")
    assert quantities(result) == [("3002", 4, 1)]
    assert [issue.code for issue in result.issues] == ["undetermined_color"]


def test_submodel_reference_with_edge_color_still_warns() -> None:
    result = parse(
        "\n".join(
            [
                "0 FILE main.ldr",
                ref(24, "sub.ldr"),
                "0 FILE sub.ldr",
                ref(16, "3001.dat"),
            ]
        )
    )
    assert quantities(result) == []
    assert {issue.code for issue in result.issues} == {
        "edge_color_not_physical",
        "undetermined_color",
    }


def test_manual_resolutions_map_and_ignore_references() -> None:
    source = "\n".join(
        [
            "0 Model",
            ref(4, "customhose.dat"),
            ref(4, "sticker.dat"),
            ref(16, "flexthing.dat"),
        ]
    )
    result = parse(
        source,
        resolutions={
            "customhose.dat": ReferenceResolution("map", "3001"),
            "sticker.dat": ReferenceResolution("ignore"),
            "flexthing.dat": ReferenceResolution("map", "3002", color_code=2),
        },
    )
    assert quantities(result) == [("3001", 4, 1), ("3002", 2, 1)]
    assert {(issue.code, issue.severity) for issue in result.issues} == {
        ("reference_manually_mapped", "info"),
        ("reference_ignored", "info"),
    }


def test_generated_path_section_is_flagged_until_resolved() -> None:
    source = "\n".join(
        [
            "0 FILE main.ldr",
            ref(4, "axlepath.ldr"),
            ref(2, "3001.dat"),
            "0 FILE axlepath.ldr",
            "0 !LDCAD PATH_POINT [posOri=1]",
            "2 24 0 0 0 1 1 1",
        ]
    )
    unresolved = parse(source)
    assert quantities(unresolved) == [("3001", 2, 1)]
    flagged = [
        issue for issue in unresolved.issues if issue.code == "generated_section_without_parts"
    ]
    assert len(flagged) == 1
    assert flagged[0].severity == "warning"
    assert flagged[0].referenced_filename == "axlepath.ldr"

    mapped = parse(source, resolutions={"axlepath.ldr": ReferenceResolution("map", "3020")})
    assert quantities(mapped) == [("3001", 2, 1), ("3020", 4, 1)]
    assert {issue.code for issue in mapped.issues} == {"reference_manually_mapped"}

    ignored = parse(source, resolutions={"axlepath.ldr": ReferenceResolution("ignore")})
    assert quantities(ignored) == [("3001", 2, 1)]
    assert {issue.code for issue in ignored.issues} == {"reference_ignored"}


def test_generated_section_flagged_only_at_outermost_level() -> None:
    source = "\n".join(
        [
            "0 FILE main.ldr",
            ref(4, "flex.ldr"),
            ref(2, "assembly.ldr"),
            "0 FILE flex.ldr",
            "0 !LDCAD PATH_POINT [posOri=1]",
            ref(16, "flexfallback.ldr"),
            "0 FILE flexfallback.ldr",
            "0 !LDCAD GENERATED [generator=LDCad]",
            "3 16 0 0 0 1 0 0 0 1 0",
            "0 FILE assembly.ldr",
            ref(16, "3001.dat"),
        ]
    )
    result = parse(source)
    assert quantities(result) == [("3001", 2, 1)]
    flagged = [
        issue.referenced_filename
        for issue in result.issues
        if issue.code == "generated_section_without_parts"
    ]
    assert flagged == ["flex.ldr"]


def test_utf8_bom_and_cp1252_fallback() -> None:
    utf8 = parse(b"\xef\xbb\xbf0 Caf\xc3\xa9\n" + ref(4, "3001.dat").encode())
    cp1252 = parse(b"0 Caf\xe9\n" + ref(4, "3001.dat").encode())
    assert utf8.encoding == "utf-8-sig"
    assert cp1252.encoding == "cp1252"


def test_binary_and_empty_main_are_fatal() -> None:
    with pytest.raises(ModelParseError, match="binary"):
        parse(b"0 Model\x00\x01")
    with pytest.raises(ModelParseError, match="no references or geometry"):
        parse("0 Only comments")
