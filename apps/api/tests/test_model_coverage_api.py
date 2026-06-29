from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select
from sqlalchemy.engine import Engine
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
from app.services.local_workspace import resolve_local_workspace


def client_for(factory: sessionmaker[Session], root: Path) -> TestClient:
    return TestClient(
        create_app(
            library_root=root / "library",
            session_factory=factory,
            model_storage_root=root / "models",
        )
    )


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


def seed_model(
    factory: sessionmaker[Session],
    bom: list[tuple[str, int, int]],
    *,
    workspace_slug: str = "local-default",
    name: str = "Coverage model",
) -> uuid.UUID:
    public_id = uuid.uuid4()
    with factory.begin() as session:
        if workspace_slug == "local-default":
            workspace = resolve_local_workspace(session)
        else:
            workspace = Workspace(slug=workspace_slug, name=workspace_slug)
            session.add(workspace)
            session.flush()
        model = ImportedModel(
            public_id=public_id,
            workspace_id=workspace.id,
            name=name,
            original_filename=f"{public_id}.ldr",
            safe_filename="model.ldr",
            source_format="ldr",
            relative_storage_path=f"originals/{public_id}/model.ldr",
            source_sha256=uuid.uuid4().hex * 2,
            import_status="ready",
            declared_step_count=1,
            total_part_quantity=sum(quantity for _part, _color, quantity in bom),
            unique_part_color_count=len(bom),
            unresolved_reference_count=0,
        )
        session.add(model)
        session.flush()
        session.add_all(
            ModelBomItem(
                model_id=model.id,
                part_id=part_id,
                color_code=color_code,
                quantity=quantity,
            )
            for part_id, color_code, quantity in bom
        )
    return public_id


def test_exact_coverage_aggregation_order_and_filters(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    model_id = seed_model(
        catalog_session_factory,
        [("3001", 4, 4), ("3001", 1, 3), ("3002", 4, 2)],
    )
    with catalog_session_factory.begin() as session:
        workspace = resolve_local_workspace(session)
        session.add_all(
            [
                InventoryItem(workspace_id=workspace.id, part_id="3001", color_code=4, quantity=2),
                InventoryItem(workspace_id=workspace.id, part_id="3001", color_code=1, quantity=8),
                InventoryItem(workspace_id=workspace.id, part_id="3002", color_code=1, quantity=50),
            ]
        )
    client = client_for(catalog_session_factory, tmp_path)
    response = client.get(f"/api/models/{model_id}/coverage")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "totalRequiredQuantity": 9,
        "totalAvailableQuantity": 5,
        "totalMissingQuantity": 4,
        "uniqueItemCount": 3,
        "completeItemCount": 1,
        "partialItemCount": 1,
        "missingItemCount": 1,
        "pieceCoveragePercentage": 55.56,
        "fullyBuildable": False,
    }
    assert [item["status"] for item in payload["items"]] == [
        "missing",
        "partial",
        "complete",
    ]
    assert payload["items"][0]["partId"] == "3002"
    assert payload["items"][0]["ownedQuantity"] == 0
    assert payload["items"][1]["missingQuantity"] == 2
    assert payload["items"][2]["availableQuantity"] == 3

    filtered = client.get(f"/api/models/{model_id}/coverage?status=partial").json()
    searched = client.get(f"/api/models/{model_id}/coverage?query=2+x+3").json()
    assert filtered["summary"] == payload["summary"]
    assert [item["status"] for item in filtered["items"]] == ["partial"]
    assert searched["summary"] == payload["summary"]
    assert [item["partId"] for item in searched["items"]] == ["3002"]
    assert client.get(f"/api/models/{model_id}/coverage?status=unknown").status_code == 422


def test_inventory_mutations_refresh_coverage_without_reimport(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    model_id = seed_model(catalog_session_factory, [("3001", 4, 4)])
    client = client_for(catalog_session_factory, tmp_path)
    baseline = client.get(f"/api/models/{model_id}/coverage").json()
    with catalog_session_factory() as session:
        model_count = session.scalar(select(func.count(ImportedModel.id)))
        source_hash = session.scalar(select(ImportedModel.source_sha256))

    assert client.put(
        "/api/inventory/items/3001/4", json={"quantity": 2}
    ).status_code == 200
    partial = client.get(f"/api/models/{model_id}/coverage").json()
    assert partial["items"][0]["ownedQuantity"] == 2
    assert partial["items"][0]["missingQuantity"] == 2
    assert partial["items"][0]["status"] == "partial"
    assert partial["summary"]["pieceCoveragePercentage"] == 50

    assert client.put(
        "/api/inventory/items/3001/4", json={"quantity": 7}
    ).status_code == 200
    complete = client.get(f"/api/models/{model_id}/coverage").json()
    assert complete["items"][0]["availableQuantity"] == 4
    assert complete["items"][0]["missingQuantity"] == 0
    assert complete["items"][0]["status"] == "complete"
    assert complete["summary"]["fullyBuildable"] is True

    assert client.put(
        "/api/inventory/items/3001/1", json={"quantity": 99}
    ).status_code == 200
    wrong_color = client.get(f"/api/models/{model_id}/coverage").json()
    assert wrong_color["items"][0]["ownedQuantity"] == 7

    assert client.delete("/api/inventory/items/3001/4").status_code == 204
    restored = client.get(f"/api/models/{model_id}/coverage").json()
    assert restored == baseline
    with catalog_session_factory() as session:
        assert session.scalar(select(func.count(ImportedModel.id))) == model_count
        assert session.scalar(select(ImportedModel.source_sha256)) == source_hash


def test_unknown_metadata_colors_and_workspace_scope(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    local_model_id = seed_model(catalog_session_factory, [("custom-x", 999, 2)])
    other_model_id = seed_model(
        catalog_session_factory,
        [("custom-x", 999, 2)],
        workspace_slug="other",
    )
    with catalog_session_factory.begin() as session:
        local = resolve_local_workspace(session)
        other = session.scalar(select(Workspace).where(Workspace.slug == "other"))
        assert other is not None
        session.add_all(
            [
                InventoryItem(workspace_id=local.id, part_id="CUSTOM-X", color_code=999, quantity=1),
                InventoryItem(workspace_id=other.id, part_id="custom-x", color_code=999, quantity=50),
            ]
        )
    client = client_for(catalog_session_factory, tmp_path)
    payload = client.get(f"/api/models/{local_model_id}/coverage").json()
    assert payload["items"][0]["ownedQuantity"] == 1
    assert payload["items"][0]["status"] == "partial"
    assert payload["items"][0]["partName"] == "custom-x"
    assert payload["items"][0]["colorName"] == "Color 999"
    assert payload["items"][0]["catalogAvailable"] is False
    assert client.get(f"/api/models/{other_model_id}/coverage").status_code == 404
    assert client.get(f"/api/models/{uuid.uuid4()}/coverage").status_code == 404


def test_empty_bom_reads_do_not_mutate_inventory_and_catalog_loss_is_safe(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    empty_id = seed_model(catalog_session_factory, [])
    model_id = seed_model(catalog_session_factory, [("3001", 4, 1)])
    with catalog_session_factory.begin() as session:
        workspace = resolve_local_workspace(session)
        session.add(InventoryItem(workspace_id=workspace.id, part_id="3001", color_code=4, quantity=1))
    client = client_for(catalog_session_factory, tmp_path)
    empty = client.get(f"/api/models/{empty_id}/coverage").json()["summary"]
    assert empty["pieceCoveragePercentage"] == 100
    assert empty["fullyBuildable"] is True

    before = client.get(f"/api/models/{model_id}/coverage").json()
    with catalog_session_factory() as session:
        inventory_before = session.scalar(select(InventoryItem.quantity))
    client.get(f"/api/models/{model_id}/coverage")
    with catalog_session_factory() as session:
        assert session.scalar(select(InventoryItem.quantity)) == inventory_before
    with catalog_session_factory.begin() as session:
        session.execute(delete(Part))
        session.execute(delete(LDrawColor))
    after = client.get(f"/api/models/{model_id}/coverage").json()
    assert after["summary"] == before["summary"]
    assert after["items"][0]["catalogAvailable"] is False


def test_model_list_and_overview_readiness_use_bounded_inventory_queries(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    seed_model(catalog_session_factory, [("3001", 4, 2)], name="First")
    seed_model(catalog_session_factory, [("3002", 1, 1)], name="Second")
    client = client_for(catalog_session_factory, tmp_path)
    bind = catalog_session_factory.kw["bind"]
    assert isinstance(bind, Engine)
    inventory_selects = 0

    def count_inventory_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal inventory_selects
        if statement.lstrip().upper().startswith("SELECT") and "inventory_items" in statement:
            inventory_selects += 1

    event.listen(bind, "before_cursor_execute", count_inventory_selects)
    try:
        listing = client.get("/api/models?pageSize=100")
    finally:
        event.remove(bind, "before_cursor_execute", count_inventory_selects)
    assert listing.status_code == 200
    assert inventory_selects == 1
    assert len(listing.json()["items"]) == 2
    assert all(item["coverage"] is not None for item in listing.json()["items"])
    readiness = client.get("/api/models/readiness-summary").json()
    assert readiness == {
        "totalModels": 2,
        "fullyBuildableModels": 0,
        "incompleteModels": 2,
        "totalMissingQuantity": 3,
    }
