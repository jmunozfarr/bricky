from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal
from xml.etree import ElementTree

from app.services.inventory_import import (
    DEFAULT_MAX_CSV_ROWS,
    MAX_PART_ID_LENGTH,
    MAX_ROW_QUANTITY,
    InventoryImportError,
    RowIssue,
)

ImportFormat = Literal["native", "rebrickable", "bricklink"]

NATIVE_HEADER_COLUMNS = frozenset({"part_id", "color_code", "quantity"})
REBRICKABLE_HEADER_COLUMNS = frozenset({"part", "color", "quantity"})
_REBRICKABLE_REQUIRED_COLUMNS = ("part", "color", "quantity")
_REBRICKABLE_SPARE_COLUMN = "is spare"
_INTEGER_PATTERN = re.compile(r"-?[0-9]+")


@dataclass(frozen=True)
class ExternalRow:
    line_number: int
    source_part_id: str
    source_color_id: int
    quantity: int
    is_spare: bool


@dataclass(frozen=True)
class ParsedExternal:
    rows: tuple[ExternalRow, ...]
    issues: tuple[RowIssue, ...]
    total_data_rows: int
    spare_row_count: int


def _parse_integer(value: str) -> int | None:
    if _INTEGER_PATTERN.fullmatch(value) is None:
        return None
    return int(value)


def _decode_utf8(data: bytes, *, file_kind: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise InventoryImportError(
            f"The {file_kind} is not UTF-8 encoded; save it as UTF-8"
        ) from error


def detect_import_format(file_name: str, data: bytes) -> ImportFormat:
    """Deterministic format detection: extension first, then CSV header shape.

    The native and Rebrickable header column sets cannot collide
    (`part_id` vs `part`), so header inspection is unambiguous.
    """
    suffix = PurePosixPath(file_name).suffix.lower()
    if suffix == ".xml":
        return "bricklink"
    if suffix != ".csv":
        raise InventoryImportError("Only .csv or .xml files are supported")

    header = _sniff_csv_header(data)
    if NATIVE_HEADER_COLUMNS.issubset(header):
        return "native"
    if REBRICKABLE_HEADER_COLUMNS.issubset(header):
        return "rebrickable"
    raise InventoryImportError(
        "The CSV header must contain either part_id,color_code,quantity (native) "
        "or Part,Color,Quantity (Rebrickable) columns"
    )


def _sniff_csv_header(data: bytes) -> frozenset[str]:
    text = _decode_utf8(data, file_kind="CSV")
    reader = csv.reader(io.StringIO(text, newline=""))
    header_row = next((row for row in reader if any(cell.strip() for cell in row)), None)
    if header_row is None:
        raise InventoryImportError("The CSV has no header row")
    return frozenset(cell.strip().lower() for cell in header_row)


def _find_columns(
    header_row: list[str], required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> dict[str, int]:
    column_index: dict[str, int] = {}
    for index, cell in enumerate(header_row):
        name = cell.strip().lower()
        if (name in required or name in optional) and name not in column_index:
            column_index[name] = index
    missing = [name for name in required if name not in column_index]
    if missing:
        raise InventoryImportError(
            f"The CSV header is missing required column(s): {', '.join(missing)}"
        )
    return column_index


def _cell(row: list[str], index: int) -> str:
    return row[index].strip() if index < len(row) else ""


def _validate_rebrickable_row(
    row: list[str], line_number: int, column_index: dict[str, int]
) -> ExternalRow | RowIssue:
    required_width = max(column_index.values()) + 1
    if len(row) < required_width:
        return RowIssue(
            line_number,
            "wrong_field_count",
            f"Row has {len(row)} column(s); expected at least {required_width}",
        )
    part_id = _cell(row, column_index["part"])
    if not part_id:
        return RowIssue(line_number, "missing_part_id", "The Part column is empty")
    if len(part_id) > MAX_PART_ID_LENGTH:
        return RowIssue(
            line_number, "bad_part_id", f"Part ID exceeds {MAX_PART_ID_LENGTH} characters"
        )
    raw_color = _cell(row, column_index["color"])
    color_id = _parse_integer(raw_color)
    if color_id is None or color_id < 0:
        return RowIssue(
            line_number,
            "bad_color_code",
            f"Color {raw_color!r} is not a non-negative integer",
        )
    raw_quantity = _cell(row, column_index["quantity"])
    quantity = _parse_integer(raw_quantity)
    if quantity is None or not 1 <= quantity <= MAX_ROW_QUANTITY:
        return RowIssue(
            line_number,
            "bad_quantity",
            f"Quantity {raw_quantity!r} must be an integer between 1 and {MAX_ROW_QUANTITY}",
        )
    is_spare = False
    spare_index = column_index.get(_REBRICKABLE_SPARE_COLUMN)
    if spare_index is not None:
        is_spare = _cell(row, spare_index).strip().lower() == "true"
    return ExternalRow(line_number, part_id, color_id, quantity, is_spare)


def parse_rebrickable_csv(data: bytes, *, max_rows: int = DEFAULT_MAX_CSV_ROWS) -> ParsedExternal:
    """Rebrickable MOC parts export: `Part,Color,Quantity,Is Spare` header.

    Rebrickable- and BrickLink-namespace IDs pass through unchanged here —
    translation into LDraw part/color identifiers happens later in
    `translate_external_rows`, which also owns the non-physical-color check.
    """
    text = _decode_utf8(data, file_kind="CSV")
    reader = csv.reader(io.StringIO(text, newline=""))
    rows: list[ExternalRow] = []
    issues: list[RowIssue] = []
    total_data_rows = 0
    spare_row_count = 0
    try:
        header_row = next((row for row in reader if any(cell.strip() for cell in row)), None)
        if header_row is None:
            raise InventoryImportError("The CSV has no header row")
        column_index = _find_columns(
            header_row, _REBRICKABLE_REQUIRED_COLUMNS, (_REBRICKABLE_SPARE_COLUMN,)
        )

        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            total_data_rows += 1
            if total_data_rows > max_rows:
                raise InventoryImportError(f"The CSV has more than {max_rows} data rows")
            result = _validate_rebrickable_row(row, reader.line_num, column_index)
            if isinstance(result, RowIssue):
                issues.append(result)
            else:
                rows.append(result)
                if result.is_spare:
                    spare_row_count += 1
    except csv.Error as error:
        raise InventoryImportError(f"The CSV structure is malformed: {error}") from error

    return ParsedExternal(tuple(rows), tuple(issues), total_data_rows, spare_row_count)


def _element_text(item: ElementTree.Element, tag: str) -> str | None:
    child = item.find(tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def _validate_bricklink_item(item: ElementTree.Element, line_number: int) -> ExternalRow | RowIssue:
    item_type = _element_text(item, "ITEMTYPE")
    if item_type != "P":
        return RowIssue(
            line_number,
            "unsupported_item_type",
            f"Item type {item_type!r} is not a part (ITEMTYPE=P)",
        )
    part_id = _element_text(item, "ITEMID")
    if not part_id:
        return RowIssue(line_number, "missing_part_id", "The ITEMID element is empty or missing")
    if len(part_id) > MAX_PART_ID_LENGTH:
        return RowIssue(
            line_number, "bad_part_id", f"Part ID exceeds {MAX_PART_ID_LENGTH} characters"
        )
    raw_color = _element_text(item, "COLOR")
    color_id = _parse_integer(raw_color) if raw_color is not None else None
    if color_id is None or color_id < 0:
        return RowIssue(
            line_number,
            "bad_color_code",
            f"Color {raw_color!r} is not a non-negative integer",
        )
    raw_quantity = _element_text(item, "MINQTY")
    quantity = _parse_integer(raw_quantity) if raw_quantity is not None else None
    if quantity is None or not 1 <= quantity <= MAX_ROW_QUANTITY:
        return RowIssue(
            line_number,
            "bad_quantity",
            f"MINQTY {raw_quantity!r} must be an integer between 1 and {MAX_ROW_QUANTITY}",
        )
    return ExternalRow(line_number, part_id, color_id, quantity, False)


def parse_bricklink_xml(data: bytes, *, max_rows: int = DEFAULT_MAX_CSV_ROWS) -> ParsedExternal:
    """BrickLink wanted-list export: a single `<INVENTORY>` of `<ITEM>` rows.

    BrickLink has no spare-part concept, so `spare_row_count` is always 0.
    `line_number` is the 1-based item ordinal (real exports are one line).
    """
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise InventoryImportError("The XML must not declare a DOCTYPE or custom entities")
    text = _decode_utf8(data, file_kind="XML")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise InventoryImportError(f"The XML structure is malformed: {error}") from error
    if root.tag != "INVENTORY":
        raise InventoryImportError("The XML root element must be <INVENTORY>")

    rows: list[ExternalRow] = []
    issues: list[RowIssue] = []
    total_data_rows = 0
    for line_number, item in enumerate(root.findall("ITEM"), start=1):
        total_data_rows += 1
        if total_data_rows > max_rows:
            raise InventoryImportError(f"The XML has more than {max_rows} items")
        result = _validate_bricklink_item(item, line_number)
        if isinstance(result, RowIssue):
            issues.append(result)
        else:
            rows.append(result)

    return ParsedExternal(tuple(rows), tuple(issues), total_data_rows, 0)
