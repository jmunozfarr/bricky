from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from xml.etree import ElementTree

from app.services.model_coverage import normalize_part_id

CSV_HEADER = ("part_id", "color_code", "quantity", "part_name", "color_name")


@dataclass(frozen=True)
class MissingPartRow:
    """One LDraw-namespace missing-quantity row (part/color already resolved
    against the catalog for display)."""

    part_id: str
    color_code: int
    quantity: int
    part_name: str
    color_name: str


@dataclass(frozen=True)
class BrickLinkExportRow:
    """One BrickLink-namespace row, ready to serialize into a wanted-list
    `<ITEM>`."""

    source_part_id: str
    source_color_id: int
    quantity: int


@dataclass(frozen=True)
class BrickLinkExportResult:
    rows: tuple[BrickLinkExportRow, ...]
    skipped_count: int
    total_count: int


def write_missing_parts_csv(rows: Iterable[MissingPartRow]) -> str:
    """`part_id,color_code,quantity` plus display extras — the required
    columns exactly match the native import format
    (`apps/api/app/services/inventory_import.py`), so the file the user buys
    against can be re-imported unchanged to add the parts to inventory."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow([row.part_id, row.color_code, row.quantity, row.part_name, row.color_name])
    return buffer.getvalue()


def resolve_bricklink_export_rows(
    items: Iterable[MissingPartRow],
    *,
    part_map: Mapping[str, str],
    color_map: Mapping[int, int],
) -> BrickLinkExportResult:
    """Translate LDraw-namespace missing rows into BrickLink-namespace rows
    using already-resolved reverse-mapping dicts (session-bound lookups
    happen in the caller, via `rebrickable_mapping.load_reverse_*`). A row
    missing either its part or color mapping is dropped, not guessed at."""
    rows: list[BrickLinkExportRow] = []
    total = 0
    for item in items:
        total += 1
        source_part_id = part_map.get(normalize_part_id(item.part_id))
        source_color_id = color_map.get(item.color_code)
        if source_part_id is None or source_color_id is None:
            continue
        rows.append(BrickLinkExportRow(source_part_id, source_color_id, item.quantity))
    return BrickLinkExportResult(
        rows=tuple(rows), skipped_count=total - len(rows), total_count=total
    )


def write_bricklink_wanted_list_xml(rows: Iterable[BrickLinkExportRow]) -> str:
    """`<INVENTORY>` of `<ITEM>` elements using the exact element vocabulary
    `parse_bricklink_xml` (`apps/api/app/services/inventory_import_formats.py`)
    already reads (`ITEMTYPE`=`P`, `ITEMID`, `COLOR`, `MINQTY`), so a
    re-uploaded export round-trips through the existing BrickLink parser."""
    root = ElementTree.Element("INVENTORY")
    for row in rows:
        item = ElementTree.SubElement(root, "ITEM")
        ElementTree.SubElement(item, "ITEMTYPE").text = "P"
        ElementTree.SubElement(item, "ITEMID").text = row.source_part_id
        ElementTree.SubElement(item, "COLOR").text = str(row.source_color_id)
        ElementTree.SubElement(item, "MINQTY").text = str(row.quantity)
    return ElementTree.tostring(root, encoding="unicode")
