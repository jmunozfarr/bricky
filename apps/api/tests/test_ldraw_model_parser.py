from __future__ import annotations

import pytest

from app.services.ldraw_model_parser import ModelParseError, parse_ldraw_model


PARTS = {"3001", "3002", "3020"}
COLORS = {1, 2, 4, 5}
IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"


def ref(color: int, filename: str) -> str:
    return f"1 {color} {IDENTITY} {filename}"


def parse(text: str | bytes):
    content = text if isinstance(text, bytes) else text.encode()
    return parse_ldraw_model(
        content, official_part_ids=PARTS, known_color_codes=COLORS
    )


def quantities(result) -> list[tuple[str, int, int]]:
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


def test_official_part_is_not_expanded_as_an_mpd_section() -> None:
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
    assert quantities(result) == []
    assert result.issues[0].code == "unsupported_custom_part"


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
