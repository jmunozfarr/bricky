from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.services.model_coverage import CoverageStatus


class CoverageSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_required_quantity: int = Field(alias="totalRequiredQuantity")
    total_available_quantity: int = Field(alias="totalAvailableQuantity")
    total_missing_quantity: int = Field(alias="totalMissingQuantity")
    unique_item_count: int = Field(alias="uniqueItemCount")
    complete_item_count: int = Field(alias="completeItemCount")
    partial_item_count: int = Field(alias="partialItemCount")
    missing_item_count: int = Field(alias="missingItemCount")
    piece_coverage_percentage: float = Field(alias="pieceCoveragePercentage")
    fully_buildable: bool = Field(alias="fullyBuildable")


class ModelSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_id: uuid.UUID = Field(alias="modelId")
    name: str
    original_filename: str = Field(alias="originalFilename")
    source_format: str = Field(alias="sourceFormat")
    import_status: str = Field(alias="importStatus")
    declared_step_count: int = Field(alias="declaredStepCount")
    total_part_quantity: int = Field(alias="totalPartQuantity")
    unique_part_color_count: int = Field(alias="uniquePartColorCount")
    unresolved_reference_count: int = Field(alias="unresolvedReferenceCount")
    created_at: datetime = Field(alias="createdAt")
    coverage: CoverageSummaryResponse | None = None


class ModelsPageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[ModelSummaryResponse]
    page: int
    page_size: int = Field(alias="pageSize")
    total_items: int = Field(alias="totalItems")
    total_pages: int = Field(alias="totalPages")


class ModelBomItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    part_id: str = Field(alias="partId")
    part_name: str = Field(alias="partName")
    category: str
    color_code: int = Field(alias="colorCode")
    color_name: str = Field(alias="colorName")
    color_hex: str | None = Field(alias="colorHex")
    quantity: int
    catalog_available: bool = Field(alias="catalogAvailable")
    render_asset_url: str | None = Field(alias="renderAssetUrl")


class ModelIssueResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    severity: str
    code: str
    message: str
    referenced_filename: str | None = Field(alias="referencedFilename")


class ModelDetailResponse(ModelSummaryResponse):
    model_config = ConfigDict(populate_by_name=True)

    source_sha256: str = Field(alias="sourceSha256")
    source_url: str = Field(alias="sourceUrl")
    updated_at: datetime = Field(alias="updatedAt")
    bom: list[ModelBomItemResponse]
    issues: list[ModelIssueResponse]


class ModelCoverageItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    part_id: str = Field(alias="partId")
    part_name: str = Field(alias="partName")
    category: str
    color_code: int = Field(alias="colorCode")
    color_name: str = Field(alias="colorName")
    color_hex: str | None = Field(alias="colorHex")
    required_quantity: int = Field(alias="requiredQuantity")
    owned_quantity: int = Field(alias="ownedQuantity")
    available_quantity: int = Field(alias="availableQuantity")
    missing_quantity: int = Field(alias="missingQuantity")
    coverage_percentage: float = Field(alias="coveragePercentage")
    status: CoverageStatus
    catalog_available: bool = Field(alias="catalogAvailable")
    render_asset_url: str | None = Field(alias="renderAssetUrl")


class ModelCoverageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_id: uuid.UUID = Field(alias="modelId")
    summary: CoverageSummaryResponse
    items: list[ModelCoverageItemResponse]


class ModelsReadinessResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_models: int = Field(alias="totalModels")
    fully_buildable_models: int = Field(alias="fullyBuildableModels")
    incomplete_models: int = Field(alias="incompleteModels")
    total_missing_quantity: int = Field(alias="totalMissingQuantity")
