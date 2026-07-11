from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.cli.models import reprocess_targets
from app.main import create_app
from app.models import (
    ImportedModel,
    LDrawColor,
    LDrawPrimitive,
    ModelBomItem,
    ModelImportIssue,
    Part,
)
from app.services.model_import import import_model
from app.services.model_reprocess import (
    ModelNotFoundError,
    ModelSourceIntegrityError,
    ModelSourceUnavailableError,
    reprocess_model,
)

IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"


def seed_catalog(factory: sessionmaker[Session], part_ids: list[str]) -> None:
    with factory.begin() as session:
        session.add_all(
            Part(
                part_id=part_id,
                name=f"Part {part_id}",
                relative_path=f"parts/{part_id}.dat",
                category="Brick",
                is_subpart=False,
                is_shortcut=False,
            )
            for part_id in part_ids
        )
        if not session.scalar(select(LDrawColor).where(LDrawColor.code == 4)):
            session.add(LDrawColor(code=4, name="Red", value_hex="#C91A09", alpha=255))


def import_source(
    factory: sessionmaker[Session], storage: Path, content: bytes, filename: str = "demo.ldr"
) -> uuid.UUID:
    outcome = import_model(
        factory,
        storage / "models",
        storage / "library",
        io.BytesIO(content),
        filename,
        None,
    )
    return outcome.public_id


def client_for(factory: sessionmaker[Session], storage: Path) -> TestClient:
    return TestClient(
        create_app(
            library_root=storage / "library",
            session_factory=factory,
            model_storage_root=storage / "models",
            model_max_upload_bytes=1024 * 1024,
        )
    )


def stored_source_path(storage: Path, public_id: uuid.UUID) -> Path:
    directory = storage / "models" / "originals" / str(public_id)
    files = list(directory.iterdir())
    assert len(files) == 1
    return files[0]


def two_part_source() -> bytes:
    return f"0 Model\n1 4 {IDENTITY} 3001.dat\n1 4 {IDENTITY} 3020.dat\n".encode()


def test_reprocess_resolves_new_catalog_parts_and_is_idempotent(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory, ["3001"])
    public_id = import_source(catalog_session_factory, tmp_path, two_part_source())

    unchanged = reprocess_model(
        catalog_session_factory, tmp_path / "models", tmp_path / "library", public_id
    )
    assert unchanged.previous_status == "ready_with_warnings"
    assert unchanged.import_status == "ready_with_warnings"
    assert [(item.part_id, item.quantity) for item in unchanged.parsed.bom] == [("3001", 1)]

    seed_catalog(catalog_session_factory, ["3020"])
    outcome = reprocess_model(
        catalog_session_factory, tmp_path / "models", tmp_path / "library", public_id
    )
    assert outcome.previous_status == "ready_with_warnings"
    assert outcome.import_status == "ready"
    assert [(item.part_id, item.quantity) for item in outcome.parsed.bom] == [
        ("3001", 1),
        ("3020", 1),
    ]

    with catalog_session_factory() as session:
        model = session.scalar(select(ImportedModel).where(ImportedModel.public_id == public_id))
        assert model is not None
        assert model.import_status == "ready"
        assert model.total_part_quantity == 2
        assert model.unique_part_color_count == 2
        assert model.unresolved_reference_count == 0
        bom_rows = session.scalar(
            select(func.count()).select_from(ModelBomItem).where(ModelBomItem.model_id == model.id)
        )
        issue_rows = session.scalar(
            select(func.count())
            .select_from(ModelImportIssue)
            .where(ModelImportIssue.model_id == model.id)
        )
        assert bom_rows == 2
        assert issue_rows == 0


def test_reprocess_uses_indexed_primitives(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory, ["3001"])
    source = f"0 Model\n1 4 {IDENTITY} 3001.dat\n1 16 {IDENTITY} axlehol8.dat\n".encode()
    public_id = import_source(catalog_session_factory, tmp_path, source)
    with catalog_session_factory() as session:
        model = session.scalar(select(ImportedModel).where(ImportedModel.public_id == public_id))
        assert model is not None
        assert model.import_status == "ready_with_warnings"
        assert model.unresolved_reference_count == 1

    with catalog_session_factory.begin() as session:
        session.add(LDrawPrimitive(name="axlehol8.dat"))
    outcome = reprocess_model(
        catalog_session_factory, tmp_path / "models", tmp_path / "library", public_id
    )
    assert outcome.import_status == "ready"
    assert outcome.parsed.issues == ()
    assert [(item.part_id, item.quantity) for item in outcome.parsed.bom] == [("3001", 1)]


def test_reprocess_endpoint_returns_updated_detail(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory, ["3001"])
    client = client_for(catalog_session_factory, tmp_path)
    response = client.post(
        "/api/models",
        files={"file": ("demo.ldr", two_part_source(), "text/plain")},
        data={"name": "Reprocess demo"},
    )
    assert response.status_code == 201
    model_id = response.json()["modelId"]
    assert response.json()["importStatus"] == "ready_with_warnings"

    seed_catalog(catalog_session_factory, ["3020"])
    reprocessed = client.post(f"/api/models/{model_id}/reprocess")
    assert reprocessed.status_code == 200
    payload = reprocessed.json()
    assert payload["importStatus"] == "ready"
    assert payload["issues"] == []
    assert [item["partId"] for item in payload["bom"]] == ["3001", "3020"]
    assert payload["unresolvedReferenceCount"] == 0


def test_reprocess_missing_model_and_source_errors(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory, ["3001"])
    client = client_for(catalog_session_factory, tmp_path)

    with pytest.raises(ModelNotFoundError):
        reprocess_model(
            catalog_session_factory, tmp_path / "models", tmp_path / "library", uuid.uuid4()
        )
    assert client.post(f"/api/models/{uuid.uuid4()}/reprocess").status_code == 404

    public_id = import_source(catalog_session_factory, tmp_path, two_part_source())
    source_path = stored_source_path(tmp_path, public_id)
    original_bytes = source_path.read_bytes()

    # The API refuses to derive anything from bytes that no longer match the
    # recorded checksum; the synthetic original is corrupted only to test that.
    source_path.write_bytes(original_bytes + b"\n0 Tampered\n")
    with pytest.raises(ModelSourceIntegrityError):
        reprocess_model(
            catalog_session_factory, tmp_path / "models", tmp_path / "library", public_id
        )
    assert client.post(f"/api/models/{public_id}/reprocess").status_code == 409

    source_path.unlink()
    with pytest.raises(ModelSourceUnavailableError):
        reprocess_model(
            catalog_session_factory, tmp_path / "models", tmp_path / "library", public_id
        )
    assert client.post(f"/api/models/{public_id}/reprocess").status_code == 404


def flex_path_source() -> bytes:
    return "\n".join(
        [
            "0 FILE main.ldr",
            f"1 4 {IDENTITY} flexAxle.ldr",
            f"1 4 {IDENTITY} 3001.dat",
            "0 FILE flexAxle.ldr",
            "0 !LDCAD PATH_POINT [posOri=1]",
            "2 24 0 0 0 1 1 1",
        ]
    ).encode()


def test_resolution_endpoints_map_ignore_and_delete(
    catalog_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    seed_catalog(catalog_session_factory, ["3001", "3020"])
    client = client_for(catalog_session_factory, tmp_path)
    response = client.post(
        "/api/models",
        files={"file": ("flex.mpd", flex_path_source(), "text/plain")},
        data={"name": "Flex demo"},
    )
    assert response.status_code == 201
    model_id = response.json()["modelId"]
    assert response.json()["importStatus"] == "ready_with_warnings"

    detail = client.get(f"/api/models/{model_id}").json()
    assert [issue["code"] for issue in detail["issues"]] == ["generated_section_without_parts"]

    resolutions_url = f"/api/models/{model_id}/resolutions"
    invalid_part = client.put(
        resolutions_url,
        json={"sourceReference": "flexAxle.ldr", "action": "map", "partId": "nope"},
    )
    assert invalid_part.status_code == 422
    invalid_color = client.put(
        resolutions_url,
        json={
            "sourceReference": "flexAxle.ldr",
            "action": "map",
            "partId": "3020",
            "colorCode": 999,
        },
    )
    assert invalid_color.status_code == 422
    missing_part = client.put(
        resolutions_url, json={"sourceReference": "flexAxle.ldr", "action": "map"}
    )
    assert missing_part.status_code == 422

    mapped = client.put(
        resolutions_url,
        json={"sourceReference": "flexAxle.ldr", "action": "map", "partId": "3020"},
    )
    assert mapped.status_code == 200
    payload = mapped.json()
    assert payload["importStatus"] == "ready"
    assert [item["partId"] for item in payload["bom"]] == ["3001", "3020"]
    assert payload["resolutions"] == [
        {
            "sourceReference": "flexaxle.ldr",
            "action": "map",
            "partId": "3020",
            "colorCode": None,
        }
    ]
    assert [issue["code"] for issue in payload["issues"]] == ["reference_manually_mapped"]

    ignored = client.put(
        resolutions_url, json={"sourceReference": "FLEXAXLE.LDR", "action": "ignore"}
    )
    assert ignored.status_code == 200
    assert ignored.json()["importStatus"] == "ready"
    assert [item["partId"] for item in ignored.json()["bom"]] == ["3001"]
    assert ignored.json()["resolutions"][0]["action"] == "ignore"

    removed = client.delete(resolutions_url, params={"source": "flexaxle.ldr"})
    assert removed.status_code == 200
    assert removed.json()["importStatus"] == "ready_with_warnings"
    assert removed.json()["resolutions"] == []

    repeat = client.delete(resolutions_url, params={"source": "flexaxle.ldr"})
    assert repeat.status_code == 200
    assert repeat.json()["importStatus"] == "ready_with_warnings"


def test_cli_reprocess_targets_reports_transitions_and_failures(
    catalog_session_factory: sessionmaker[Session],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_catalog(catalog_session_factory, ["3001"])
    first = import_source(catalog_session_factory, tmp_path, two_part_source(), "first.ldr")
    second = import_source(
        catalog_session_factory,
        tmp_path,
        f"0 Model\n1 4 {IDENTITY} 3001.dat\n".encode(),
        "second.ldr",
    )

    seed_catalog(catalog_session_factory, ["3020"])
    exit_code = reprocess_targets(
        catalog_session_factory, tmp_path / "models", tmp_path / "library"
    )
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "ready_with_warnings -> ready" in output
    assert "Reprocessed 2 of 2 models" in output

    stored_source_path(tmp_path, second).unlink()
    exit_code = reprocess_targets(
        catalog_session_factory,
        tmp_path / "models",
        tmp_path / "library",
        [first, second],
    )
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAILED" in output
    assert "Reprocessed 1 of 2 models" in output
