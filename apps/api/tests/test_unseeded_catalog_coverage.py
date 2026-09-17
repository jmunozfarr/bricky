"""Bug condition exploration for the unseeded-catalog coverage defect.

Property 1 (Bug Condition) from `.kiro/specs/unseeded-catalog-coverage/design.md`:
for any persisted model whose BOM is empty while its unresolved reference count is
greater than zero, the published verdict must not report `fullyBuildable` true, must
not present an unqualified 100% piece coverage, and must not be counted in
`ModelsReadinessResponse.fullyBuildableModels`.

The defect is deterministic, so the property is scoped to the concrete failing cases
rather than to a generated input space: the two end-to-end fixtures that exhibit it,
imported against a catalog context with zero `parts` rows. That empty catalog is the
natural state of the throwaway schema `catalog_session_factory` creates, so nothing
has to be torn down to reach it.

These bug-condition tests are EXPECTED TO FAIL on unfixed code - the failure is the
evidence that the defect exists, and the same assertions validate the fix once it
lands. The two tests at the bottom are controls that must pass on unfixed code: one
proves the condition is not merely "empty BOM", the other pins where the empty BOM
originates.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app
from app.services.ldraw_model_parser import parse_ldraw_model

IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"

# Verbatim copy of SYNTHETIC_MPD in apps/web/e2e/synthetic.ts: 3001 x3 in the main
# section plus submodel wing.ldr holding 3020 x2.
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

# Verbatim copy of INVENTORY_MPD in apps/web/e2e/inventory-import.spec.ts: 3005,
# 3004 x2, 3622 x2, five pieces across three distinct part references.
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
class UnresolvableFixture:
    """One concrete case in the scoped bug-condition input space."""

    label: str
    source: str
    # Distinct unresolved references, which is what unresolved_reference_count counts.
    unresolved_reference_count: int
    # (referenced filename, occurrence count) per distinct unresolved reference.
    unresolved_references: tuple[tuple[str, int], ...]
    # Official part ids an indexed catalog would hold for this fixture.
    indexed_part_ids: frozenset[str]


UNRESOLVABLE_FIXTURES = (
    UnresolvableFixture(
        label="core-loop",
        source=CORE_LOOP_MPD,
        unresolved_reference_count=2,
        unresolved_references=(("3001.dat", 3), ("3020.dat", 2)),
        indexed_part_ids=frozenset({"3001", "3020"}),
    ),
    UnresolvableFixture(
        label="inventory-import",
        source=INVENTORY_IMPORT_MPD,
        unresolved_reference_count=3,
        unresolved_references=(("3004.dat", 2), ("3005.dat", 1), ("3622.dat", 2)),
        indexed_part_ids=frozenset({"3004", "3005", "3622"}),
    ),
)


def client_for(factory: sessionmaker[Session], root: Path) -> TestClient:
    return TestClient(
        create_app(
            library_root=root / "library",
            session_factory=factory,
            model_storage_root=root / "models",
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


def list_summary(client: TestClient, model_id: str) -> dict[str, Any]:
    """The model summary the models list publishes, coverage verdict included."""
    listing = client.get("/api/models?pageSize=100")
    assert listing.status_code == 200, listing.text
    matches = [item for item in listing.json()["items"] if item["modelId"] == model_id]
    assert len(matches) == 1
    summary: dict[str, Any] = matches[0]
    return summary


def is_bug_condition(summary: dict[str, Any]) -> bool:
    """isBugCondition from the design, read off the published model summary."""
    return (
        summary["totalPartQuantity"] == 0
        and summary["uniquePartColorCount"] == 0
        and summary["unresolvedReferenceCount"] > 0
    )


def claims_unqualified_full_coverage(coverage: dict[str, Any]) -> bool:
    """A coverage summary asserts complete readiness as unqualified fact."""
    return coverage["fullyBuildable"] is True and coverage["pieceCoveragePercentage"] == 100.0


def counterexample(
    summary: dict[str, Any], coverage: dict[str, Any] | None = None, **extra: object
) -> str:
    """The mutually contradictory facts a failing assertion should report.

    Rendered as one line so the counterexample survives pytest's truncation of
    assertion messages and can be read straight out of a failure report.
    """
    verdict = coverage if coverage is not None else summary["coverage"] or {}
    facts = {
        "fullyBuildable": verdict.get("fullyBuildable"),
        "pieceCoveragePercentage": verdict.get("pieceCoveragePercentage"),
        "totalRequiredQuantity": verdict.get("totalRequiredQuantity"),
        "totalPartQuantity": summary["totalPartQuantity"],
        "uniquePartColorCount": summary["uniquePartColorCount"],
        "unresolvedReferenceCount": summary["unresolvedReferenceCount"],
        "importStatus": summary["importStatus"],
        **extra,
    }
    return " ".join(f"{key}={value!r}" for key, value in facts.items())


@pytest.mark.parametrize(
    "fixture", UNRESOLVABLE_FIXTURES, ids=[case.label for case in UNRESOLVABLE_FIXTURES]
)
def test_unresolvable_model_summary_does_not_claim_fully_buildable(
    fixture: UnresolvableFixture,
    catalog_session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """The models list must not publish buildability for a model that resolved nothing."""
    client = client_for(catalog_session_factory, tmp_path)
    model_id = upload(client, fixture.source, fixture.label)
    summary = list_summary(client, model_id)

    # Precondition: the imported model is in the reported bug condition.
    assert summary["unresolvedReferenceCount"] == fixture.unresolved_reference_count
    assert is_bug_condition(summary), summary

    assert summary["coverage"]["fullyBuildable"] is not True, counterexample(summary)


@pytest.mark.parametrize(
    "fixture", UNRESOLVABLE_FIXTURES, ids=[case.label for case in UNRESOLVABLE_FIXTURES]
)
def test_unresolvable_model_coverage_endpoint_does_not_claim_full_coverage(
    fixture: UnresolvableFixture,
    catalog_session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """/api/models/{id}/coverage must not report an unqualified 100% and buildable."""
    client = client_for(catalog_session_factory, tmp_path)
    model_id = upload(client, fixture.source, fixture.label)
    summary = list_summary(client, model_id)
    assert is_bug_condition(summary)

    response = client.get(f"/api/models/{model_id}/coverage")
    assert response.status_code == 200, response.text
    coverage = response.json()["summary"]
    assert coverage["totalRequiredQuantity"] == 0
    assert response.json()["items"] == []

    assert not claims_unqualified_full_coverage(coverage), counterexample(summary, coverage)


@pytest.mark.parametrize(
    "fixture", UNRESOLVABLE_FIXTURES, ids=[case.label for case in UNRESOLVABLE_FIXTURES]
)
def test_unresolvable_model_is_not_counted_as_fully_buildable(
    fixture: UnresolvableFixture,
    catalog_session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """The readiness aggregation must exclude a model that resolved nothing."""
    client = client_for(catalog_session_factory, tmp_path)
    model_id = upload(client, fixture.source, fixture.label)
    summary = list_summary(client, model_id)
    assert is_bug_condition(summary)

    readiness = client.get("/api/models/readiness-summary")
    assert readiness.status_code == 200, readiness.text
    payload = readiness.json()
    assert payload["totalModels"] == 1

    assert payload["fullyBuildableModels"] == 0, counterexample(
        summary, fullyBuildableModels=payload["fullyBuildableModels"]
    )


def test_control_empty_bom_from_ignore_resolution_keeps_todays_verdict(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    """Control: an empty BOM with zero unresolved references is not the bug condition.

    A model whose sole reference carries an `ignore` resolution is genuinely
    part-free, so isBugCondition is false and today's verdict is correct for it.
    This must pass both before and after the fix, proving the condition under test
    is not merely "empty BOM".
    """
    client = client_for(catalog_session_factory, tmp_path)
    model_id = upload(client, f"0 Control\n1 4 {IDENTITY} 3001.dat\n", "control-ignored")

    resolved = client.put(
        f"/api/models/{model_id}/resolutions",
        json={"sourceReference": "3001.dat", "action": "ignore"},
    )
    assert resolved.status_code == 200, resolved.text
    detail = resolved.json()
    assert detail["bom"] == []
    assert [issue["code"] for issue in detail["issues"]] == ["reference_ignored"]
    assert detail["importStatus"] == "ready"

    summary = list_summary(client, model_id)
    assert summary["totalPartQuantity"] == 0
    assert summary["uniquePartColorCount"] == 0
    assert summary["unresolvedReferenceCount"] == 0
    assert not is_bug_condition(summary)

    assert summary["coverage"]["fullyBuildable"] is True
    assert summary["coverage"]["pieceCoveragePercentage"] == 100.0
    coverage = client.get(f"/api/models/{model_id}/coverage").json()["summary"]
    assert coverage["fullyBuildable"] is True
    assert coverage["pieceCoveragePercentage"] == 100.0
    assert client.get("/api/models/readiness-summary").json()["fullyBuildableModels"] == 1


@pytest.mark.parametrize(
    "fixture", UNRESOLVABLE_FIXTURES, ids=[case.label for case in UNRESOLVABLE_FIXTURES]
)
def test_control_empty_bom_originates_at_the_unresolved_reference_continue(
    fixture: UnresolvableFixture,
) -> None:
    """Control: pin the origin of the empty BOM to the unresolved-reference branch.

    `official_part_ids` is the only input that differs between the two calls, and it
    is consumed exactly at the `official_part_id is None` branch in
    `ldraw_model_parser.traverse` that records `unresolved_reference` and `continue`s
    past `count_physical_part`. If flipping it empties the BOM and produces those
    issues, the empty BOM originates there and nowhere else.
    """
    unindexed = parse_ldraw_model(
        fixture.source.encode(),
        official_part_ids=frozenset(),
        known_color_codes=frozenset(),
    )
    assert unindexed.bom == ()
    assert [
        (
            issue.severity,
            issue.code,
            issue.message,
            issue.referenced_filename,
            issue.occurrence_count,
        )
        for issue in sorted(unindexed.issues, key=lambda issue: issue.referenced_filename or "")
    ] == [
        (
            "warning",
            "unresolved_reference",
            "Reference is not an embedded submodel or indexed official part",
            filename,
            occurrences,
        )
        for filename, occurrences in fixture.unresolved_references
    ]

    indexed = parse_ldraw_model(
        fixture.source.encode(),
        official_part_ids=fixture.indexed_part_ids,
        known_color_codes=frozenset(),
    )
    assert {item.part_id for item in indexed.bom} == fixture.indexed_part_ids
    assert sum(item.quantity for item in indexed.bom) == sum(
        occurrences for _filename, occurrences in fixture.unresolved_references
    )
    assert [issue for issue in indexed.issues if issue.code == "unresolved_reference"] == []
