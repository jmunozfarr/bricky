from __future__ import annotations

from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app
from app.models import (
    ImportedModel,
    InventoryItem,
    LDrawColor,
    ModelBomItem,
    Part,
    Workspace,
)
from app.services.instruction_graph import InstructionGraphLimits
from app.services.local_workspace import resolve_local_workspace

IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"


def source(part: str = "3001", color: int = 4) -> bytes:
    return f"0 Imported model\n1 {color} {IDENTITY} {part}.dat\n".encode()


def seed_catalog(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        session.add_all(
            [
                Part(
                    part_id="3001",
                    name="Brick 2 x 4",
                    relative_path="parts/3001.dat",
                    category="Brick",
                    is_subpart=False,
                    is_shortcut=False,
                ),
                Part(
                    part_id="3002",
                    name="Brick 2 x 3",
                    relative_path="parts/3002.dat",
                    category="Brick",
                    is_subpart=False,
                    is_shortcut=False,
                ),
                LDrawColor(code=4, name="Red", value_hex="#C91A09", alpha=255),
                LDrawColor(code=1, name="Blue", value_hex="#0055BF", alpha=255),
            ]
        )


def client_for(
    factory: sessionmaker[Session],
    storage: Path,
    maximum: int = 1024 * 1024,
    graph_limits: InstructionGraphLimits | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            library_root=storage / "library",
            session_factory=factory,
            model_storage_root=storage / "models",
            model_max_upload_bytes=maximum,
            instruction_graph_limits=graph_limits,
        )
    )


def upload(client: TestClient, content: bytes, filename: str = "demo.ldr") -> httpx.Response:
    return client.post(
        "/api/models",
        files={"file": (filename, content, "text/plain")},
        data={"name": "Test model"},
    )


def test_successful_ldr_import_preserves_bytes_and_exposes_detail(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    original = b"\xef\xbb\xbf0 Exact bytes\r\n" + source()
    response = upload(client, original, "unsafe name.LDR")
    assert response.status_code == 201
    model_id = response.json()["modelId"]
    detail = client.get(f"/api/models/{model_id}")
    assert detail.status_code == 200
    assert detail.json()["bom"] == [
        {
            "partId": "3001",
            "partName": "Brick 2 x 4",
            "category": "Brick",
            "colorCode": 4,
            "colorName": "Red",
            "colorHex": "#C91A09",
            "quantity": 1,
            "catalogAvailable": True,
            "renderAssetUrl": "/api/ldraw/parts/3001.dat",
        }
    ]
    served = client.get(f"/api/models/{model_id}/source")
    assert served.status_code == 200
    assert served.content == original
    stored = list((tmp_path / "models" / "originals" / model_id).iterdir())
    assert len(stored) == 1 and stored[0].read_bytes() == original


def test_mpd_warning_duplicate_search_and_pagination(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    mpd = "\n".join(
        [
            "0 FILE main.ldr",
            f"1 4 {IDENTITY} sub.ldr",
            "0 STEP",
            "0 FILE sub.ldr",
            f"1 16 {IDENTITY} 3001.dat",
            f"1 4 {IDENTITY} missing.ldr",
        ]
    ).encode()
    first = upload(client, mpd, "demo.mpd")
    assert first.status_code == 201
    assert first.json()["importStatus"] == "ready_with_warnings"
    assert first.json()["declaredStepCount"] == 2
    duplicate = upload(client, mpd, "other.mpd")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["existingModelId"] == first.json()["modelId"]
    upload(client, source("3002", 1), "second.ldr")
    listing = client.get("/api/models?query=second&page=1&pageSize=1")
    assert listing.status_code == 200
    assert listing.json()["totalItems"] == 1
    detail = client.get(f"/api/models/{first.json()['modelId']}").json()
    assert detail["issues"][0]["code"] == "unresolved_reference"


def test_instruction_graph_endpoint_expands_distinct_occurrences(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    mpd = "\n".join(
        [
            "0 FILE main.ldr",
            f"1 4 {IDENTITY} module.ldr",
            "0 STEP",
            "1 1 20 0 0 0 -1 0 1 0 0 0 0 1 module.ldr",
            "0 FILE module.ldr",
            f"1 16 {IDENTITY} 3001.dat",
        ]
    ).encode()
    model_id = upload(client, mpd, "hierarchy.mpd").json()["modelId"]

    response = client.get(f"/api/models/{model_id}/instruction-graph")

    assert response.status_code == 200
    body = response.json()
    assert body["modelId"] == model_id
    assert body["modelDefinitionCount"] == 2
    assert body["expandedOccurrenceCount"] == 3
    assert body["instructionNodeCount"] == 4
    assert body["traversalOrder"] == ["occ-000001", "occ-000002", "occ-000003"]
    assert [item["attachmentStep"] for item in body["occurrences"][1:]] == [1, 2]
    assert body["occurrences"][2]["localTransform"] == {
        "translation": [20.0, 0.0, 0.0],
        "matrix": [0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    }
    assert body["limits"] == {
        "maximumNestingDepth": 32,
        "maximumExpandedOccurrences": 10000,
        "maximumInstructionNodes": 100000,
    }


def test_instruction_graph_endpoint_returns_limit_issues(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(
        catalog_session_factory,
        tmp_path,
        graph_limits=InstructionGraphLimits(max_expanded_occurrences=1),
    )
    mpd = "\n".join(
        [
            "0 FILE main.ldr",
            f"1 4 {IDENTITY} module.ldr",
            "0 FILE module.ldr",
            f"1 16 {IDENTITY} 3001.dat",
        ]
    ).encode()
    model_id = upload(client, mpd, "limited.mpd").json()["modelId"]

    body = client.get(f"/api/models/{model_id}/instruction-graph").json()

    assert body["truncated"] is True
    assert body["expandedOccurrenceCount"] == 1
    assert body["issues"] == [
        {
            "severity": "warning",
            "code": "expanded_occurrence_limit_exceeded",
            "message": "Submodel expansion stopped at the configured occurrence limit",
            "sourceSubmodelName": "main.ldr",
            "sourceFilename": "module.ldr",
            "occurrenceId": "occ-000001",
            "configuredLimit": 1,
        }
    ]


def test_validation_rejections_leave_no_partial_data(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path, maximum=20)
    assert upload(client, source(), "model.txt").status_code == 422
    assert upload(client, b"0 Model\x00binary", "model.ldr").status_code == 422
    assert upload(client, source(), "model.ldr").status_code == 413
    with catalog_session_factory() as session:
        assert session.scalar(select(func.count(ImportedModel.id))) == 0
    model_root = tmp_path / "models"
    assert not model_root.exists() or list(model_root.iterdir()) == []


def test_delete_removes_source_and_preserves_inventory(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    with catalog_session_factory.begin() as session:
        workspace = resolve_local_workspace(session)
        session.add(
            InventoryItem(workspace_id=workspace.id, part_id="3001", color_code=4, quantity=7)
        )
    client = client_for(catalog_session_factory, tmp_path)
    created = upload(client, source()).json()
    model_id = created["modelId"]
    assert client.delete(f"/api/models/{model_id}").status_code == 204
    assert client.delete(f"/api/models/{model_id}").status_code == 204
    assert client.get(f"/api/models/{model_id}").status_code == 404
    assert not (tmp_path / "models" / "originals" / model_id).exists()
    with catalog_session_factory() as session:
        assert session.scalar(select(func.count(InventoryItem.id))) == 1
        assert session.scalar(select(func.count(ModelBomItem.id))) == 0


def test_source_path_is_not_a_generic_file_reader(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    model_id = upload(client, source()).json()["modelId"]
    with catalog_session_factory.begin() as session:
        model = session.scalar(select(ImportedModel))
        assert model is not None
        model.relative_storage_path = "../secret.ldr"
    assert client.get(f"/api/models/{model_id}/source").status_code == 404
    assert client.get(f"/api/models/{model_id}/instruction-graph").status_code == 404
    assert client.get("/api/models/not-a-uuid/source").status_code == 422


def test_upload_cannot_select_another_workspace(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    with catalog_session_factory.begin() as session:
        session.add(Workspace(slug="other", name="Other workspace"))
    client = client_for(catalog_session_factory, tmp_path)
    response = client.post(
        "/api/models",
        files={"file": ("model.ldr", source(), "text/plain")},
        data={"name": "Scoped model", "workspaceId": "other"},
    )
    assert response.status_code == 201
    with catalog_session_factory() as session:
        model = session.scalar(select(ImportedModel))
        assert model is not None
        workspace = session.get(Workspace, model.workspace_id)
        assert workspace is not None and workspace.slug == "local-default"
