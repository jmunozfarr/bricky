from __future__ import annotations

import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.cli.backup import (
    ARCHIVE_ROOT,
    BackupError,
    create_backup,
    prepare_restore,
    replace_models,
    validate_backup,
)


def create_valid_backup(tmp_path: Path) -> Path:
    database_dump = tmp_path / "database.dump"
    database_dump.write_bytes(b"PGDMP\x01synthetic database payload")
    models = tmp_path / "models"
    source = models / "originals" / "model-id" / "source.ldr"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"0 Immutable model\r\n")
    archive = tmp_path / "backup.tar.gz"
    create_backup(
        database_dump,
        models,
        archive,
        created_at=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
    )
    return archive


def test_backup_manifest_checksums_and_payload_scope(tmp_path: Path) -> None:
    archive = create_valid_backup(tmp_path)

    validation = validate_backup(archive)

    assert validation.created_at == "2026-06-29T12:00:00Z"
    assert validation.payload_count == 2
    assert validation.model_file_count == 1
    with tarfile.open(archive, "r:gz") as package:
        names = set(package.getnames())
    assert f"{ARCHIVE_ROOT}/database.dump" in names
    assert f"{ARCHIVE_ROOT}/models/originals/model-id/source.ldr" in names
    assert all(".env" not in name and "ldraw" not in name for name in names)


def test_restore_requires_force_and_replaces_model_files(tmp_path: Path) -> None:
    archive = create_valid_backup(tmp_path)
    prepared = tmp_path / "prepared"
    with pytest.raises(BackupError, match="force"):
        prepare_restore(archive, prepared, force=False)

    prepare_restore(archive, prepared, force=True)
    destination = tmp_path / "live-models"
    stale = destination / "originals" / "old" / "stale.ldr"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")

    restored = replace_models(
        prepared / ARCHIVE_ROOT / "models",
        destination,
    )

    assert restored == 1
    assert not stale.exists()
    assert (
        destination / "originals" / "model-id" / "source.ldr"
    ).read_bytes() == b"0 Immutable model\r\n"


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    original = create_valid_backup(tmp_path)
    extracted = tmp_path / "extracted"
    with tarfile.open(original, "r:gz") as package:
        package.extractall(extracted, filter="data")
    (extracted / ARCHIVE_ROOT / "database.dump").write_bytes(b"PGDMPtampered")
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(tampered, "w:gz") as package:
        package.add(extracted / ARCHIVE_ROOT, arcname=ARCHIVE_ROOT)

    with pytest.raises(BackupError, match="checksum"):
        validate_backup(tampered)


def test_invalid_format_and_unsafe_archive_path_are_rejected(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.tar.gz"
    manifest = json.dumps({"format": "something-else", "version": 1}).encode()
    with tarfile.open(invalid, "w:gz") as package:
        member = tarfile.TarInfo(f"{ARCHIVE_ROOT}/manifest.json")
        member.size = len(manifest)
        package.addfile(member, io.BytesIO(manifest))
    with pytest.raises(BackupError, match="recognized"):
        validate_backup(invalid)

    unsafe = tmp_path / "unsafe.tar.gz"
    with tarfile.open(unsafe, "w:gz") as package:
        member = tarfile.TarInfo(f"{ARCHIVE_ROOT}/../escape")
        member.size = 1
        package.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(BackupError, match="unsafe"):
        validate_backup(unsafe)
