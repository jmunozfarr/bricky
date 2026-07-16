from __future__ import annotations

from pathlib import Path

import pytest

from app.services.inventory_import import InventoryImportError
from app.services.inventory_import_formats import (
    detect_import_format,
    parse_bricklink_xml,
    parse_rebrickable_csv,
)

FIXTURES = Path(__file__).parent / "fixtures"
REBRICKABLE_FIXTURE = FIXTURES / "rebrickable_parts_moc.csv"
BRICKLINK_FIXTURE = FIXTURES / "bricklink_wanted_list.xml"


class TestDetectImportFormat:
    def test_native_csv_header(self) -> None:
        assert (
            detect_import_format("inv.csv", b"part_id,color_code,quantity\n3001,4,2\n") == "native"
        )

    def test_rebrickable_csv_header(self) -> None:
        assert (
            detect_import_format("inv.csv", b"Part,Color,Quantity,Is Spare\n3001,0,2,False\n")
            == "rebrickable"
        )

    def test_xml_extension_is_bricklink_regardless_of_content(self) -> None:
        assert detect_import_format("wanted.xml", b"<INVENTORY></INVENTORY>") == "bricklink"

    def test_unsupported_extension_rejected(self) -> None:
        with pytest.raises(InventoryImportError):
            detect_import_format("inv.txt", b"part_id,color_code,quantity\n")

    def test_unrecognized_csv_header_rejected(self) -> None:
        with pytest.raises(InventoryImportError):
            detect_import_format("inv.csv", b"foo,bar,baz\n1,2,3\n")

    def test_empty_csv_rejected(self) -> None:
        with pytest.raises(InventoryImportError):
            detect_import_format("inv.csv", b"")

    def test_real_rebrickable_fixture_detected(self) -> None:
        assert detect_import_format("moc.csv", REBRICKABLE_FIXTURE.read_bytes()) == "rebrickable"


class TestParseRebrickableCsv:
    def test_real_fixture(self) -> None:
        parsed = parse_rebrickable_csv(REBRICKABLE_FIXTURE.read_bytes())
        assert parsed.total_data_rows == 249
        assert len(parsed.rows) == 249
        assert parsed.issues == ()
        assert parsed.spare_row_count == 0
        first = parsed.rows[0]
        assert first.source_part_id == "32200"
        assert first.source_color_id == 0
        assert first.quantity == 2
        assert first.is_spare is False

    def test_spare_rows_are_flagged_and_counted(self) -> None:
        data = b"Part,Color,Quantity,Is Spare\n3001,0,2,True\n3002,0,1,False\n3003,0,1,true\n"
        parsed = parse_rebrickable_csv(data)
        assert parsed.spare_row_count == 2
        assert [row.is_spare for row in parsed.rows] == [True, False, True]

    def test_missing_spare_column_defaults_to_false(self) -> None:
        data = b"Part,Color,Quantity\n3001,0,2\n"
        parsed = parse_rebrickable_csv(data)
        assert parsed.rows[0].is_spare is False
        assert parsed.spare_row_count == 0

    def test_bad_quantity_is_a_row_issue_not_fatal(self) -> None:
        data = b"Part,Color,Quantity,Is Spare\n3001,0,0,False\n3002,0,1,False\n"
        parsed = parse_rebrickable_csv(data)
        assert len(parsed.rows) == 1
        assert len(parsed.issues) == 1
        assert parsed.issues[0].code == "bad_quantity"

    def test_missing_required_column_is_fatal(self) -> None:
        with pytest.raises(InventoryImportError):
            parse_rebrickable_csv(b"Part,Quantity\n3001,2\n")

    def test_row_cap_is_enforced(self) -> None:
        rows = "\n".join(f"{n},0,1,False" for n in range(5))
        data = f"Part,Color,Quantity,Is Spare\n{rows}\n".encode()
        with pytest.raises(InventoryImportError):
            parse_rebrickable_csv(data, max_rows=3)

    def test_non_utf8_is_rejected(self) -> None:
        with pytest.raises(InventoryImportError):
            parse_rebrickable_csv("Part,Color,Quantity\n3001,0,2\n".encode("utf-16"))


class TestParseBricklinkXml:
    def test_real_fixture(self) -> None:
        parsed = parse_bricklink_xml(BRICKLINK_FIXTURE.read_bytes())
        assert parsed.total_data_rows == 249
        assert len(parsed.rows) == 249
        assert parsed.issues == ()
        assert parsed.spare_row_count == 0
        first = parsed.rows[0]
        assert first.source_part_id == "32200"
        assert first.source_color_id == 11
        assert first.quantity == 2
        assert first.line_number == 1

    def test_non_part_item_type_is_a_row_issue(self) -> None:
        data = (
            b"<INVENTORY>"
            b"<ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>3001</ITEMID><COLOR>0</COLOR><MINQTY>1</MINQTY></ITEM>"
            b"<ITEM><ITEMTYPE>M</ITEMTYPE><ITEMID>fig01</ITEMID><COLOR>0</COLOR><MINQTY>1</MINQTY></ITEM>"
            b"</INVENTORY>"
        )
        parsed = parse_bricklink_xml(data)
        assert len(parsed.rows) == 1
        assert len(parsed.issues) == 1
        assert parsed.issues[0].code == "unsupported_item_type"

    def test_missing_minqty_is_a_row_issue(self) -> None:
        data = (
            b"<INVENTORY><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>3001</ITEMID>"
            b"<COLOR>0</COLOR></ITEM></INVENTORY>"
        )
        parsed = parse_bricklink_xml(data)
        assert parsed.rows == ()
        assert parsed.issues[0].code == "bad_quantity"

    def test_optional_wanted_list_fields_are_tolerated(self) -> None:
        data = (
            b"<INVENTORY><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>3001</ITEMID>"
            b"<COLOR>0</COLOR><MINQTY>1</MINQTY><CONDITION>N</CONDITION>"
            b"<NOTIFY>N</NOTIFY><REMARKS>test</REMARKS></ITEM></INVENTORY>"
        )
        parsed = parse_bricklink_xml(data)
        assert len(parsed.rows) == 1

    def test_wrong_root_element_is_fatal(self) -> None:
        with pytest.raises(InventoryImportError):
            parse_bricklink_xml(b"<WANTEDLIST></WANTEDLIST>")

    def test_malformed_xml_is_fatal(self) -> None:
        with pytest.raises(InventoryImportError):
            parse_bricklink_xml(b"<INVENTORY><ITEM></INVENTORY>")

    def test_doctype_is_rejected(self) -> None:
        data = b'<?xml version="1.0"?><!DOCTYPE foo><INVENTORY></INVENTORY>'
        with pytest.raises(InventoryImportError):
            parse_bricklink_xml(data)

    def test_row_cap_is_enforced(self) -> None:
        items = "".join(
            f"<ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>{n}</ITEMID><COLOR>0</COLOR>"
            f"<MINQTY>1</MINQTY></ITEM>"
            for n in range(5)
        )
        data = f"<INVENTORY>{items}</INVENTORY>".encode()
        with pytest.raises(InventoryImportError):
            parse_bricklink_xml(data, max_rows=3)


def test_real_fixtures_converge_on_row_count_and_total_quantity() -> None:
    """The committed samples are the same 249-row MOC exported both ways.
    Row order and source-namespace IDs differ per row (Rebrickable vs
    BrickLink part/color IDs are different namespaces), so this stage can
    only check the row-count and total-quantity invariants; true per-part
    convergence (same LDraw part+color quantities) is validated once the
    mapping-driven translation step (Phase B.3) lands."""
    rebrickable = parse_rebrickable_csv(REBRICKABLE_FIXTURE.read_bytes())
    bricklink = parse_bricklink_xml(BRICKLINK_FIXTURE.read_bytes())
    assert len(rebrickable.rows) == len(bricklink.rows)
    assert sum(row.quantity for row in rebrickable.rows) == sum(
        row.quantity for row in bricklink.rows
    )
