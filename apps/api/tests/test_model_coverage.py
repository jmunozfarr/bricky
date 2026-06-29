from app.services.model_coverage import (
    CoverageRequirement,
    InventoryQuantity,
    calculate_model_coverage,
    percentage,
)


def requirement(
    part_id: str = "3001", color_code: int = 4, quantity: int = 4
) -> CoverageRequirement:
    return CoverageRequirement(part_id, color_code, quantity)


def owned(
    part_id: str = "3001", color_code: int = 4, quantity: int = 2
) -> InventoryQuantity:
    return InventoryQuantity(part_id, color_code, quantity)


def test_empty_inventory_is_fully_missing() -> None:
    coverage = calculate_model_coverage([requirement()], [])
    item = coverage.items[0]
    assert (item.owned_quantity, item.available_quantity, item.missing_quantity) == (0, 0, 4)
    assert item.status == "missing"
    assert item.coverage_percentage == 0
    assert coverage.summary.piece_coverage_percentage == 0
    assert coverage.summary.fully_buildable is False


def test_only_exact_normalized_part_and_color_match() -> None:
    coverage = calculate_model_coverage(
        [requirement("3001", 4, 4)],
        [owned(" 3001 ", 4, 1), owned("3001", 1, 20), owned("3002", 4, 20)],
    )
    assert coverage.items[0].owned_quantity == 1
    assert coverage.items[0].status == "partial"


def test_complete_and_excess_inventory_cap_availability() -> None:
    equal = calculate_model_coverage([requirement(quantity=4)], [owned(quantity=4)]).items[0]
    excess = calculate_model_coverage([requirement(quantity=4)], [owned(quantity=9)]).items[0]
    assert equal.status == "complete"
    assert excess.status == "complete"
    assert excess.owned_quantity == 9
    assert excess.available_quantity == 4
    assert excess.missing_quantity == 0
    assert excess.coverage_percentage == 100


def test_multiple_items_aggregate_physical_quantities_and_statuses() -> None:
    coverage = calculate_model_coverage(
        [requirement("3001", 4, 4), requirement("3002", 1, 3), requirement("3003", 7, 1)],
        [owned("3001", 4, 2), owned("3002", 1, 3)],
    )
    assert coverage.summary.total_required_quantity == 8
    assert coverage.summary.total_available_quantity == 5
    assert coverage.summary.total_missing_quantity == 3
    assert coverage.summary.unique_item_count == 3
    assert coverage.summary.complete_item_count == 1
    assert coverage.summary.partial_item_count == 1
    assert coverage.summary.missing_item_count == 1
    assert coverage.summary.piece_coverage_percentage == 62.5


def test_percentage_rounding_is_half_up_to_two_decimals() -> None:
    assert percentage(2, 3) == 66.67
    assert percentage(1, 6) == 16.67


def test_empty_bom_is_safe_and_buildable() -> None:
    coverage = calculate_model_coverage([], [owned()])
    assert coverage.items == ()
    assert coverage.summary.total_required_quantity == 0
    assert coverage.summary.piece_coverage_percentage == 100
    assert coverage.summary.fully_buildable is True
