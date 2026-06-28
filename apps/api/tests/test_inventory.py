from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app
from app.models import InventoryItem, LDrawColor, Part, Workspace
from app.services.ldraw_catalog import rebuild_catalog
from app.services.ldraw_library import manifest_path_for
from app.services.local_workspace import resolve_local_workspace


def seed_catalog(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        session.add_all(
            [
                Part(
                    part_id="3001",
                    name="Brick 2 x 4",
                    relative_path="parts/3001.dat",
                    author="James Jessiman",
                    category="Brick",
                    org_classification="Part",
                    license="Test license",
                    keywords="brick, basic",
                    is_subpart=False,
                    is_shortcut=False,
                ),
                Part(
                    part_id="3002",
                    name="Plate 2 x 3",
                    relative_path="parts/3002.dat",
                    author="Test Author",
                    category="Plate",
                    org_classification="Part",
                    license="Test license",
                    keywords=None,
                    is_subpart=False,
                    is_shortcut=False,
                ),
                LDrawColor(
                    code=1,
                    name="Blue",
                    value_hex="#0055BF",
                    edge_hex="#333333",
                    alpha=255,
                    luminance=None,
                    finish=None,
                ),
                LDrawColor(
                    code=4,
                    name="Red",
                    value_hex="#C91A09",
                    edge_hex="#333333",
                    alpha=255,
                    luminance=None,
                    finish=None,
                ),
            ]
        )


def client_for(factory: sessionmaker[Session], tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "missing-library", factory))


def test_local_workspace_creation_is_idempotent(
    catalog_session_factory: sessionmaker[Session],
) -> None:
    with catalog_session_factory.begin() as session:
        first = resolve_local_workspace(session)
        second = resolve_local_workspace(session)
        assert first.id == second.id
    with catalog_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Workspace)) == 1


def test_empty_inventory_summary(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    response = client_for(catalog_session_factory, tmp_path).get("/api/inventory/summary")

    assert response.status_code == 200
    assert response.json() == {
        "totalQuantity": 0,
        "uniqueItems": 0,
        "uniqueParts": 0,
    }


def test_create_update_and_separate_part_color_items(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)

    created = client.put("/api/inventory/items/3001/4", json={"quantity": 5})
    updated = client.put("/api/inventory/items/3001/4", json={"quantity": 8})
    second_color = client.put("/api/inventory/items/3001/1", json={"quantity": 2})
    second_part = client.put("/api/inventory/items/3002/4", json={"quantity": 3})

    assert created.status_code == 200 and created.json()["quantity"] == 5
    assert updated.json()["quantity"] == 8
    assert second_color.json()["colorCode"] == 1
    assert second_part.json()["partId"] == "3002"
    with catalog_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(InventoryItem)) == 3


def test_unknown_catalog_values_and_quantity_validation(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)

    assert client.put("/api/inventory/items/unknown/4", json={"quantity": 1}).status_code == 404
    assert client.put("/api/inventory/items/3001/999", json={"quantity": 1}).status_code == 404
    for quantity in (0, -1, 1_000_000):
        assert client.put(
            "/api/inventory/items/3001/4", json={"quantity": quantity}
        ).status_code == 422


def test_deletion_is_idempotent(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    client.put("/api/inventory/items/3001/4", json={"quantity": 1})

    assert client.delete("/api/inventory/items/3001/4").status_code == 204
    assert client.delete("/api/inventory/items/3001/4").status_code == 204


def test_inventory_search_filters_pagination_variants_and_summary(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    client.put("/api/inventory/items/3001/4", json={"quantity": 8})
    client.put("/api/inventory/items/3001/1", json={"quantity": 2})
    client.put("/api/inventory/items/3002/4", json={"quantity": 3})

    exact = client.get("/api/inventory/items", params={"query": "3001"}).json()
    name = client.get("/api/inventory/items", params={"query": "plate"}).json()
    category = client.get("/api/inventory/items", params={"category": "Brick"}).json()
    color = client.get("/api/inventory/items", params={"colorCode": 1}).json()
    page = client.get(
        "/api/inventory/items", params={"page": 2, "pageSize": 1}
    ).json()
    variants = client.get("/api/inventory/items/3001").json()
    summary = client.get("/api/inventory/summary").json()

    assert exact["totalItems"] == 2
    assert all(item["partId"] == "3001" for item in exact["items"])
    assert name["items"][0]["partId"] == "3002"
    assert category["totalItems"] == 2
    assert color["items"][0]["colorCode"] == 1
    assert page["page"] == 2 and page["totalPages"] == 3
    assert [item["colorCode"] for item in variants] == [1, 4]
    assert summary == {"totalQuantity": 13, "uniqueItems": 3, "uniqueParts": 2}


def test_missing_catalog_metadata_keeps_inventory_visible(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    client.put("/api/inventory/items/3001/4", json={"quantity": 5})
    with catalog_session_factory.begin() as session:
        session.execute(delete(Part).where(Part.part_id == "3001"))

    item = client.get("/api/inventory/items", params={"query": "3001"}).json()[
        "items"
    ][0]

    assert item["quantity"] == 5
    assert item["catalogAvailable"] is False
    assert item["renderAssetUrl"] is None


def test_catalog_rebuild_preserves_inventory(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    client.put("/api/inventory/items/3001/4", json={"quantity": 5})

    root = tmp_path / "official"
    (root / "parts").mkdir(parents=True)
    (root / "p").mkdir()
    (root / "p" / "box.dat").write_text("0 Primitive\n")
    (root / "LDConfig.ldr").write_text(
        "0 !COLOUR Red CODE 4 VALUE #C91A09 EDGE #333333\n"
    )
    (root / "parts" / "3001.dat").write_text(
        "0 Brick 2 x 4\n0 !CATEGORY Brick\n3 16 0 0 0 1 0 0 0 1 0\n"
    )
    manifest_path_for(root).write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "installed_at": "2026-01-01T00:00:00+00:00",
                "source": "synthetic",
                "archive_sha256": "c" * 64,
                "file_counts": {"dat": 2, "ldr": 1, "png": 0},
            }
        )
    )

    rebuild_catalog(catalog_session_factory, root)

    with catalog_session_factory() as session:
        item = session.scalar(select(InventoryItem))
        assert item is not None and item.quantity == 5


def test_request_cannot_choose_another_workspace(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    with catalog_session_factory.begin() as session:
        session.add(Workspace(slug="other", name="Other workspace"))
    response = client_for(catalog_session_factory, tmp_path).put(
        "/api/inventory/items/3001/4",
        json={"quantity": 5, "workspaceId": 2},
    )

    assert response.status_code == 422
    with catalog_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(InventoryItem)) == 0
