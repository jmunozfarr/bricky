from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas import CamelModel
from app.services.model_coverage import CoverageStatus


class CoverageSummaryResponse(CamelModel):
    total_required_quantity: int
    total_available_quantity: int
    total_missing_quantity: int
    unique_item_count: int
    complete_item_count: int
    partial_item_count: int
    missing_item_count: int
    piece_coverage_percentage: float
    fully_buildable: bool


class ModelSummaryResponse(CamelModel):
    model_id: uuid.UUID
    name: str
    original_filename: str
    source_format: str
    import_status: str
    declared_step_count: int
    total_part_quantity: int
    unique_part_color_count: int
    unresolved_reference_count: int
    created_at: datetime
    coverage: CoverageSummaryResponse | None = None


class ModelsPageResponse(CamelModel):
    items: list[ModelSummaryResponse]
    page: int
    page_size: int
    total_items: int
    total_pages: int


class ModelBomItemResponse(CamelModel):
    part_id: str
    part_name: str
    category: str
    color_code: int
    color_name: str
    color_hex: str | None
    quantity: int
    catalog_available: bool
    render_asset_url: str | None


class ModelIssueResponse(CamelModel):
    severity: str
    code: str
    message: str
    referenced_filename: str | None
    occurrence_count: int


class ModelResolutionRequest(CamelModel):
    source_reference: str = Field(min_length=1, max_length=255)
    action: Literal["map", "ignore"]
    part_id: str | None = Field(default=None, max_length=64)
    color_code: int | None = None


class ModelResolutionResponse(CamelModel):
    source_reference: str
    action: str
    part_id: str | None
    color_code: int | None


class ModelDetailResponse(ModelSummaryResponse):
    source_sha256: str
    source_url: str
    updated_at: datetime
    bom: list[ModelBomItemResponse]
    issues: list[ModelIssueResponse]
    resolutions: list[ModelResolutionResponse]


class ModelCoverageItemResponse(CamelModel):
    part_id: str
    part_name: str
    category: str
    color_code: int
    color_name: str
    color_hex: str | None
    required_quantity: int
    owned_quantity: int
    available_quantity: int
    missing_quantity: int
    coverage_percentage: float
    status: CoverageStatus
    catalog_available: bool
    render_asset_url: str | None


class ModelCoverageResponse(CamelModel):
    model_id: uuid.UUID
    summary: CoverageSummaryResponse
    items: list[ModelCoverageItemResponse]


class ModelsReadinessResponse(CamelModel):
    total_models: int
    fully_buildable_models: int
    incomplete_models: int
    total_missing_quantity: int
