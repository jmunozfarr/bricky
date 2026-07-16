from __future__ import annotations

from pydantic import Field

from app.schemas import CamelModel
from app.services.inventory_import import ChangeKind, Strategy, UnknownReason
from app.services.inventory_import_formats import ImportFormat


class ImportBucketSummaryResponse(CamelModel):
    row_count: int
    create_count: int
    update_count: int
    unchanged_count: int
    quantity_delta: int
    missing_part_count: int
    missing_color_count: int
    missing_mapping_count: int


class ImportPreviewRowResponse(CamelModel):
    part_id: str
    source_part_id: str
    canonicalized_from: str | None
    color_code: int
    quantity: int
    current_quantity: int
    resulting_quantity: int
    change: ChangeKind
    unknown_reason: UnknownReason | None
    part_name: str | None
    color_name: str | None
    color_hex: str | None
    alpha: int | None
    render_asset_url: str | None


class ImportRowIssueResponse(CamelModel):
    line_number: int
    code: str
    message: str


class InventoryImportPreviewResponse(CamelModel):
    file_name: str
    format: ImportFormat
    strategy: Strategy
    total_data_rows: int
    planned_row_count: int
    duplicate_row_count: int
    alias_canonicalized_count: int
    ignored_columns: list[str]
    invalid_row_count: int
    spare_row_count: int
    mapping_available: bool
    known: ImportBucketSummaryResponse
    unknown: ImportBucketSummaryResponse
    rows: list[ImportPreviewRowResponse]
    rows_truncated: bool
    issues: list[ImportRowIssueResponse]
    issues_truncated: bool
    # Only present for format == "set": the official set catalog vs. what
    # this app could actually expand (nested sub-inventories/minifigs are
    # not resolved, see docs/BULK_INVENTORY.md).
    set_num: str | None = None
    set_name: str | None = None
    official_part_count: int | None = None
    expanded_quantity: int | None = None


class InventoryImportApplyResponse(CamelModel):
    format: ImportFormat
    strategy: Strategy
    include_unknown: bool
    applied_row_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    skipped_unknown_row_count: int
    invalid_row_count: int
    quantity_delta: int
    set_num: str | None = None
    set_name: str | None = None


class SetImportPreviewRequest(CamelModel):
    set_num: str = Field(min_length=1, max_length=32)
    strategy: Strategy


class SetImportApplyRequest(CamelModel):
    set_num: str = Field(min_length=1, max_length=32)
    strategy: Strategy
    include_unknown: bool
