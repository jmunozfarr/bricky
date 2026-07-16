from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from test_inventory_import_api import (
    client_for,
    csv_bytes,
    post_preview,
    seed_catalog,
    seed_mapping,
)

from app.models import RebrickableSet, RebrickableSetDataState, RebrickableSetPart


def seed_set_data(factory: sessionmaker[Session]) -> None:
    """A tiny set (7922-1) whose two parts match seed_mapping's rebrickable
    entries (3001 red, 3070b blue) -- lets set-import tests cross-check
    against the equivalent Rebrickable CSV path."""
    with factory.begin() as session:
        session.add(
            RebrickableSet(
                set_num="7922-1", name="Yoda's Starfighter", num_parts=5, chosen_version=1
            )
        )
        session.add_all(
            [
                RebrickableSetPart(
                    set_num="7922-1", part_num="3001", color_id=0, quantity=3, is_spare=False
                ),
                RebrickableSetPart(
                    set_num="7922-1", part_num="3070b", color_id=7, quantity=2, is_spare=False
                ),
            ]
        )
        session.add(
            RebrickableSetDataState(
                id=1,
                populated_at=datetime.now(UTC),
                set_count=1,
                part_row_count=2,
                fetcher_version="test",
            )
        )


def post_set_preview(client: TestClient, set_num: str, strategy: str = "add") -> httpx.Response:
    return client.post(
        "/api/inventory/import/set/preview",
        json={"setNum": set_num, "strategy": strategy},
    )


def post_set_apply(
    client: TestClient, set_num: str, strategy: str = "add", include_unknown: bool = True
) -> httpx.Response:
    return client.post(
        "/api/inventory/import/set/apply",
        json={"setNum": set_num, "strategy": strategy, "includeUnknown": include_unknown},
    )


def test_preview_returns_set_metadata_and_expanded_rows(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    seed_mapping(catalog_session_factory)
    seed_set_data(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)

    response = post_set_preview(client, "7922-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "set"
    assert payload["setNum"] == "7922-1"
    assert payload["setName"] == "Yoda's Starfighter"
    assert payload["officialPartCount"] == 5
    assert payload["expandedQuantity"] == 5
    by_key = {(row["partId"], row["colorCode"]): row for row in payload["rows"]}
    assert by_key[("3001", 4)]["quantity"] == 3
    assert by_key[("3070b", 1)]["quantity"] == 2
    assert by_key[("3001", 4)]["unknownReason"] is None
    assert by_key[("3070b", 1)]["unknownReason"] is None


def test_preview_falls_back_to_dash_one_suffix(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    seed_mapping(catalog_session_factory)
    seed_set_data(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)

    response = post_set_preview(client, "7922")

    assert response.status_code == 200
    assert response.json()["setNum"] == "7922-1"


def test_preview_unknown_set_is_404_when_data_populated(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    seed_set_data(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)

    response = post_set_preview(client, "99999-1")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_preview_reports_data_not_populated(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)

    response = post_set_preview(client, "7922-1")

    assert response.status_code == 404
    assert "populate-sets" in response.json()["detail"]


def test_apply_persists_translated_rows_and_reports_set_metadata(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    seed_catalog(catalog_session_factory)
    seed_mapping(catalog_session_factory)
    seed_set_data(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)

    response = post_set_apply(client, "7922-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "set"
    assert payload["setNum"] == "7922-1"
    assert payload["setName"] == "Yoda's Starfighter"
    assert payload["appliedRowCount"] == 2

    inventory = client.get("/api/inventory/items?pageSize=100").json()["items"]
    by_part = {(item["partId"], item["colorCode"]): item["quantity"] for item in inventory}
    assert by_part[("3001", 4)] == 3
    assert by_part[("3070b", 1)] == 2


def test_set_preview_matches_equivalent_rebrickable_csv_upload(
    tmp_path: Path, catalog_session_factory: sessionmaker[Session]
) -> None:
    """Cross-validation, mirroring Phase B's fixture technique: expanding a
    set through the new path must converge with uploading a hand-built
    Rebrickable CSV of the same rows through the existing path."""
    seed_catalog(catalog_session_factory)
    seed_mapping(catalog_session_factory)
    seed_set_data(catalog_session_factory)
    client = client_for(catalog_session_factory, tmp_path)

    set_result = post_set_preview(client, "7922-1").json()
    csv_result = post_preview(
        client,
        csv_bytes("3001,0,3,False", "3070b,7,2,False", header="Part,Color,Quantity,Is Spare"),
    ).json()

    def known_totals(payload: dict[str, Any]) -> set[tuple[str, int, int]]:
        return {(row["partId"], row["colorCode"], row["quantity"]) for row in payload["rows"]}

    assert known_totals(set_result) == known_totals(csv_result) == {("3001", 4, 3), ("3070b", 1, 2)}
