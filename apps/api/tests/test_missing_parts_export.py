from __future__ import annotations

from app.services.inventory_import import parse_inventory_csv
from app.services.inventory_import_formats import parse_bricklink_xml
from app.services.missing_parts_export import (
    BrickLinkExportRow,
    MissingPartRow,
    resolve_bricklink_export_rows,
    write_bricklink_wanted_list_xml,
    write_missing_parts_csv,
)


def row(part_id: str, color_code: int, quantity: int) -> MissingPartRow:
    return MissingPartRow(
        part_id=part_id,
        color_code=color_code,
        quantity=quantity,
        part_name=f"Part {part_id}",
        color_name=f"Color {color_code}",
    )


class TestWriteMissingPartsCsv:
    def test_empty_document_is_header_only(self) -> None:
        assert write_missing_parts_csv([]) == "part_id,color_code,quantity,part_name,color_name\n"

    def test_round_trips_through_native_import_parser(self) -> None:
        csv_text = write_missing_parts_csv([row("3001", 4, 2), row("3070b", 1, 10)])
        parsed = parse_inventory_csv(csv_text.encode("utf-8"))
        assert parsed.issues == ()
        assert [(r.part_id, r.color_code, r.quantity) for r in parsed.rows] == [
            ("3001", 4, 2),
            ("3070b", 1, 10),
        ]
        # part_name/color_name are extra, ignored columns from the native
        # parser's point of view -- the file re-imports unchanged.
        assert set(parsed.ignored_columns) == {"part_name", "color_name"}


class TestResolveBricklinkExportRows:
    def test_maps_both_part_and_color(self) -> None:
        result = resolve_bricklink_export_rows(
            [row("3001", 4, 2)],
            part_map={"3001": "bl3001"},
            color_map={4: 11},
        )
        assert result.total_count == 1
        assert result.skipped_count == 0
        assert result.rows == (BrickLinkExportRow("bl3001", 11, 2),)

    def test_drops_row_missing_part_mapping(self) -> None:
        result = resolve_bricklink_export_rows(
            [row("mystery", 4, 1)], part_map={}, color_map={4: 11}
        )
        assert result.rows == ()
        assert result.skipped_count == 1
        assert result.total_count == 1

    def test_drops_row_missing_color_mapping(self) -> None:
        result = resolve_bricklink_export_rows(
            [row("3001", 999, 1)], part_map={"3001": "bl3001"}, color_map={}
        )
        assert result.rows == ()
        assert result.skipped_count == 1

    def test_normalizes_part_id_case_for_lookup(self) -> None:
        result = resolve_bricklink_export_rows(
            [row("3070B", 4, 1)], part_map={"3070b": "bl3070b"}, color_map={4: 11}
        )
        assert result.rows == (BrickLinkExportRow("bl3070b", 11, 1),)

    def test_empty_input(self) -> None:
        result = resolve_bricklink_export_rows([], part_map={}, color_map={})
        assert result == resolve_bricklink_export_rows([], part_map={}, color_map={})
        assert result.total_count == 0
        assert result.skipped_count == 0
        assert result.rows == ()


class TestWriteBricklinkWantedListXml:
    def test_empty_document_is_a_valid_empty_root(self) -> None:
        assert write_bricklink_wanted_list_xml([]) == "<INVENTORY />"

    def test_round_trips_through_bricklink_import_parser(self) -> None:
        xml_text = write_bricklink_wanted_list_xml(
            [BrickLinkExportRow("bl3001", 11, 2), BrickLinkExportRow("bl3070b", 5, 10)]
        )
        parsed = parse_bricklink_xml(xml_text.encode("utf-8"))
        assert parsed.issues == ()
        assert [(r.source_part_id, r.source_color_id, r.quantity) for r in parsed.rows] == [
            ("bl3001", 11, 2),
            ("bl3070b", 5, 10),
        ]
