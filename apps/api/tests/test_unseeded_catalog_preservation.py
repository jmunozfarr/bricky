"""Preservation baseline for the unseeded-catalog coverage defect.

Property 2 (Preservation) from `.kiro/specs/unseeded-catalog-coverage/design.md`:
for any model where the bug condition does NOT hold -- in particular every model
whose `unresolved_reference_count` is zero -- the fixed system must produce the
same coverage summary, percentage, per-item statuses, `fullyBuildable` value and
readiness contribution as the original system, and `calculate_model_coverage`
must remain callable with an empty requirement set without raising.

Observation-first. Every literal below was read off UNFIXED code, against an
indexed synthetic catalog, and then written down. Nothing here asserts what the
fix is expected to do, so the file is green before the fix and re-running it
afterwards is the identity check the property asks for.

Two decisions worth recording:

1. **No property-based testing library.** `hypothesis` is absent from
   `apps/api/requirements.in`, and `requirements.lock` is fully pinned and is
   what the Docker image installs from, so adding one means regenerating the
   lock and rebuilding the image -- disproportionate friction for this fix. The
   properties are therefore generated-input loops in plain pytest, seeded from
   `random.Random(PROPERTY_SEED)` so any failure is reproducible, with
   enumerated tables for the boundary cases. If `hypothesis` is ever added,
   these loops are the strategies to promote.

2. **Preservation is asserted over the coverage-summary fields that exist
   today** (`COVERAGE_SUMMARY_FIELDS`), not over the whole response object. The
   design plans to *add* a requirement-completeness field, so comparing whole
   objects would fail on the addition rather than on a behavior change.

The coverage primitive's own empty-requirement contract already has a dedicated
example in `test_model_coverage.test_empty_bom_is_safe_and_buildable`; it is not
restated here, only exercised as the zero-requirement boundary of the generated
space.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from synthetic_catalog import (
    FIXTURE_COLORS,
    FIXTURE_PARTS,
    MOVED_ALIAS_PART_ID,
    PRIMITIVE_NAME,
    SPARE_PART_ID,
    UNINDEXED_COLOR_CODE,
    index_synthetic_catalog,
)

from app.main import create_app
from app.services.model_coverage import (
    CoverageRequirement,
    InventoryQuantity,
    calculate_model_coverage,
    percentage,
)

IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"

# One fixed seed for every generated space in this module, so a counterexample
# is reproducible by re-running the test unchanged.
PROPERTY_SEED = 20260711

# The published coverage-summary contract as it stands before the fix.
COVERAGE_SUMMARY_FIELDS = (
    "totalRequiredQuantity",
    "totalAvailableQuantity",
    "totalMissingQuantity",
    "uniqueItemCount",
    "completeItemCount",
    "partialItemCount",
    "missingItemCount",
    "pieceCoveragePercentage",
    "fullyBuildable",
)

OFFICIAL_PART_IDS = (
    *(part_id for part_id, _name, _category in FIXTURE_PARTS),
    SPARE_PART_ID,
)
PHYSICAL_COLOR_CODES = tuple(code for code, _name, _value in FIXTURE_COLORS)


# --------------------------------------------------------------------------
# Independent oracle
# --------------------------------------------------------------------------
# Written from the documented contract rather than by calling the code under
# test: half-up to two decimals, a non-positive denominator is full coverage,
# availability is capped at the requirement, and inventory keys are matched on
# the case-insensitive stripped part id.


def half_up_percentage(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 100.0
    value = (Decimal(numerator) * Decimal(100)) / Decimal(denominator)
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def owned_lookup(inventory: Sequence[tuple[str, int, int]]) -> dict[tuple[str, int], int]:
    owned: dict[tuple[str, int], int] = {}
    for part_id, color_code, quantity in inventory:
        key = (part_id.strip().lower(), color_code)
        owned[key] = owned.get(key, 0) + max(quantity, 0)
    return owned


@dataclass(frozen=True)
class ExpectedItem:
    part_id: str
    color_code: int
    required_quantity: int
    owned_quantity: int
    available_quantity: int
    missing_quantity: int
    coverage_percentage: float
    status: str


@dataclass(frozen=True)
class ExpectedCoverage:
    summary: dict[str, Any]
    items: tuple[ExpectedItem, ...]


def expected_coverage(
    requirements: Sequence[tuple[str, int, int]],
    inventory: Sequence[tuple[str, int, int]],
) -> ExpectedCoverage:
    owned_by_key = owned_lookup(inventory)
    items: list[ExpectedItem] = []
    for part_id, color_code, required in requirements:
        owned = owned_by_key.get((part_id.strip().lower(), color_code), 0)
        available = min(required, owned)
        status = "complete" if owned >= required else "partial" if owned > 0 else "missing"
        items.append(
            ExpectedItem(
                part_id=part_id,
                color_code=color_code,
                required_quantity=required,
                owned_quantity=owned,
                available_quantity=available,
                missing_quantity=max(required - owned, 0),
                coverage_percentage=half_up_percentage(available, required),
                status=status,
            )
        )
    total_required = sum(item.required_quantity for item in items)
    total_available = sum(item.available_quantity for item in items)
    total_missing = sum(item.missing_quantity for item in items)
    summary = {
        "totalRequiredQuantity": total_required,
        "totalAvailableQuantity": total_available,
        "totalMissingQuantity": total_missing,
        "uniqueItemCount": len(items),
        "completeItemCount": sum(item.status == "complete" for item in items),
        "partialItemCount": sum(item.status == "partial" for item in items),
        "missingItemCount": sum(item.status == "missing" for item in items),
        "pieceCoveragePercentage": half_up_percentage(total_available, total_required),
        "fullyBuildable": total_missing == 0,
    }
    return ExpectedCoverage(summary=summary, items=tuple(items))


def published_verdict(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Project a coverage summary onto the fields published before the fix."""
    return {name: summary[name] for name in COVERAGE_SUMMARY_FIELDS}


# --------------------------------------------------------------------------
# The coverage primitive, over a generated requirement/inventory space
# --------------------------------------------------------------------------


def generated_coverage_case(
    rng: random.Random,
) -> tuple[tuple[tuple[str, int, int], ...], tuple[tuple[str, int, int], ...]]:
    """One (requirements, inventory) pair from the primitive's input space.

    Deliberately includes the zero-requirement boundary, repeated requirement
    keys, inventory rows that match nothing, padded and upper-cased part ids,
    and non-positive owned quantities.
    """
    part_pool = (*OFFICIAL_PART_IDS, "custom-x")
    color_pool = (*PHYSICAL_COLOR_CODES, UNINDEXED_COLOR_CODE)

    def spelling(part_id: str) -> str:
        return rng.choice((part_id, f" {part_id} ", part_id.upper()))

    requirements = tuple(
        (rng.choice(part_pool), rng.choice(color_pool), rng.randint(1, 7))
        for _ in range(rng.randint(0, 5))
    )
    inventory = tuple(
        (spelling(rng.choice(part_pool)), rng.choice(color_pool), rng.randint(-3, 9))
        for _ in range(rng.randint(0, 6))
    )
    return requirements, inventory


def test_coverage_primitive_matches_the_independent_oracle_across_generated_pairs() -> None:
    """`calculate_model_coverage` over 200 generated pairs, including empty ones."""
    rng = random.Random(PROPERTY_SEED)
    empty_requirement_cases = 0
    fully_buildable_cases = 0
    for iteration in range(200):
        requirements, inventory = generated_coverage_case(rng)
        expected = expected_coverage(requirements, inventory)
        coverage = calculate_model_coverage(
            [CoverageRequirement(*entry) for entry in requirements],
            [InventoryQuantity(*entry) for entry in inventory],
        )
        context = f"iteration={iteration} requirements={requirements} inventory={inventory}"

        assert [
            ExpectedItem(
                item.part_id,
                item.color_code,
                item.required_quantity,
                item.owned_quantity,
                item.available_quantity,
                item.missing_quantity,
                item.coverage_percentage,
                item.status,
            )
            for item in coverage.items
        ] == list(expected.items), context
        summary = coverage.summary
        assert {
            "totalRequiredQuantity": summary.total_required_quantity,
            "totalAvailableQuantity": summary.total_available_quantity,
            "totalMissingQuantity": summary.total_missing_quantity,
            "uniqueItemCount": summary.unique_item_count,
            "completeItemCount": summary.complete_item_count,
            "partialItemCount": summary.partial_item_count,
            "missingItemCount": summary.missing_item_count,
            "pieceCoveragePercentage": summary.piece_coverage_percentage,
            "fullyBuildable": summary.fully_buildable,
        } == expected.summary, context

        if not requirements:
            empty_requirement_cases += 1
            assert summary.piece_coverage_percentage == 100.0, context
            assert summary.fully_buildable is True, context
        if summary.fully_buildable:
            fully_buildable_cases += 1

    # The generated space is non-degenerate: it reached both the empty
    # requirement set and a mix of buildable and unbuildable outcomes.
    assert empty_requirement_cases > 0
    assert 0 < fully_buildable_cases < 200


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [
        # Third decimal exactly 5: half-up, not half-even, and not float round().
        (1, 800, 0.13),
        (5, 800, 0.63),
        (3, 800, 0.38),
        (7, 800, 0.88),
        # Repeating decimals truncate at two places.
        (2, 3, 66.67),
        (1, 3, 33.33),
        # Exact values keep no spurious precision.
        (1, 8, 12.5),
        (0, 5, 0.0),
        (5, 5, 100.0),
        # A non-positive denominator is full coverage by contract.
        (0, 0, 100.0),
        (3, 0, 100.0),
        (0, -1, 100.0),
    ],
)
def test_percentage_rounds_half_up_to_two_decimals(
    numerator: int, denominator: int, expected: float
) -> None:
    assert percentage(numerator, denominator) == expected


@pytest.mark.parametrize(
    ("required", "owned", "status", "available", "missing", "item_percentage"),
    [
        (4, 0, "missing", 0, 4, 0.0),
        (4, 1, "partial", 1, 3, 25.0),
        (4, 3, "partial", 3, 1, 75.0),
        (4, 4, "complete", 4, 0, 100.0),
        (4, 9, "complete", 4, 0, 100.0),
        (1, 0, "missing", 0, 1, 0.0),
        (1, 1, "complete", 1, 0, 100.0),
        (3, 1, "partial", 1, 2, 33.33),
    ],
)
def test_item_status_boundaries_are_owned_against_required(
    required: int,
    owned: int,
    status: str,
    available: int,
    missing: int,
    item_percentage: float,
) -> None:
    inventory = [InventoryQuantity("3001", 4, owned)] if owned > 0 else []
    coverage = calculate_model_coverage([CoverageRequirement("3001", 4, required)], inventory)
    item = coverage.items[0]
    assert (item.status, item.available_quantity, item.missing_quantity) == (
        status,
        available,
        missing,
    )
    assert item.coverage_percentage == item_percentage
    assert coverage.summary.fully_buildable is (missing == 0)


def test_non_positive_required_quantity_is_still_rejected() -> None:
    with pytest.raises(ValueError, match="Required quantities must be positive"):
        calculate_model_coverage([CoverageRequirement("3001", 4, 0)], [])


# --------------------------------------------------------------------------
# The published verdict, against an indexed catalog
# --------------------------------------------------------------------------


def client_for(factory: sessionmaker[Session], library_root: Path, storage: Path) -> TestClient:
    return TestClient(
        create_app(
            library_root=library_root,
            session_factory=factory,
            model_storage_root=storage,
        )
    )


def upload(client: TestClient, source: str, name: str) -> str:
    response = client.post(
        "/api/models",
        files={"file": (f"{name}.mpd", source.encode(), "text/plain")},
        data={"name": name},
    )
    assert response.status_code == 201, response.text
    model_id: str = response.json()["modelId"]
    return model_id


def write_inventory(client: TestClient, inventory: Sequence[tuple[str, int, int]]) -> None:
    for part_id, color_code, quantity in inventory:
        response = client.put(
            f"/api/inventory/items/{part_id}/{color_code}", json={"quantity": quantity}
        )
        assert response.status_code == 200, response.text


def bom_triples(detail: Mapping[str, Any]) -> list[tuple[str, int, int]]:
    return [(item["partId"], item["colorCode"], item["quantity"]) for item in detail["bom"]]


def issue_tuples(detail: Mapping[str, Any]) -> list[tuple[str, str, str | None, int]]:
    return [
        (
            issue["severity"],
            issue["code"],
            issue["referencedFilename"],
            issue["occurrenceCount"],
        )
        for issue in detail["issues"]
    ]


def list_summary(client: TestClient, model_id: str) -> dict[str, Any]:
    listing = client.get("/api/models?pageSize=100")
    assert listing.status_code == 200, listing.text
    matches = [item for item in listing.json()["items"] if item["modelId"] == model_id]
    assert len(matches) == 1
    summary: dict[str, Any] = matches[0]
    return summary


# Verbatim copies of the two end-to-end fixtures: apps/web/e2e/synthetic.ts and
# the INVENTORY_MPD in apps/web/e2e/inventory-import.spec.ts. With an indexed
# catalog these are the models whose `40% covered / 3 pieces missing` and
# `60% covered / 2 pieces missing` assertions requirement 3.10 protects.
CORE_LOOP_MPD = "\n".join(
    [
        "0 FILE main.ldr",
        "0 Name: main.ldr",
        "1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat",
        "0 STEP",
        "1 14 0 -24 0 1 0 0 0 1 0 0 0 1 3001.dat",
        "0 STEP",
        "1 1 0 -48 0 1 0 0 0 1 0 0 0 1 3001.dat",
        "0 STEP",
        "1 16 60 0 0 1 0 0 0 1 0 0 0 1 wing.ldr",
        "0 FILE wing.ldr",
        "1 2 0 0 0 1 0 0 0 1 0 0 0 1 3020.dat",
        "0 STEP",
        "1 2 0 -8 0 1 0 0 0 1 0 0 0 1 3020.dat",
        "0 NOFILE",
        "",
    ]
)

INVENTORY_IMPORT_MPD = "\n".join(
    [
        "0 FILE main.ldr",
        "0 Name: main.ldr",
        "1 71 0 0 0 1 0 0 0 1 0 0 0 1 3005.dat",
        "0 STEP",
        "1 19 0 -24 0 1 0 0 0 1 0 0 0 1 3004.dat",
        "1 19 0 -48 0 1 0 0 0 1 0 0 0 1 3004.dat",
        "0 STEP",
        "1 27 60 0 0 1 0 0 0 1 0 0 0 1 3622.dat",
        "1 27 60 -24 0 1 0 0 0 1 0 0 0 1 3622.dat",
        "0 NOFILE",
        "",
    ]
)


@dataclass(frozen=True)
class ResolvedFixture:
    """An e2e fixture as it resolves against an indexed catalog."""

    label: str
    source: str
    inventory: tuple[tuple[str, int, int], ...]
    declared_step_count: int
    bom: tuple[tuple[str, int, int], ...]
    piece_coverage_percentage: float
    total_missing_quantity: int
    item_statuses: tuple[tuple[str, int, str], ...]


RESOLVED_FIXTURES = (
    ResolvedFixture(
        label="core-loop",
        source=CORE_LOOP_MPD,
        inventory=(("3020", 2, 2),),
        declared_step_count=4,
        bom=(("3001", 1, 1), ("3001", 4, 1), ("3001", 14, 1), ("3020", 2, 2)),
        piece_coverage_percentage=40.0,
        total_missing_quantity=3,
        item_statuses=(
            ("3001", 1, "missing"),
            ("3001", 4, "missing"),
            ("3001", 14, "missing"),
            ("3020", 2, "complete"),
        ),
    ),
    ResolvedFixture(
        label="inventory-import",
        source=INVENTORY_IMPORT_MPD,
        inventory=(("3005", 71, 1), ("3004", 19, 2)),
        declared_step_count=3,
        bom=(("3004", 19, 2), ("3005", 71, 1), ("3622", 27, 2)),
        piece_coverage_percentage=60.0,
        total_missing_quantity=2,
        item_statuses=(
            ("3622", 27, "missing"),
            ("3004", 19, "complete"),
            ("3005", 71, "complete"),
        ),
    ),
)


@pytest.mark.parametrize(
    "fixture", RESOLVED_FIXTURES, ids=[case.label for case in RESOLVED_FIXTURES]
)
def test_indexed_catalog_fully_resolved_fixture_verdict_is_pinned(
    fixture: ResolvedFixture,
    catalog_session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """The exact verdict an indexed install publishes for a fully resolved model."""
    library_root, _report = index_synthetic_catalog(catalog_session_factory, tmp_path)
    client = client_for(catalog_session_factory, library_root, tmp_path / "models")
    model_id = upload(client, fixture.source, fixture.label)
    write_inventory(client, fixture.inventory)

    detail = client.get(f"/api/models/{model_id}").json()
    assert detail["importStatus"] == "ready"
    assert detail["unresolvedReferenceCount"] == 0
    assert issue_tuples(detail) == []
    assert detail["declaredStepCount"] == fixture.declared_step_count
    assert bom_triples(detail) == list(fixture.bom)
    assert detail["totalPartQuantity"] == sum(quantity for *_key, quantity in fixture.bom)
    assert detail["uniquePartColorCount"] == len(fixture.bom)

    expected = expected_coverage(fixture.bom, fixture.inventory)
    assert expected.summary["pieceCoveragePercentage"] == fixture.piece_coverage_percentage
    assert expected.summary["totalMissingQuantity"] == fixture.total_missing_quantity

    coverage = client.get(f"/api/models/{model_id}/coverage").json()
    assert published_verdict(coverage["summary"]) == expected.summary
    assert [
        (item["partId"], item["colorCode"], item["status"]) for item in coverage["items"]
    ] == list(fixture.item_statuses)
    assert published_verdict(list_summary(client, model_id)["coverage"]) == expected.summary
    assert client.get("/api/models/readiness-summary").json() == {
        "totalModels": 1,
        "fullyBuildableModels": 0,
        "incompleteModels": 1,
        "totalMissingQuantity": fixture.total_missing_quantity,
    }


@dataclass(frozen=True)
class ResolutionPath:
    """One reference-resolution path that leaves zero unresolved references."""

    label: str
    source: str
    bom: tuple[tuple[str, int, int], ...]
    issues: tuple[tuple[str, str, str | None, int], ...] = ()
    import_status: str = "ready"
    resolutions: tuple[dict[str, Any], ...] = field(default_factory=tuple)


# Inventory shared by every case below, so the table mixes fully buildable
# verdicts with incomplete ones among models that all resolved completely.
RESOLUTION_PATH_INVENTORY = (("3001", 4, 1), ("3020", 2, 5))

RESOLUTION_PATHS = (
    ResolutionPath(
        label="normalized-parts-hit",
        source=f"0 Direct\n1 4 {IDENTITY} 3001.dat\n",
        bom=(("3001", 4, 1),),
    ),
    ResolutionPath(
        label="known-primitive-bare",
        source=f"0 Primitive\n1 4 {IDENTITY} 3001.dat\n1 4 {IDENTITY} {PRIMITIVE_NAME}\n",
        bom=(("3001", 4, 1),),
    ),
    ResolutionPath(
        label="primitive-under-p",
        source=f"0 PrimitivePath\n1 4 {IDENTITY} 3001.dat\n1 4 {IDENTITY} p/{PRIMITIVE_NAME}\n",
        bom=(("3001", 4, 1),),
    ),
    ResolutionPath(
        label="auto-mapped-set-wrapper",
        source=f"0 Wrapper\n1 4 {IDENTITY} 42083 - 3001.dat\n",
        bom=(("3001", 4, 1),),
        issues=(("info", "custom_part_auto_mapped", "42083 - 3001.dat", 1),),
    ),
    ResolutionPath(
        label="auto-mapped-bent",
        source=f"0 Bent\n1 1 {IDENTITY} 3001_bended.dat\n",
        bom=(("3001", 1, 1),),
        issues=(("info", "custom_part_auto_mapped", "3001_bended.dat", 1),),
    ),
    ResolutionPath(
        label="embedded-section-shadowing-official-part",
        source="\n".join(
            [
                "0 FILE main.ldr",
                f"1 4 {IDENTITY} 3020.dat",
                "0 FILE 3020.dat",
                f"1 16 {IDENTITY} 3001.dat",
                "",
            ]
        ),
        bom=(("3020", 4, 1),),
        issues=(("info", "custom_part_auto_mapped", "3020.dat", 1),),
    ),
    ResolutionPath(
        label="manual-map",
        source=f"0 ManualMap\n1 4 {IDENTITY} customhose.dat\n",
        bom=(("3004", 4, 1),),
        issues=(("info", "reference_manually_mapped", "customhose.dat", 1),),
        resolutions=({"sourceReference": "customhose.dat", "action": "map", "partId": "3004"},),
    ),
    ResolutionPath(
        label="manual-map-with-color-override",
        source=f"0 ManualMapColor\n1 4 {IDENTITY} customflex.dat\n",
        bom=(("3005", 2, 1),),
        issues=(("info", "reference_manually_mapped", "customflex.dat", 1),),
        resolutions=(
            {
                "sourceReference": "customflex.dat",
                "action": "map",
                "partId": "3005",
                "colorCode": 2,
            },
        ),
    ),
    ResolutionPath(
        label="manual-ignore-beside-a-counted-part",
        source=f"0 ManualIgnore\n1 4 {IDENTITY} 3001.dat\n1 4 {IDENTITY} sticker.dat\n",
        bom=(("3001", 4, 1),),
        issues=(("info", "reference_ignored", "sticker.dat", 1),),
        resolutions=({"sourceReference": "sticker.dat", "action": "ignore"},),
    ),
    ResolutionPath(
        label="submodel-traversal",
        source="\n".join(
            [
                "0 FILE main.ldr",
                f"1 4 {IDENTITY} body.ldr",
                "0 FILE body.ldr",
                f"1 16 {IDENTITY} 3001.dat",
                f"1 2 {IDENTITY} 3020.dat",
                "",
            ]
        ),
        bom=(("3001", 4, 1), ("3020", 2, 1)),
    ),
    ResolutionPath(
        label="moved-alias-canonicalization",
        source=f"0 Alias\n1 4 {IDENTITY} {MOVED_ALIAS_PART_ID}.dat\n",
        bom=(("3001", 4, 1),),
    ),
    ResolutionPath(
        # An unindexed color still counts the part; the warning is not an
        # unresolved reference, but it does flip import_status.
        label="unknown-color-counts-the-part",
        source=f"0 UnknownColor\n1 {UNINDEXED_COLOR_CODE} {IDENTITY} 3001.dat\n",
        bom=(("3001", UNINDEXED_COLOR_CODE, 1),),
        issues=(("warning", "unknown_color", "3001.dat", 1),),
        import_status="ready_with_warnings",
    ),
)


@pytest.mark.parametrize("path", RESOLUTION_PATHS, ids=[case.label for case in RESOLUTION_PATHS])
def test_every_resolution_path_keeps_its_classification_and_verdict(
    path: ResolutionPath,
    catalog_session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """Each resolution path resolves fully, so its verdict must survive the fix."""
    library_root, _report = index_synthetic_catalog(catalog_session_factory, tmp_path)
    client = client_for(catalog_session_factory, library_root, tmp_path / "models")
    write_inventory(client, RESOLUTION_PATH_INVENTORY)
    model_id = upload(client, path.source, path.label)
    for payload in path.resolutions:
        applied = client.put(f"/api/models/{model_id}/resolutions", json=payload)
        assert applied.status_code == 200, applied.text

    detail = client.get(f"/api/models/{model_id}").json()
    assert bom_triples(detail) == list(path.bom)
    assert issue_tuples(detail) == list(path.issues)
    assert detail["importStatus"] == path.import_status
    assert detail["totalPartQuantity"] == sum(quantity for *_key, quantity in path.bom)
    assert detail["uniquePartColorCount"] == len(path.bom)
    # The precondition that puts this case inside the preservation surface.
    assert detail["unresolvedReferenceCount"] == 0

    expected = expected_coverage(path.bom, RESOLUTION_PATH_INVENTORY)
    coverage = client.get(f"/api/models/{model_id}/coverage").json()
    assert published_verdict(coverage["summary"]) == expected.summary
    assert [(item["partId"], item["colorCode"], item["status"]) for item in coverage["items"]] == [
        (item.part_id, item.color_code, item.status) for item in expected.items
    ]
    assert published_verdict(list_summary(client, model_id)["coverage"]) == expected.summary
    assert client.get("/api/models/readiness-summary").json() == {
        "totalModels": 1,
        "fullyBuildableModels": int(expected.summary["fullyBuildable"]),
        "incompleteModels": 1 - int(expected.summary["fullyBuildable"]),
        "totalMissingQuantity": expected.summary["totalMissingQuantity"],
    }


# --------------------------------------------------------------------------
# The core property, over a generated workspace of fully resolved models
# --------------------------------------------------------------------------

GENERATED_MODEL_COUNT = 10


@dataclass(frozen=True)
class GeneratedModel:
    label: str
    source: str
    requirements: tuple[tuple[str, int, int], ...]


def generated_model(rng: random.Random, index: int) -> GeneratedModel:
    """A model that resolves completely: official ids and physical colors only.

    Half the references move into a submodel so traversal is inside the
    generated space. Colors 16 and 24 are excluded on purpose -- a leaf
    reference carrying either does not resolve to a physical part, which would
    leave the model outside the preservation surface.
    """
    keys: list[tuple[str, int]] = []
    while len(keys) < rng.randint(1, 4):
        candidate = (rng.choice(OFFICIAL_PART_IDS), rng.choice(PHYSICAL_COLOR_CODES))
        if candidate not in keys:
            keys.append(candidate)
    requirements = tuple((part_id, color, rng.randint(1, 4)) for part_id, color in keys)

    split = max(len(requirements) // 2, 1) if index % 2 else len(requirements)
    top_level = requirements[:split]
    nested = requirements[split:]

    lines = ["0 FILE main.ldr", f"0 // generated-{index}"]
    for part_id, color, quantity in top_level:
        lines.extend(f"1 {color} {IDENTITY} {part_id}.dat" for _ in range(quantity))
    if nested:
        lines.append(f"1 16 {IDENTITY} sub.ldr")
        lines.append("0 FILE sub.ldr")
        for part_id, color, quantity in nested:
            lines.extend(f"1 {color} {IDENTITY} {part_id}.dat" for _ in range(quantity))
    lines.extend(("0 NOFILE", ""))
    return GeneratedModel(
        label=f"generated-{index}",
        source="\n".join(lines),
        requirements=tuple(sorted(requirements, key=lambda entry: (entry[0], entry[1]))),
    )


def generated_inventory(
    rng: random.Random, models: Sequence[GeneratedModel]
) -> tuple[tuple[str, int, int], ...]:
    """Owned quantities spanning missing, partial, complete and excess."""
    demand: dict[tuple[str, int], int] = {}
    for model in models:
        for part_id, color, quantity in model.requirements:
            key = (part_id, color)
            demand[key] = max(demand.get(key, 0), quantity)
    rows: list[tuple[str, int, int]] = []
    for (part_id, color), required in sorted(demand.items()):
        owned = rng.choice((0, 1, required - 1, required, required, required + 2))
        if owned > 0:
            rows.append((part_id, color, owned))
    return tuple(rows)


def test_published_verdict_for_fully_resolved_models_is_the_coverage_of_their_bom(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    """The property the fix must not disturb.

    For every generated model with `unresolvedReferenceCount == 0`, the verdict
    the API publishes -- on the card, on the coverage endpoint, and in the
    readiness aggregation -- is exactly the coverage of its own BOM against the
    workspace inventory. The fix conjoins the verdict with requirement
    completeness, which is true for every model here, so this must hold
    identically afterwards.
    """
    rng = random.Random(PROPERTY_SEED)
    library_root, _report = index_synthetic_catalog(catalog_session_factory, tmp_path)
    client = client_for(catalog_session_factory, library_root, tmp_path / "models")

    models = [generated_model(rng, index) for index in range(GENERATED_MODEL_COUNT)]
    inventory = generated_inventory(rng, models)
    write_inventory(client, inventory)

    verdicts: list[dict[str, Any]] = []
    for model in models:
        model_id = upload(client, model.source, model.label)
        detail = client.get(f"/api/models/{model_id}").json()
        context = f"{model.label} requirements={model.requirements}"

        assert detail["unresolvedReferenceCount"] == 0, context
        assert detail["importStatus"] == "ready", context
        assert bom_triples(detail) == list(model.requirements), context
        assert detail["totalPartQuantity"] == sum(
            quantity for *_key, quantity in model.requirements
        ), context
        assert detail["uniquePartColorCount"] == len(model.requirements), context

        expected = expected_coverage(model.requirements, inventory)
        coverage = client.get(f"/api/models/{model_id}/coverage").json()
        assert published_verdict(coverage["summary"]) == expected.summary, context
        assert [
            (
                item["partId"],
                item["colorCode"],
                item["requiredQuantity"],
                item["ownedQuantity"],
                item["availableQuantity"],
                item["missingQuantity"],
                item["coveragePercentage"],
                item["status"],
            )
            for item in sorted(
                coverage["items"], key=lambda entry: (entry["partId"], entry["colorCode"])
            )
        ] == [
            (
                item.part_id,
                item.color_code,
                item.required_quantity,
                item.owned_quantity,
                item.available_quantity,
                item.missing_quantity,
                item.coverage_percentage,
                item.status,
            )
            for item in sorted(expected.items, key=lambda entry: (entry.part_id, entry.color_code))
        ], context
        assert published_verdict(list_summary(client, model_id)["coverage"]) == expected.summary, (
            context
        )
        verdicts.append(expected.summary)

    buildable = sum(1 for verdict in verdicts if verdict["fullyBuildable"])
    # A vacuous generated space would prove nothing about the aggregation.
    assert 0 < buildable < GENERATED_MODEL_COUNT
    assert client.get("/api/models/readiness-summary").json() == {
        "totalModels": GENERATED_MODEL_COUNT,
        "fullyBuildableModels": buildable,
        "incompleteModels": GENERATED_MODEL_COUNT - buildable,
        "totalMissingQuantity": sum(verdict["totalMissingQuantity"] for verdict in verdicts),
    }
