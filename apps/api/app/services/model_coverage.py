from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

CoverageStatus = Literal["complete", "partial", "missing"]


@dataclass(frozen=True)
class CoverageRequirement:
    part_id: str
    color_code: int
    required_quantity: int


@dataclass(frozen=True)
class InventoryQuantity:
    part_id: str
    color_code: int
    owned_quantity: int


@dataclass(frozen=True)
class CoverageItem:
    part_id: str
    color_code: int
    required_quantity: int
    owned_quantity: int
    available_quantity: int
    missing_quantity: int
    coverage_percentage: float
    status: CoverageStatus


@dataclass(frozen=True)
class CoverageSummary:
    total_required_quantity: int
    total_available_quantity: int
    total_missing_quantity: int
    unique_item_count: int
    complete_item_count: int
    partial_item_count: int
    missing_item_count: int
    piece_coverage_percentage: float
    fully_buildable: bool


@dataclass(frozen=True)
class ModelCoverage:
    summary: CoverageSummary
    items: tuple[CoverageItem, ...]


def normalize_part_id(part_id: str) -> str:
    """Return the case-insensitive natural key used by LDraw identifiers."""

    return part_id.strip().lower()


def percentage(numerator: int, denominator: int) -> float:
    """Round a percentage half-up to two decimal places.

    An empty requirement is considered fully covered and therefore returns 100.
    """

    if denominator <= 0:
        return 100.0
    value = (Decimal(numerator) * Decimal(100)) / Decimal(denominator)
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculate_model_coverage(
    requirements: Iterable[CoverageRequirement],
    inventory: Iterable[InventoryQuantity],
) -> ModelCoverage:
    owned_by_key: defaultdict[tuple[str, int], int] = defaultdict(int)
    for item in inventory:
        owned_by_key[(normalize_part_id(item.part_id), item.color_code)] += max(
            item.owned_quantity, 0
        )

    coverage_items: list[CoverageItem] = []
    for requirement in requirements:
        if requirement.required_quantity <= 0:
            raise ValueError("Required quantities must be positive")
        owned = owned_by_key[(normalize_part_id(requirement.part_id), requirement.color_code)]
        available = min(requirement.required_quantity, owned)
        missing = max(requirement.required_quantity - owned, 0)
        status: CoverageStatus
        if owned >= requirement.required_quantity:
            status = "complete"
        elif owned > 0:
            status = "partial"
        else:
            status = "missing"
        coverage_items.append(
            CoverageItem(
                part_id=requirement.part_id,
                color_code=requirement.color_code,
                required_quantity=requirement.required_quantity,
                owned_quantity=owned,
                available_quantity=available,
                missing_quantity=missing,
                coverage_percentage=percentage(available, requirement.required_quantity),
                status=status,
            )
        )

    total_required = sum(item.required_quantity for item in coverage_items)
    total_available = sum(item.available_quantity for item in coverage_items)
    total_missing = sum(item.missing_quantity for item in coverage_items)
    summary = CoverageSummary(
        total_required_quantity=total_required,
        total_available_quantity=total_available,
        total_missing_quantity=total_missing,
        unique_item_count=len(coverage_items),
        complete_item_count=sum(item.status == "complete" for item in coverage_items),
        partial_item_count=sum(item.status == "partial" for item in coverage_items),
        missing_item_count=sum(item.status == "missing" for item in coverage_items),
        piece_coverage_percentage=percentage(total_available, total_required),
        fully_buildable=total_missing == 0,
    )
    return ModelCoverage(summary=summary, items=tuple(coverage_items))
