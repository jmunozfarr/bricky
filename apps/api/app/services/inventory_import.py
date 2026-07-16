from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable, Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Any, BinaryIO, Literal

from sqlalchemy import SQLColumnExpression, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import InventoryItem, LDrawColor, Part
from app.services.model_coverage import normalize_part_id

Strategy = Literal["add", "replace"]
ChangeKind = Literal["create", "update", "unchanged"]
# "unmapped" is external-format only: the source ID has no entry in the
# Rebrickable/BrickLink -> LDraw mapping table, checked strictly (a raw ID
# that coincidentally matches the installed catalog is still "unmapped" —
# the mapping table is authoritative once populated). Takes precedence over
# "part"/"color", which describe an already-LDraw-namespace ID that is
# merely missing from the (rebuildable) installed catalog.
UnknownReason = Literal["part", "color", "unmapped"]
# Maps raw source part IDs to canonical official IDs; entries may be omitted
# for identities, callers fall back to the raw ID.
AliasMap = Callable[[set[str]], Mapping[str, str]]

DEFAULT_MAX_CSV_UPLOAD_BYTES = 1024 * 1024
DEFAULT_MAX_CSV_ROWS = 20_000
# Matches the per-request Quantity bound enforced by the inventory API; the
# database itself only checks quantity > 0.
MAX_ROW_QUANTITY = 999_999
MAX_PART_ID_LENGTH = 64
NON_PHYSICAL_COLOR_CODES = frozenset({16, 24})
REQUIRED_COLUMNS = ("part_id", "color_code", "quantity")
# psycopg uses server-side binding with a 65,535-parameter ceiling; four
# parameters per row keeps 5,000-row chunks comfortably below it.
_UPSERT_CHUNK_ROWS = 5_000
_INTEGER_PATTERN = re.compile(r"-?[0-9]+")


class InventoryImportError(Exception):
    """Safe import error suitable for an HTTP 422 response."""


class InventoryImportTooLargeError(InventoryImportError):
    pass


@dataclass(frozen=True)
class CsvRow:
    line_number: int
    part_id: str
    color_code: int
    quantity: int


@dataclass(frozen=True)
class RowIssue:
    line_number: int
    code: str
    message: str


@dataclass(frozen=True)
class ParsedCsv:
    rows: tuple[CsvRow, ...]
    issues: tuple[RowIssue, ...]
    total_data_rows: int
    ignored_columns: tuple[str, ...]


@dataclass(frozen=True)
class PlannedChange:
    part_id: str
    """The spelling that will persist: existing row > catalog canonical > lowercase."""

    normalized_part_id: str
    color_code: int
    source_part_ids: tuple[str, ...]
    canonicalized_from: str | None
    quantity: int
    current_quantity: int
    resulting_quantity: int
    change: ChangeKind
    unknown_reason: UnknownReason | None


@dataclass(frozen=True)
class ImportPlan:
    strategy: Strategy
    changes: tuple[PlannedChange, ...]
    issues: tuple[RowIssue, ...]
    total_data_rows: int
    duplicate_row_count: int
    ignored_columns: tuple[str, ...]


@dataclass(frozen=True)
class BucketSummary:
    row_count: int
    create_count: int
    update_count: int
    unchanged_count: int
    quantity_delta: int
    missing_part_count: int
    missing_color_count: int
    missing_mapping_count: int


@dataclass(frozen=True)
class AppliedCounts:
    applied_rows: int
    created: int
    updated: int
    unchanged: int
    skipped_unknown: int
    quantity_delta: int


def read_csv_upload(source: BinaryIO, maximum_bytes: int) -> bytes:
    if maximum_bytes <= 0:
        raise InventoryImportError("Configured upload limit must be positive")
    buffer = io.BytesIO()
    total = 0
    while chunk := source.read(1024 * 1024):
        total += len(chunk)
        if total > maximum_bytes:
            raise InventoryImportTooLargeError(
                f"CSV exceeds the configured {maximum_bytes}-byte upload limit"
            )
        buffer.write(chunk)
    if total == 0:
        raise InventoryImportError("The uploaded CSV is empty")
    return buffer.getvalue()


def _parse_integer(value: str) -> int | None:
    if _INTEGER_PATTERN.fullmatch(value) is None:
        return None
    return int(value)


def _header_columns(header_row: list[str]) -> tuple[dict[str, int], tuple[str, ...]]:
    column_index: dict[str, int] = {}
    ignored: list[str] = []
    for index, cell in enumerate(header_row):
        name = cell.strip().lower()
        if name in REQUIRED_COLUMNS and name not in column_index:
            column_index[name] = index
        elif name:
            ignored.append(cell.strip())
    missing = [name for name in REQUIRED_COLUMNS if name not in column_index]
    if missing:
        raise InventoryImportError(
            f"The CSV header is missing required column(s): {', '.join(missing)}"
        )
    return column_index, tuple(ignored)


def _row_value(row: list[str], index: int) -> str:
    return row[index].strip() if index < len(row) else ""


def _validate_row(
    row: list[str], line_number: int, column_index: dict[str, int]
) -> CsvRow | RowIssue:
    required_width = max(column_index.values()) + 1
    if len(row) < required_width:
        return RowIssue(
            line_number,
            "wrong_field_count",
            f"Row has {len(row)} column(s); expected at least {required_width}",
        )
    part_id = _row_value(row, column_index["part_id"])
    if not part_id:
        return RowIssue(line_number, "missing_part_id", "The part_id column is empty")
    if len(part_id) > MAX_PART_ID_LENGTH:
        return RowIssue(
            line_number,
            "bad_part_id",
            f"Part ID exceeds {MAX_PART_ID_LENGTH} characters",
        )
    raw_color = _row_value(row, column_index["color_code"])
    color_code = _parse_integer(raw_color)
    if color_code is None or color_code < 0:
        return RowIssue(
            line_number,
            "bad_color_code",
            f"Color code {raw_color!r} is not a non-negative integer",
        )
    if color_code in NON_PHYSICAL_COLOR_CODES:
        return RowIssue(
            line_number,
            "non_physical_color",
            f"Color {color_code} is an LDraw placeholder, not a physical color",
        )
    raw_quantity = _row_value(row, column_index["quantity"])
    quantity = _parse_integer(raw_quantity)
    if quantity is None or not 1 <= quantity <= MAX_ROW_QUANTITY:
        return RowIssue(
            line_number,
            "bad_quantity",
            f"Quantity {raw_quantity!r} must be an integer between 1 and {MAX_ROW_QUANTITY}",
        )
    return CsvRow(line_number, part_id, color_code, quantity)


def parse_inventory_csv(data: bytes, *, max_rows: int = DEFAULT_MAX_CSV_ROWS) -> ParsedCsv:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise InventoryImportError(
            "The CSV is not UTF-8 encoded; save it as CSV UTF-8 (comma delimited)"
        ) from error

    reader = csv.reader(io.StringIO(text, newline=""))
    rows: list[CsvRow] = []
    issues: list[RowIssue] = []
    total_data_rows = 0
    try:
        header_row = next(
            (row for row in reader if any(cell.strip() for cell in row)),
            None,
        )
        if header_row is None:
            raise InventoryImportError("The CSV has no header row")
        column_index, ignored_columns = _header_columns(header_row)

        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            total_data_rows += 1
            if total_data_rows > max_rows:
                raise InventoryImportError(f"The CSV has more than {max_rows} data rows")
            result = _validate_row(row, reader.line_num, column_index)
            if isinstance(result, RowIssue):
                issues.append(result)
            else:
                rows.append(result)
    except csv.Error as error:
        raise InventoryImportError(f"The CSV structure is malformed: {error}") from error

    return ParsedCsv(tuple(rows), tuple(issues), total_data_rows, ignored_columns)


@dataclass
class _PendingKey:
    quantity: int
    source_part_ids: list[str]
    canonicalized_from: str | None


def plan_inventory_import(
    parsed: ParsedCsv,
    strategy: Strategy,
    *,
    canonical_by_source: Mapping[str, str],
    catalog_casing_by_normalized: Mapping[str, str],
    known_color_codes: AbstractSet[int],
    current_rows: Mapping[tuple[str, int], tuple[str, int]],
    mapped_source_part_ids: AbstractSet[str] | None = None,
) -> ImportPlan:
    """`mapped_source_part_ids` is external-format only (native/Phase A callers
    leave it `None`): when given, a row whose raw `part_id` is absent is
    "unmapped" regardless of catalog contents, and is grouped/persisted under
    its raw source ID rather than falling back through `canonical_by_source`
    (which would risk a spurious match against a coincidentally-identical
    LDraw ID)."""
    pending: dict[tuple[str, int], _PendingKey] = {}
    duplicate_row_count = 0
    unmapped_keys: set[tuple[str, int]] = set()
    for row in parsed.rows:
        if mapped_source_part_ids is not None and row.part_id not in mapped_source_part_ids:
            canonical = row.part_id
        else:
            canonical = canonical_by_source.get(row.part_id, row.part_id)
        normalized = normalize_part_id(canonical)
        key = (normalized, row.color_code)
        if mapped_source_part_ids is not None and row.part_id not in mapped_source_part_ids:
            unmapped_keys.add(key)
        entry = pending.get(key)
        if entry is None:
            entry = pending[key] = _PendingKey(0, [], None)
        else:
            duplicate_row_count += 1
        entry.quantity = min(entry.quantity + row.quantity, MAX_ROW_QUANTITY)
        if row.part_id not in entry.source_part_ids:
            entry.source_part_ids.append(row.part_id)
        if entry.canonicalized_from is None and normalize_part_id(row.part_id) != normalized:
            entry.canonicalized_from = row.part_id

    changes: list[PlannedChange] = []
    for (normalized, color_code), entry in sorted(pending.items(), key=lambda item: item[0]):
        catalog_casing = catalog_casing_by_normalized.get(normalized)
        existing = current_rows.get((normalized, color_code))
        current_quantity = existing[1] if existing is not None else 0
        unknown_reason: UnknownReason | None = None
        if (normalized, color_code) in unmapped_keys:
            unknown_reason = "unmapped"
        elif catalog_casing is None:
            unknown_reason = "part"
        elif color_code not in known_color_codes:
            unknown_reason = "color"
        if existing is not None:
            persisted_part_id = existing[0]
        elif catalog_casing is not None:
            persisted_part_id = catalog_casing
        else:
            persisted_part_id = normalized
        if strategy == "add":
            resulting_quantity = min(current_quantity + entry.quantity, MAX_ROW_QUANTITY)
        else:
            resulting_quantity = entry.quantity
        change: ChangeKind
        if current_quantity == 0:
            change = "create"
        elif resulting_quantity == current_quantity:
            change = "unchanged"
        else:
            change = "update"
        changes.append(
            PlannedChange(
                part_id=persisted_part_id,
                normalized_part_id=normalized,
                color_code=color_code,
                source_part_ids=tuple(entry.source_part_ids),
                canonicalized_from=entry.canonicalized_from,
                quantity=entry.quantity,
                current_quantity=current_quantity,
                resulting_quantity=resulting_quantity,
                change=change,
                unknown_reason=unknown_reason,
            )
        )

    return ImportPlan(
        strategy=strategy,
        changes=tuple(changes),
        issues=parsed.issues,
        total_data_rows=parsed.total_data_rows,
        duplicate_row_count=duplicate_row_count,
        ignored_columns=parsed.ignored_columns,
    )


def build_import_plan(
    session: Session,
    workspace_id: int,
    parsed: ParsedCsv,
    strategy: Strategy,
    resolve_aliases: AliasMap,
    *,
    require_explicit_mapping: bool = False,
) -> ImportPlan:
    """Shared preview/apply orchestration: bounded lookups feeding the pure planner.

    `require_explicit_mapping=True` is the external-format path: `resolve_aliases`
    must then return an entry for every raw ID it successfully mapped (no
    identity omission, unlike the native `~Moved to` resolver's contract),
    so `canonical_by_source.keys()` doubles as the mapped-ID set passed to
    the planner.
    """
    raw_part_ids = {row.part_id for row in parsed.rows}
    canonical_by_source = dict(resolve_aliases(raw_part_ids)) if raw_part_ids else {}
    keys = sorted(
        {
            (
                normalize_part_id(canonical_by_source.get(row.part_id, row.part_id)),
                row.color_code,
            )
            for row in parsed.rows
        }
    )

    catalog_casing_by_normalized: dict[str, str] = {}
    normalized_ids = sorted({normalized for normalized, _ in keys})
    if normalized_ids:
        catalog_casing_by_normalized = {
            normalize_part_id(part_id): part_id
            for part_id in session.scalars(
                select(Part.part_id).where(
                    func.lower(Part.part_id).in_(normalized_ids),
                    Part.is_subpart.is_(False),
                )
            )
        }
    known_color_codes = frozenset(session.scalars(select(LDrawColor.code)))

    current_rows: dict[tuple[str, int], tuple[str, int]] = {}
    if keys:
        for part_id, color_code, quantity in session.execute(
            select(
                InventoryItem.part_id,
                InventoryItem.color_code,
                InventoryItem.quantity,
            )
            .where(
                InventoryItem.workspace_id == workspace_id,
                tuple_(
                    func.lower(func.trim(InventoryItem.part_id)),
                    InventoryItem.color_code,
                ).in_(keys),
            )
            .order_by(InventoryItem.id)
        ):
            current_rows.setdefault((normalize_part_id(part_id), color_code), (part_id, quantity))

    return plan_inventory_import(
        parsed,
        strategy,
        canonical_by_source=canonical_by_source,
        catalog_casing_by_normalized=catalog_casing_by_normalized,
        known_color_codes=known_color_codes,
        current_rows=current_rows,
        mapped_source_part_ids=frozenset(canonical_by_source) if require_explicit_mapping else None,
    )


def summarize_changes(changes: Iterable[PlannedChange]) -> BucketSummary:
    materialized = tuple(changes)
    return BucketSummary(
        row_count=len(materialized),
        create_count=sum(1 for change in materialized if change.change == "create"),
        update_count=sum(1 for change in materialized if change.change == "update"),
        unchanged_count=sum(1 for change in materialized if change.change == "unchanged"),
        quantity_delta=sum(
            change.resulting_quantity - change.current_quantity for change in materialized
        ),
        missing_part_count=sum(1 for change in materialized if change.unknown_reason == "part"),
        missing_color_count=sum(1 for change in materialized if change.unknown_reason == "color"),
        missing_mapping_count=sum(
            1 for change in materialized if change.unknown_reason == "unmapped"
        ),
    )


def apply_import_plan(
    session: Session,
    workspace_id: int,
    plan: ImportPlan,
    *,
    include_unknown: bool,
) -> AppliedCounts:
    """Execute the plan's batched upsert; the caller owns the commit."""
    applicable = [
        change for change in plan.changes if include_unknown or change.unknown_reason is None
    ]
    for start in range(0, len(applicable), _UPSERT_CHUNK_ROWS):
        chunk = applicable[start : start + _UPSERT_CHUNK_ROWS]
        statement = insert(InventoryItem).values(
            [
                {
                    "workspace_id": workspace_id,
                    "part_id": change.part_id,
                    "color_code": change.color_code,
                    "quantity": change.quantity,
                }
                for change in chunk
            ]
        )
        updated_quantity: SQLColumnExpression[Any]
        if plan.strategy == "add":
            updated_quantity = func.least(
                InventoryItem.quantity + statement.excluded.quantity, MAX_ROW_QUANTITY
            )
        else:
            updated_quantity = statement.excluded.quantity
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    InventoryItem.workspace_id,
                    InventoryItem.part_id,
                    InventoryItem.color_code,
                ],
                set_={"quantity": updated_quantity, "updated_at": func.now()},
            )
        )
    summary = summarize_changes(applicable)
    return AppliedCounts(
        applied_rows=summary.row_count,
        created=summary.create_count,
        updated=summary.update_count,
        unchanged=summary.unchanged_count,
        skipped_unknown=len(plan.changes) - len(applicable),
        quantity_delta=summary.quantity_delta,
    )
