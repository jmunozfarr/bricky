from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ImportedModel
from app.services.instruction_graph import InstructionGraphLimits
from instruction_fixture_factory import generated_large_repeated_model
from test_models_api import client_for, seed_catalog, upload


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "instruction_graph"
VALID_FIXTURES = (
    "flat_steps.mpd",
    "one_stepped_submodel.mpd",
    "nested_stepped_submodels.mpd",
    "repeated_submodel.mpd",
    "transformed_occurrences.mpd",
    "explicit_attachment_steps.mpd",
    "direct_geometry_flex.mpd",
)


def imported_fixture(
    factory: sessionmaker[Session], tmp_path: Path, name: str
) -> tuple[TestClient, str, bytes]:
    seed_catalog(factory)
    client = client_for(factory, tmp_path)
    source = (FIXTURE_ROOT / name).read_bytes()
    response = upload(client, source, name)
    assert response.status_code == 201
    return client, response.json()["modelId"], source


@pytest.mark.parametrize("name", VALID_FIXTURES)
def test_valid_static_fixtures_expose_bounded_playback(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path, name: str
) -> None:
    client, model_id, _source = imported_fixture(
        catalog_session_factory, tmp_path, name
    )

    summary = client.get(f"/api/models/{model_id}/instruction-playback")

    assert summary.status_code == 200
    assert summary.json()["available"] is True
    root_id = summary.json()["rootOccurrenceId"]
    occurrence = client.get(
        f"/api/models/{model_id}/instruction-occurrences/{root_id}?step=1"
    )
    assert occurrence.status_code == 200
    assert occurrence.json()["occurrenceId"] == "occ-000001"
    assert "sceneSourceUrl" in occurrence.json()
    assert "modelDefinitions" not in occurrence.json()
    assert "instructionNodes" not in occurrence.json()


def test_occurrence_payload_has_breadcrumbs_immediate_children_and_repeats(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    client, model_id, _source = imported_fixture(
        catalog_session_factory, tmp_path, "repeated_submodel.mpd"
    )

    root = client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-000001?step=1"
    ).json()
    child = client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-000003?step=1"
    ).json()

    assert root["breadcrumbs"] == [
        {"occurrenceId": "occ-000001", "sourceSubmodelName": "main.ldr"}
    ]
    assert [item["occurrenceId"] for item in root["children"]] == [
        "occ-000002",
        "occ-000003",
    ]
    assert root["children"][1]["repeatedDefinitionIndex"] == 2
    assert child["parentOccurrenceId"] == "occ-000001"
    assert [item["occurrenceId"] for item in child["breadcrumbs"]] == [
        "occ-000001",
        "occ-000003",
    ]


def test_build_manifest_returns_complete_scene_steps_parts_and_inventory(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    client, model_id, _source = imported_fixture(
        catalog_session_factory, tmp_path, "flat_steps.mpd"
    )
    assert client.put(
        "/api/inventory/items/3001/4", json={"quantity": 2}
    ).status_code == 200

    response = client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-000001/build-manifest"
    )

    assert response.status_code == 200
    manifest = response.json()
    assert manifest["occurrenceId"] == "occ-000001"
    assert "step=" not in manifest["scene"]["url"]
    assert len(manifest["scene"]["cacheKey"]) == 64
    assert [step["step"] for step in manifest["steps"]] == [1, 2, 3]
    assert manifest["steps"][0]["parts"] == [
        {
            "sourcePartId": "3001",
            "partId": "3001",
            "aliasApplied": False,
            "instructionNodeIds": ["node-000001"],
            "partName": "Brick 2 x 4",
            "colorCode": 4,
            "colorName": "Red",
            "colorHex": "#C91A09",
            "quantityThisStep": 1,
            "ownedQuantity": 2,
            "modelRequiredQuantity": 1,
            "modelMissingQuantity": 0,
            "catalogAvailable": True,
        }
    ]
    assert manifest["steps"][2]["parts"][0]["catalogAvailable"] is False


def test_derived_source_is_safe_ephemeral_and_preserves_original(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    client, model_id, original = imported_fixture(
        catalog_session_factory, tmp_path, "transformed_occurrences.mpd"
    )
    original_hash = hashlib.sha256(original).hexdigest()

    response = client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-000001/source"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=3600"
    assert response.headers["etag"].startswith('"')
    assert b"__bricky_occ_000002.ldr" in response.content
    assert str(tmp_path).encode() not in response.content
    assert client.get(f"/api/models/{model_id}/source").content == original
    with catalog_session_factory() as session:
        model = session.scalar(select(ImportedModel))
        assert model is not None and model.source_sha256 == original_hash
    stored = list((tmp_path / "models" / "originals" / model_id).iterdir())
    assert len(stored) == 1


def test_unknown_occurrence_and_traversal_attempt_return_404(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    client, model_id, _source = imported_fixture(
        catalog_session_factory, tmp_path, "flat_steps.mpd"
    )

    assert client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-999999"
    ).status_code == 404
    assert client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-999999/source"
    ).status_code == 404
    assert client.get(
        f"/api/models/{model_id}/instruction-occurrences/%2E%2E%2Fsource/source"
    ).status_code == 404


def test_cycle_and_safety_limit_return_flattened_fallback_state(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    cycle_client = client_for(catalog_session_factory, tmp_path / "cycle")
    cycle_source = (FIXTURE_ROOT / "recursion_cycle.mpd").read_bytes()
    cycle_id = upload(cycle_client, cycle_source, "cycle.mpd").json()["modelId"]
    cycle = cycle_client.get(
        f"/api/models/{cycle_id}/instruction-playback"
    ).json()

    assert cycle["available"] is False
    assert cycle["rootOccurrenceId"] is None
    assert cycle["issues"][0]["code"] == "recursive_submodel_cycle"
    assert cycle_client.get(
        f"/api/models/{cycle_id}/instruction-occurrences/occ-000001"
    ).status_code == 409

    limited_client = client_for(
        catalog_session_factory,
        tmp_path / "limited",
        graph_limits=InstructionGraphLimits(max_nesting_depth=2),
    )
    limited_source = (FIXTURE_ROOT / "excessive_nesting.mpd").read_bytes()
    limited_id = upload(
        limited_client, limited_source, "limited.mpd"
    ).json()["modelId"]
    limited = limited_client.get(
        f"/api/models/{limited_id}/instruction-playback"
    ).json()
    assert limited["available"] is False
    assert limited["issues"][0]["code"] == "nesting_depth_limit_exceeded"


def test_large_occurrence_navigation_payload_is_paginated(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    response = upload(
        client, generated_large_repeated_model(1_000), "generated-1000.mpd"
    )
    assert response.status_code == 201
    model_id = response.json()["modelId"]

    summary = client.get(f"/api/models/{model_id}/instruction-playback")
    occurrence = client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-000001?step=1"
    )

    assert len(summary.content) < 1_000
    assert len(occurrence.content) < 20_000
    assert occurrence.json()["childTotal"] == 1_000
    assert len(occurrence.json()["children"]) == 50
    assert summary.json()["recommendedRenderStrategy"] == "local"
    assert summary.json()["flattenedRenderingAllowed"] is False
    assert occurrence.json()["renderStrategy"] == "local"
    assert "mode=local" in occurrence.json()["sceneSourceUrl"]


def test_local_source_excludes_child_geometry_and_invalid_modes_are_typed(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    client, model_id, _source = imported_fixture(
        catalog_session_factory, tmp_path, "direct_geometry_flex.mpd"
    )
    metadata = client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-000001?step=1&renderStrategy=local"
    )
    source = client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-000001/source?mode=local&step=1"
    )
    invalid = client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-000001/source?mode=invalid&step=1"
    )

    assert metadata.status_code == source.status_code == 200
    assert metadata.json()["children"][0]["occurrenceId"] == "occ-000002"
    assert metadata.json()["renderStrategy"] == "local"
    assert b"__bricky_occ_000002.ldr" not in source.content
    assert invalid.status_code == 422
