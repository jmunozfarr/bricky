from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app
from app.models import ImportedModel, InventoryItem, ModelBomItem
from app.services.ldraw_catalog import rebuild_catalog
from app.services.ldraw_library import manifest_path_for

IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"


def write_part(root: Path, part_id: str, description: str | None = None) -> None:
    path = root / "parts" / f"{part_id}.dat"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"0 {description or f'Part {part_id}'}\n"
        f"0 Name: {part_id}.dat\n"
        "0 !LDRAW_ORG Part\n"
        "0 !CATEGORY Test\n"
        "3 16 0 0 0 1 0 0 0 1 0\n",
        encoding="utf-8",
    )


def write_moved(
    root: Path,
    part_id: str,
    target: str,
    *,
    reference_target: str | None = None,
) -> None:
    path = root / "parts" / f"{part_id}.dat"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"0 ~Moved to {target}\n"
        f"0 Name: {part_id}.dat\n"
        "0 !LDRAW_ORG Part\n"
        f"1 16 {IDENTITY} {reference_target or target}.dat\n",
        encoding="utf-8",
    )


def create_library(tmp_path: Path) -> Path:
    root = tmp_path / "official"
    (root / "parts").mkdir(parents=True)
    (root / "p").mkdir()
    (root / "LDConfig.ldr").write_text(
        "0 !COLOUR Blue CODE 1 VALUE #0055BF EDGE #333333\n"
        "0 !COLOUR Red CODE 4 VALUE #C91A09 EDGE #333333\n",
        encoding="utf-8",
    )
    write_part(root, "canonical")
    write_moved(root, "alias", "canonical")
    write_moved(root, "cycle-a", "cycle-b")
    write_moved(root, "cycle-b", "cycle-a")
    write_moved(root, "missing", "absent")
    write_part(root, "other")
    write_moved(root, "malformed", "canonical", reference_target="other")
    write_part(root, "shortcut", "~Shortcut test assembly")
    (root / "parts" / "shortcut.dat").write_text(
        "0 ~Shortcut test assembly\n"
        "0 Name: shortcut.dat\n"
        "0 !LDRAW_ORG Shortcut\n"
        f"1 16 {IDENTITY} canonical.dat\n",
        encoding="utf-8",
    )
    manifest_path_for(root).write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "installed_at": "2026-01-01T00:00:00+00:00",
                "source": "synthetic moved-alias test library",
                "archive_sha256": "c" * 64,
                "file_counts": {"dat": 8, "ldr": 1, "png": 0},
            }
        ),
        encoding="utf-8",
    )
    return root


def client_for(factory: sessionmaker[Session], root: Path, storage: Path) -> TestClient:
    return TestClient(
        create_app(
            library_root=root,
            session_factory=factory,
            model_storage_root=storage,
        )
    )


def upload(client: TestClient, source: bytes, filename: str = "aliases.ldr") -> httpx.Response:
    return client.post(
        "/api/models",
        files={"file": (filename, source, "text/plain")},
        data={"name": "Alias validation"},
    )


def reference(part_id: str, color_code: int) -> str:
    return f"1 {color_code} {IDENTITY} {part_id}.dat"


def test_import_canonicalizes_merges_colors_and_preserves_source(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    root = create_library(tmp_path)
    rebuild_catalog(catalog_session_factory, root)
    client = client_for(catalog_session_factory, root, tmp_path / "models")
    source = (
        "0 Original alias source\r\n"
        + "\r\n".join(
            [
                reference("ALIAS", 4),
                reference("alias", 4),
                reference("canonical", 4),
                reference("canonical", 4),
                reference("canonical", 4),
                reference("alias", 1),
            ]
        )
        + "\r\n"
    ).encode()

    created = upload(client, source)
    assert created.status_code == 201
    assert created.json()["importStatus"] == "ready"
    model_id = created.json()["modelId"]
    detail = client.get(f"/api/models/{model_id}").json()

    assert [(item["partId"], item["colorCode"], item["quantity"]) for item in detail["bom"]] == [
        ("canonical", 1, 1),
        ("canonical", 4, 5),
    ]
    assert detail["totalPartQuantity"] == 6
    assert detail["uniquePartColorCount"] == 2
    assert detail["issues"] == []
    assert detail["sourceSha256"] == hashlib.sha256(source).hexdigest()
    assert client.get(f"/api/models/{model_id}/source").content == source


def test_coverage_uses_canonical_inventory_and_catalog_rebuild_preserves_data(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    root = create_library(tmp_path)
    rebuild_catalog(catalog_session_factory, root)
    client = client_for(catalog_session_factory, root, tmp_path / "models")
    model_id = upload(client, (reference("alias", 4) + "\n").encode()).json()["modelId"]

    assert client.put("/api/inventory/items/alias/4", json={"quantity": 10}).status_code == 200
    alias_only = client.get(f"/api/models/{model_id}/coverage").json()
    assert alias_only["items"][0]["partId"] == "canonical"
    assert alias_only["items"][0]["ownedQuantity"] == 0
    assert alias_only["summary"]["pieceCoveragePercentage"] == 0

    assert client.put("/api/inventory/items/canonical/4", json={"quantity": 1}).status_code == 200
    canonical = client.get(f"/api/models/{model_id}/coverage").json()
    assert canonical["items"][0]["ownedQuantity"] == 1
    assert canonical["items"][0]["status"] == "complete"
    assert canonical["summary"]["pieceCoveragePercentage"] == 100

    rebuild_catalog(catalog_session_factory, root)
    with catalog_session_factory() as session:
        assert session.scalar(select(func.count(ImportedModel.id))) == 1
        assert session.scalar(select(func.count(ModelBomItem.id))) == 1
        assert session.scalar(select(func.count(InventoryItem.id))) == 2
    rebuilt = client.get(f"/api/models/{model_id}/coverage").json()
    assert rebuilt["summary"] == canonical["summary"]


def test_alias_failures_warn_and_retain_original_ids(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    root = create_library(tmp_path)
    rebuild_catalog(catalog_session_factory, root)
    client = client_for(catalog_session_factory, root, tmp_path / "models")
    source = (
        "\n".join(
            [
                reference("cycle-a", 4),
                reference("missing", 4),
                reference("malformed", 4),
                reference("shortcut", 4),
                reference("canonical", 4),
            ]
        )
        + "\n"
    ).encode()

    created = upload(client, source)
    assert created.status_code == 201
    assert created.json()["importStatus"] == "ready_with_warnings"
    detail = client.get(f"/api/models/{created.json()['modelId']}").json()
    assert {item["partId"] for item in detail["bom"]} == {
        "canonical",
        "cycle-a",
        "malformed",
        "missing",
        "shortcut",
    }
    assert {issue["code"] for issue in detail["issues"]} == {
        "moved_alias_cycle",
        "moved_alias_malformed",
        "moved_alias_missing_target",
    }
