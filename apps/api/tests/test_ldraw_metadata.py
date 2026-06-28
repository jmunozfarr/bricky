from app.services.ldraw_metadata import parse_color_config, parse_part_header


def test_parses_complete_representative_part_header() -> None:
    content = b"""0 Brick  2 x  4
0 Name: 3001.dat
0 Author: James Jessiman
0 !LDRAW_ORG Part UPDATE 2004-03
0 !LICENSE Licensed under CC BY 4.0 : see CAreadme.txt
0 !CATEGORY Brick
0 !KEYWORDS basic, rectangular
1 16 0 0 0 1 0 0 0 1 0 0 0 1 s\\3001s01.dat
0 !KEYWORDS ignored, after geometry
"""

    header = parse_part_header(content, "parts/3001.dat")

    assert header.part_id == "3001"
    assert header.description == "Brick  2 x  4"
    assert header.author == "James Jessiman"
    assert header.category == "Brick"
    assert header.org_classification == "Part UPDATE 2004-03"
    assert header.license == "Licensed under CC BY 4.0 : see CAreadme.txt"
    assert header.keywords == ("basic", "rectangular")
    assert header.is_subpart is False


def test_missing_optional_fields_are_safe() -> None:
    header = parse_part_header(b"0 Simple Element\n2 24 0 0 0 1 1 1\n", "parts/x1.dat")

    assert header.author is None
    assert header.license is None
    assert header.org_classification is None
    assert header.keywords == ()


def test_category_falls_back_to_description_prefix() -> None:
    header = parse_part_header(b"0 Minifig Head Plain\n", "parts/3626.dat")

    assert header.category == "Minifig"


def test_accumulates_multi_line_keywords() -> None:
    content = b"0 Plate\n0 !KEYWORDS flat, base\n0 !KEYWORDS thin, structural\n"

    assert parse_part_header(content, "parts/p1.dat").keywords == (
        "flat",
        "base",
        "thin",
        "structural",
    )


def test_detects_subpart_from_normalized_path() -> None:
    header = parse_part_header(b"0 Subpart\n", "parts\\s\\3001s01.dat")

    assert header.relative_path == "parts/s/3001s01.dat"
    assert header.is_subpart is True


def test_invalid_utf8_is_replaced_without_aborting() -> None:
    header = parse_part_header(b"0 Brick \xff special\n", "parts/test.dat")

    assert header.description == "Brick � special"


def test_parses_representative_color_definitions_and_optional_properties() -> None:
    content = b"""0 !COLOUR Bright_Red CODE 4 VALUE #C91A09 EDGE #333333
0 !COLOUR Trans_Blue CODE 33 VALUE #0020A0 EDGE 4 ALPHA 128 LUMINANCE 15
0 !COLOUR Chrome_Gold CODE 334 VALUE #BBA53D EDGE #333333 CHROME
0 !COLOUR Glitter CODE 100 VALUE #123456 EDGE #654321 MATERIAL GLITTER VALUE #FFFFFF
"""

    colors = parse_color_config(content)

    assert colors[0].name == "Bright Red"
    assert colors[0].edge_hex == "#333333"
    assert colors[0].alpha == 255
    assert colors[1].edge_hex is None
    assert colors[1].alpha == 128
    assert colors[1].luminance == 15
    assert colors[2].finish == "CHROME"
    assert colors[3].finish == "GLITTER"
