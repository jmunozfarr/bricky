from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app
from app.models import InventoryItem, LDrawColor, Part
from app.services.ldraw_catalog import rebuild_catalog
from app.services.ldraw_library import manifest_path_for

IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"


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
                    part_id="3070b",
                    name="Tile 1 x 1",
                    relative_path="parts/3070b.dat",
                    author="Test Author",
                    category="Tile",
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


def client_for(
    factory: sessionmaker[Session],
    tmp_path: Path,
    *,
    library_root: Path | None = None,
    max_upload_bytes: int | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            library_root or tmp_path / "missing-library",
            factory,
            inventory_max_upload_bytes=max_upload_bytes,
        )
    )


def csv_bytes(*rows: str, header: str = "part_id,color_code,quantity") -> bytes:
    return "\n".join((header, *rows, "")).encode()


def post_preview(
    client: TestClient,
    content: bytes,
    strategy: str = "add",
    filename: str = "inventory.csv",
) -> httpx.Response:
    return client.post(
        "/api/inventory/import/preview",
        files={"file": (filename, content, "text/csv")},
        data={"strategy": strategy},
    )


def post_apply(
    client: TestClient,
    content: bytes,
    strategy: str = "add",
    include_unknown: bool = True,
    filename: str = "inventory.csv",
) -> httpx.Response:
    return client.post(
        "/api/inventory/import/apply",
        files={"file": (filename, content, "text/csv")},
        data={
            "strategy": strategy,
            "includeUnknown": "true" if include_unknown else "false",
        },
    )


def inventory_rows(factory: sessionmaker[Session]) -> dict[tuple[str, int], int]:
    with factory() as session:
        return {
            (item.part_id, item.color_code): item.quantity
            for item in session.scalars(select(InventoryItem))
        }


def write_part(root: Path, part_id: str) -> None:
    path = root / "parts" / f"{part_id}.dat"
    path.write_text(
        f"0 Part {part_id}\n"
        f"0 Name: {part_id}.dat\n"
        "0 !LDRAW_ORG Part\n"
        "0 !CATEGORY Test\n"
        "3 16 0 0 0 1 0 0 0 1 0\n",
        encoding="utf-8",
    )


def write_moved(root: Path, part_id: str, target: str) -> None:
    path = root / "parts" / f"{part_id}.dat"
    path.write_text(
        f"0 ~Moved to {target}\n"
        f"0 Name: {part_id}.dat\n"
        "0 !LDRAW_ORG Part\n"
        f"1 16 {IDENTITY} {target}.dat\n",
        encoding="utf-8",
    )


def create_alias_library(tmp_path: Path) -> Path:
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
    manifest_path_for(root).write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "installed_at": "2026-01-01T00:00:00+00:00",
                "source": "synthetic inventory-import test library",
                "archive_sha256": "c" * 64,
                "file_counts": {"dat": 2, "ldr": 1, "png": 0},
            }
        ),
        encoding="utf-8",
    )
    return root


def test_preview_reports_buckets_issues_and_row_details(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    assert client.put("/api/inventory/items/3001/4", json={"quantity": 2}).status_code == 200

    content = csv_bytes(
        "3001,1,3",
        "3001,4,5",
        "3070B,4,1",
        "3070b,4,2",
        "mystery,4,2",
        "3001,99,1",
        "3001,16,1",
        "3001,4,abc",
        header="Part_ID,Color_Code,Quantity,Notes",
    )
    response = post_preview(client, content)

    assert response.status_code == 200
    payload = response.json()
    assert payload["fileName"] == "inventory.csv"
    assert payload["strategy"] == "add"
    assert payload["totalDataRows"] == 8
    assert payload["plannedRowCount"] == 5
    assert payload["duplicateRowCount"] == 1
    assert payload["aliasCanonicalizedCount"] == 0
    assert payload["ignoredColumns"] == ["Notes"]
    assert payload["invalidRowCount"] == 2
    assert payload["known"] == {
        "rowCount": 3,
        "createCount": 2,
        "updateCount": 1,
        "unchangedCount": 0,
        "quantityDelta": 11,
        "missingPartCount": 0,
        "missingColorCount": 0,
    }
    assert payload["unknown"] == {
        "rowCount": 2,
        "createCount": 2,
        "updateCount": 0,
        "unchangedCount": 0,
        "quantityDelta": 3,
        "missingPartCount": 1,
        "missingColorCount": 1,
    }
    assert payload["rowsTruncated"] is False
    assert payload["issuesTruncated"] is False
    assert [(issue["lineNumber"], issue["code"]) for issue in payload["issues"]] == [
        (8, "non_physical_color"),
        (9, "bad_quantity"),
    ]

    rows = payload["rows"]
    assert [
        (row["partId"], row["colorCode"], row["change"], row["unknownReason"]) for row in rows
    ] == [
        ("3001", 99, "create", "color"),
        ("mystery", 4, "create", "part"),
        ("3001", 1, "create", None),
        ("3070b", 4, "create", None),
        ("3001", 4, "update", None),
    ]
    merged_casing = rows[3]
    assert merged_casing["sourcePartId"] == "3070B"
    assert merged_casing["quantity"] == 3
    assert merged_casing["canonicalizedFrom"] is None
    assert merged_casing["partName"] == "Tile 1 x 1"
    assert merged_casing["colorName"] == "Red"
    updated = rows[4]
    assert updated["currentQuantity"] == 2
    assert updated["resultingQuantity"] == 7
    unknown_part = rows[1]
    assert unknown_part["partName"] is None
    assert unknown_part["renderAssetUrl"] is None


def test_preview_add_and_replace_compute_resulting_quantities(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    assert client.put("/api/inventory/items/3001/4", json={"quantity": 2}).status_code == 200
    content = csv_bytes("3001,4,5")

    added = post_preview(client, content, strategy="add").json()
    replaced = post_preview(client, content, strategy="replace").json()

    assert added["rows"][0]["resultingQuantity"] == 7
    assert replaced["rows"][0]["resultingQuantity"] == 5
    assert added["known"]["quantityDelta"] == 5
    assert replaced["known"]["quantityDelta"] == 3


def test_apply_add_sums_and_clamps_quantities(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    client.put("/api/inventory/items/3001/4", json={"quantity": 999_998})
    client.put("/api/inventory/items/3001/1", json={"quantity": 2})

    response = post_apply(client, csv_bytes("3001,4,5", "3001,1,3", "3070b,4,6"))

    assert response.status_code == 200
    assert response.json() == {
        "strategy": "add",
        "includeUnknown": True,
        "appliedRowCount": 3,
        "createdCount": 1,
        "updatedCount": 2,
        "unchangedCount": 0,
        "skippedUnknownRowCount": 0,
        "invalidRowCount": 0,
        "quantityDelta": 10,
    }
    assert inventory_rows(catalog_session_factory) == {
        ("3001", 4): 999_999,
        ("3001", 1): 5,
        ("3070b", 4): 6,
    }


def test_apply_replace_overwrites_and_repeat_is_unchanged(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    client.put("/api/inventory/items/3001/4", json={"quantity": 2})
    content = csv_bytes("3001,4,6")

    first = post_apply(client, content, strategy="replace").json()
    second = post_apply(client, content, strategy="replace").json()

    assert first["updatedCount"] == 1 and first["quantityDelta"] == 4
    assert second["unchangedCount"] == 1 and second["quantityDelta"] == 0
    assert inventory_rows(catalog_session_factory) == {("3001", 4): 6}


def test_double_apply_add_doubles_quantities(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    content = csv_bytes("3001,4,4")

    assert post_apply(client, content).json()["createdCount"] == 1
    assert post_apply(client, content).json()["updatedCount"] == 1
    assert inventory_rows(catalog_session_factory) == {("3001", 4): 8}


def test_apply_merges_casing_variants_into_single_catalog_spelled_row(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)

    response = post_apply(client, csv_bytes("3070B,4,2", "3070b,4,3"))

    assert response.json()["appliedRowCount"] == 1
    assert inventory_rows(catalog_session_factory) == {("3070b", 4): 5}


def test_include_unknown_toggle_controls_persistence_and_listing(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    content = csv_bytes("MYSTERY,4,2", "3001,4,1")

    skipped = post_apply(client, content, include_unknown=False).json()
    assert skipped["appliedRowCount"] == 1
    assert skipped["skippedUnknownRowCount"] == 1
    assert skipped["quantityDelta"] == 1
    assert inventory_rows(catalog_session_factory) == {("3001", 4): 1}

    included = post_apply(client, content, include_unknown=True).json()
    assert included["appliedRowCount"] == 2
    assert included["createdCount"] == 1 and included["updatedCount"] == 1
    assert inventory_rows(catalog_session_factory) == {("3001", 4): 2, ("mystery", 4): 2}

    items = client.get("/api/inventory/items").json()["items"]
    orphan = next(item for item in items if item["partId"] == "mystery")
    assert orphan["catalogAvailable"] is False
    assert orphan["partName"] == "mystery"
    assert orphan["category"] == "Unavailable"


def test_alias_canonicalization_end_to_end(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    root = create_alias_library(tmp_path)
    rebuild_catalog(catalog_session_factory, root)
    client = client_for(catalog_session_factory, tmp_path, library_root=root)
    content = csv_bytes("ALIAS,4,2", "canonical,4,3")

    previewed = post_preview(client, content)
    assert previewed.status_code == 200
    payload = previewed.json()
    assert payload["aliasCanonicalizedCount"] == 1
    assert payload["duplicateRowCount"] == 1
    assert payload["plannedRowCount"] == 1
    assert payload["known"]["rowCount"] == 1
    row = payload["rows"][0]
    assert row["partId"] == "canonical"
    assert row["canonicalizedFrom"] == "ALIAS"
    assert row["quantity"] == 5

    applied = post_apply(client, content)
    assert applied.json()["createdCount"] == 1
    assert inventory_rows(catalog_session_factory) == {("canonical", 4): 5}


def test_upload_over_byte_cap_returns_413(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path, max_upload_bytes=64)
    content = csv_bytes(*(["3001,4,1"] * 20))

    assert post_preview(client, content).status_code == 413
    assert post_apply(client, content).status_code == 413


def test_import_rejects_invalid_uploads(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    valid = csv_bytes("3001,4,1")

    wrong_extension = post_preview(client, valid, filename="inventory.txt")
    assert wrong_extension.status_code == 422
    assert ".csv" in wrong_extension.json()["detail"]
    assert post_apply(client, valid, filename="inventory.txt").status_code == 422

    empty = post_preview(client, b"")
    assert empty.status_code == 422
    assert "empty" in empty.json()["detail"]

    missing_column = post_preview(client, csv_bytes("3001,1", header="part_id,quantity"))
    assert missing_column.status_code == 422
    assert "color_code" in missing_column.json()["detail"]

    not_utf8 = post_preview(client, "part_id,color_code,quantity\n3001,4,1\n".encode("utf-16"))
    assert not_utf8.status_code == 422
    assert "UTF-8" in not_utf8.json()["detail"]

    assert post_preview(client, valid, strategy="merge").status_code == 422

    assert inventory_rows(catalog_session_factory) == {}


def test_import_rejects_files_over_the_row_cap(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)
    content = csv_bytes(*(["3001,4,1"] * 20_001))

    response = post_preview(client, content)

    assert response.status_code == 422
    assert "20000" in response.json()["detail"]
    assert inventory_rows(catalog_session_factory) == {}
