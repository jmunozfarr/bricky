from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from instruction_fixture_factory import generated_large_repeated_model
from test_models_api import client_for, seed_catalog, upload


@pytest.mark.parametrize("physical_parts", [100, 1_000, 5_000])
def test_playback_api_diagnostics(
    catalog_session_factory: sessionmaker[Session],
    tmp_path: Path,
    physical_parts: int,
    record_property: pytest.RecordProperty,
) -> None:
    seed_catalog(catalog_session_factory)
    client: TestClient = client_for(catalog_session_factory, tmp_path)
    model_id = upload(
        client,
        generated_large_repeated_model(physical_parts),
        f"generated-{physical_parts}.mpd",
    ).json()["modelId"]

    started = perf_counter()
    summary = client.get(f"/api/models/{model_id}/instruction-playback")
    root = client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-000001?step=1"
    )
    source = client.get(root.json()["sceneSourceUrl"])
    initial_api_ms = (perf_counter() - started) * 1_000

    scope_started = perf_counter()
    child = client.get(
        f"/api/models/{model_id}/instruction-occurrences/occ-000002?step=1"
    )
    child_source = client.get(child.json()["sceneSourceUrl"])
    scope_api_ms = (perf_counter() - scope_started) * 1_000
    diagnostics = {
        "physicalPartOccurrences": physical_parts,
        "summaryPayloadBytes": len(summary.content),
        "rootOccurrencePayloadBytes": len(root.content),
        "rootSceneSourceBytes": len(source.content),
        "childOccurrencePayloadBytes": len(child.content),
        "childSceneSourceBytes": len(child_source.content),
        "initialPlaybackApiMs": round(initial_api_ms, 3),
        "occurrenceScopeApiMs": round(scope_api_ms, 3),
    }
    record_property("instruction_playback_api", json.dumps(diagnostics))
    print(f"instruction-playback API diagnostic: {json.dumps(diagnostics)}")

    assert summary.status_code == root.status_code == source.status_code == 200
    assert child.status_code == child_source.status_code == 200
    assert len(root.json()["children"]) == min(physical_parts, 50)
    assert len(summary.content) < 1_000
    assert len(root.content) < 20_000
