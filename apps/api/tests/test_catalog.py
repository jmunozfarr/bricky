from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app
from app.models import Part
from app.services.ldraw_catalog import CatalogError, get_catalog_status, rebuild_catalog
from app.services.ldraw_library import manifest_path_for


FINGERPRINT = "a" * 64


def write_part(
    library_root: Path,
    relative_path: str,
    description: str,
    category: str,
    author: str = "Test Author",
) -> None:
    path = library_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"0 {description}\n"
        f"0 Name: {path.name}\n"
        f"0 Author: {author}\n"
        "0 !LDRAW_ORG Part\n"
        "0 !LICENSE Licensed for testing\n"
        f"0 !CATEGORY {category}\n"
        "0 !KEYWORDS sample, test\n"
        "3 16 0 0 0 1 0 0 0 1 0\n",
        encoding="utf-8",
    )


def create_synthetic_library(tmp_path: Path) -> Path:
    root = tmp_path / "official"
    (root / "parts").mkdir(parents=True)
    (root / "p").mkdir()
    (root / "p" / "box.dat").write_text("0 Primitive\n", encoding="utf-8")
    (root / "LDConfig.ldr").write_text(
        "0 !COLOUR Red CODE 4 VALUE #C91A09 EDGE #333333\n"
        "0 !COLOUR Blue CODE 1 VALUE #0055BF EDGE 4 ALPHA 240\n",
        encoding="utf-8",
    )
    write_part(root, "parts/3001.dat", "Brick 2 x 4", "Brick", "James Jessiman")
    write_part(root, "parts/3002.dat", "Plate 2 x 3", "Plate")
    write_part(root, "parts/2456.dat", "Brick 2 x 6", "Brick")
    write_part(root, "parts/s/3001s01.dat", "Brick Subpart", "Subpart")
    manifest_path_for(root).write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "installed_at": "2026-01-01T00:00:00+00:00",
                "source": "synthetic test archive",
                "archive_sha256": FINGERPRINT,
                "file_counts": {"dat": 5, "ldr": 1, "png": 0},
            }
        ),
        encoding="utf-8",
    )
    return root


def test_successful_rebuild_and_idempotency(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    root = create_synthetic_library(tmp_path)

    first = rebuild_catalog(catalog_session_factory, root)
    second = rebuild_catalog(catalog_session_factory, root)

    assert first.indexed_part_count == 3
    assert first.skipped_subpart_count == 1
    assert first.indexed_color_count == 2
    assert second.indexed_part_count == first.indexed_part_count
    with catalog_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Part)) == 3


def test_failed_rebuild_rolls_back_previous_catalog(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    root = create_synthetic_library(tmp_path)
    rebuild_catalog(catalog_session_factory, root)
    (root / "LDConfig.ldr").write_text(
        "0 !COLOUR Red CODE 4 VALUE #C91A09 EDGE #333333\n"
        "0 !COLOUR Duplicate CODE 4 VALUE #FFFFFF EDGE #333333\n",
        encoding="utf-8",
    )

    with pytest.raises(CatalogError, match="Database rebuild failed"):
        rebuild_catalog(catalog_session_factory, root)

    with catalog_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Part)) == 3
        assert session.scalar(select(Part.name).where(Part.part_id == "3001")) == "Brick 2 x 4"


def test_catalog_status_before_current_and_stale(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    root = create_synthetic_library(tmp_path)
    with catalog_session_factory() as session:
        before = get_catalog_status(session, root)
    assert before.library_installed is True
    assert before.indexed is False
    assert before.stale is False

    rebuild_catalog(catalog_session_factory, root)
    with catalog_session_factory() as session:
        current = get_catalog_status(session, root)
    assert current.indexed is True
    assert current.stale is False

    manifest = json.loads(manifest_path_for(root).read_text())
    manifest["archive_sha256"] = "b" * 64
    manifest_path_for(root).write_text(json.dumps(manifest), encoding="utf-8")
    with catalog_session_factory() as session:
        stale = get_catalog_status(session, root)
    assert stale.stale is True


def test_catalog_api_search_filters_pagination_and_details(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    root = create_synthetic_library(tmp_path)
    rebuild_catalog(catalog_session_factory, root)
    client = TestClient(create_app(root, catalog_session_factory))

    id_search = client.get("/api/parts", params={"query": "3001"})
    name_search = client.get("/api/parts", params={"query": "brick"})
    category = client.get("/api/parts", params={"category": "Plate"})
    paged = client.get("/api/parts", params={"page": 2, "pageSize": 1})
    detail = client.get("/api/parts/3001")
    unknown = client.get("/api/parts/unknown")
    categories = client.get("/api/parts/categories")
    colors = client.get("/api/colors")

    assert id_search.json()["items"][0]["partId"] == "3001"
    assert name_search.json()["totalItems"] == 2
    assert category.json()["items"][0]["partId"] == "3002"
    assert paged.json()["page"] == 2
    assert paged.json()["pageSize"] == 1
    assert paged.json()["totalPages"] == 3
    assert all(item["partId"] != "3001s01" for item in name_search.json()["items"])
    assert unknown.status_code == 404
    assert detail.status_code == 200
    render_url = detail.json()["renderAssetUrl"]
    assert render_url == "/api/ldraw/parts/3001.dat"
    assert ".." not in render_url and not render_url.startswith("/data")
    assert [item["name"] for item in categories.json()] == ["Brick", "Plate"]
    assert [item["code"] for item in colors.json()] == [1, 4]


def test_catalog_api_reports_current_index(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    root = create_synthetic_library(tmp_path)
    rebuild_catalog(catalog_session_factory, root)
    response = TestClient(create_app(root, catalog_session_factory)).get(
        "/api/catalog/status"
    )

    assert response.status_code == 200
    assert response.json()["libraryInstalled"] is True
    assert response.json()["indexed"] is True
    assert response.json()["stale"] is False
    assert response.json()["partCount"] == 3
