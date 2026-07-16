from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from test_model_coverage_api import client_for, seed_catalog, seed_model

from app.models import ExternalColorMap, ExternalPartIdMap, InventoryItem
from app.services.inventory_import import parse_inventory_csv
from app.services.inventory_import_formats import parse_bricklink_xml
from app.services.local_workspace import resolve_local_workspace


def seed_mapping(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        session.add_all(
            [
                ExternalPartIdMap(
                    source_system="bricklink",
                    source_part_id="bl3001",
                    ldraw_part_id="3001",
                    is_preferred=True,
                ),
                ExternalColorMap(source_system="bricklink", source_color_id=11, ldraw_color_code=4),
            ]
        )


def test_csv_export_lists_only_missing_rows_and_round_trips(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    model_id = seed_model(
        catalog_session_factory,
        [("3001", 4, 4), ("3001", 1, 3), ("3002", 4, 2)],
    )
    with catalog_session_factory.begin() as session:
        workspace = resolve_local_workspace(session)
        session.add(
            InventoryItem(workspace_id=workspace.id, part_id="3001", color_code=4, quantity=4)
        )
    client = client_for(catalog_session_factory, tmp_path)

    response = client.get(f"/api/models/{model_id}/missing-parts")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in response.headers["content-disposition"]
    assert "missing-parts.csv" in response.headers["content-disposition"]
    parsed = parse_inventory_csv(response.content)
    assert parsed.issues == ()
    # 3001/4 is fully covered (owned 4, required 4) -- excluded.
    assert [(row.part_id, row.color_code, row.quantity) for row in parsed.rows] == [
        ("3001", 1, 3),
        ("3002", 4, 2),
    ]


def test_csv_export_is_header_only_when_fully_buildable(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    model_id = seed_model(catalog_session_factory, [])
    client = client_for(catalog_session_factory, tmp_path)

    response = client.get(f"/api/models/{model_id}/missing-parts?format=csv")

    assert response.status_code == 200
    assert response.text == "part_id,color_code,quantity,part_name,color_name\n"


def test_unknown_model_is_404(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    client = client_for(catalog_session_factory, tmp_path)
    assert client.get(f"/api/models/{uuid.uuid4()}/missing-parts").status_code == 404


def test_invalid_format_is_422(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    model_id = seed_model(catalog_session_factory, [("3001", 4, 1)])
    client = client_for(catalog_session_factory, tmp_path)
    assert client.get(f"/api/models/{model_id}/missing-parts?format=json").status_code == 422


def test_bricklink_xml_export_maps_and_round_trips(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    seed_mapping(catalog_session_factory)
    model_id = seed_model(catalog_session_factory, [("3001", 4, 5)])
    client = client_for(catalog_session_factory, tmp_path)

    response = client.get(f"/api/models/{model_id}/missing-parts?format=bricklink-xml")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml; charset=utf-8"
    assert "missing-parts.xml" in response.headers["content-disposition"]
    assert response.headers["x-missing-parts-skipped"] == "0"
    assert response.headers["x-missing-parts-total"] == "1"
    parsed = parse_bricklink_xml(response.content)
    assert parsed.issues == ()
    assert [(row.source_part_id, row.source_color_id, row.quantity) for row in parsed.rows] == [
        ("bl3001", 11, 5)
    ]


def test_bricklink_xml_export_skips_unmapped_rows_and_reports_count(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    seed_mapping(catalog_session_factory)
    # 3002 has no mapping-table entry at all.
    model_id = seed_model(catalog_session_factory, [("3001", 4, 5), ("3002", 4, 2)])
    client = client_for(catalog_session_factory, tmp_path)

    response = client.get(f"/api/models/{model_id}/missing-parts?format=bricklink-xml")

    assert response.status_code == 200
    assert response.headers["x-missing-parts-skipped"] == "1"
    assert response.headers["x-missing-parts-total"] == "2"
    parsed = parse_bricklink_xml(response.content)
    assert [row.source_part_id for row in parsed.rows] == ["bl3001"]


def test_bricklink_xml_export_is_empty_root_when_mapping_table_is_empty(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory)
    model_id = seed_model(catalog_session_factory, [("3001", 4, 1)])
    client = client_for(catalog_session_factory, tmp_path)

    response = client.get(f"/api/models/{model_id}/missing-parts?format=bricklink-xml")

    assert response.status_code == 200
    assert response.headers["x-missing-parts-skipped"] == "1"
    assert response.headers["x-missing-parts-total"] == "1"
    parsed = parse_bricklink_xml(response.content)
    assert parsed.rows == ()
