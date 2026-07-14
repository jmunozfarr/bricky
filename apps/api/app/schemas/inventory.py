from __future__ import annotations

from app.schemas import CamelModel
from app.services.inventory_import import ChangeKind, Strategy, UnknownReason


class ImportBucketSummaryResponse(CamelModel):
    row_count: int
    create_count: int
    update_count: int
    unchanged_count: int
    quantity_delta: int
    missing_part_count: int
    missing_color_count: int


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
    strategy: Strategy
    total_data_rows: int
    planned_row_count: int
    duplicate_row_count: int
    alias_canonicalized_count: int
    ignored_columns: list[str]
    invalid_row_count: int
    known: ImportBucketSummaryResponse
    unknown: ImportBucketSummaryResponse
    rows: list[ImportPreviewRowResponse]
    rows_truncated: bool
    issues: list[ImportRowIssueResponse]
    issues_truncated: bool


class InventoryImportApplyResponse(CamelModel):
    strategy: Strategy
    include_unknown: bool
    applied_row_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    skipped_unknown_row_count: int
    invalid_row_count: int
    quantity_delta: int
