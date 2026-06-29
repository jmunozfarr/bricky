from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO


BACKUP_FORMAT = "bricky-backup"
BACKUP_VERSION = 1
ARCHIVE_ROOT = "bricky-backup"
DATABASE_PATH = "database.dump"
MODELS_PATH = "models"
MANIFEST_PATH = "manifest.json"
MAX_MANIFEST_BYTES = 1024 * 1024


class BackupError(Exception):
    """Safe operational error for backup and restore commands."""


@dataclass(frozen=True)
class BackupValidation:
    created_at: str
    payload_count: int
    model_file_count: int
    database_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_stream(source: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _copy_models(source: Path, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return []
    if not source.is_dir() or source.is_symlink():
        raise BackupError("Model storage is not a safe directory")
    copied: list[Path] = []
    for entry in sorted(source.rglob("*")):
        if entry.is_symlink():
            raise BackupError(f"Model storage contains a symbolic link: {entry.name}")
        relative = entry.relative_to(source)
        target = destination / relative
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif entry.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, target)
            copied.append(target)
        else:
            raise BackupError(f"Model storage contains an unsupported entry: {entry.name}")
    return copied


def create_backup(
    database_dump: Path,
    models_root: Path,
    output_archive: Path,
    *,
    created_at: datetime | None = None,
) -> BackupValidation:
    if output_archive.exists():
        raise BackupError("Backup output already exists")
    if not database_dump.is_file() or database_dump.stat().st_size == 0:
        raise BackupError("PostgreSQL dump is missing or empty")
    with database_dump.open("rb") as source:
        if source.read(5) != b"PGDMP":
            raise BackupError("Database payload is not a PostgreSQL custom-format dump")

    output_archive.parent.mkdir(parents=True, exist_ok=True)
    package_directory = Path(
        tempfile.mkdtemp(prefix=".backup-package-", dir=output_archive.parent)
    )
    temporary_archive = output_archive.with_name(
        f".{output_archive.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        archive_root = package_directory / ARCHIVE_ROOT
        archive_root.mkdir()
        packaged_dump = archive_root / DATABASE_PATH
        shutil.copy2(database_dump, packaged_dump)
        copied_models = _copy_models(models_root, archive_root / MODELS_PATH)

        payload_paths = [packaged_dump, *copied_models]
        payloads: dict[str, dict[str, object]] = {}
        for payload in sorted(payload_paths):
            relative = payload.relative_to(archive_root).as_posix()
            payloads[relative] = {
                "sha256": sha256_file(payload),
                "size": payload.stat().st_size,
            }

        timestamp = (created_at or datetime.now(UTC)).astimezone(UTC)
        manifest = {
            "format": BACKUP_FORMAT,
            "version": BACKUP_VERSION,
            "createdAt": timestamp.isoformat().replace("+00:00", "Z"),
            "databaseFormat": "postgresql-custom",
            "modelFileCount": len(copied_models),
            "ldrawIncluded": False,
            "payloads": payloads,
        }
        (archive_root / MANIFEST_PATH).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        with tarfile.open(temporary_archive, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
            archive.add(archive_root, arcname=ARCHIVE_ROOT, recursive=True)
        os.chmod(temporary_archive, 0o600)
        os.replace(temporary_archive, output_archive)
        return BackupValidation(
            created_at=manifest["createdAt"],
            payload_count=len(payloads),
            model_file_count=len(copied_models),
            database_sha256=str(payloads[DATABASE_PATH]["sha256"]),
        )
    finally:
        shutil.rmtree(package_directory, ignore_errors=True)
        temporary_archive.unlink(missing_ok=True)


def _safe_archive_members(
    archive: tarfile.TarFile,
) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] != ARCHIVE_ROOT
            or member.issym()
            or member.islnk()
            or not (member.isfile() or member.isdir())
        ):
            raise BackupError("Backup archive contains an unsafe entry")
        normalized = path.as_posix()
        if normalized in members:
            raise BackupError("Backup archive contains duplicate entries")
        members[normalized] = member
    return members


def _load_manifest(
    archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo]
) -> dict[str, object]:
    manifest_name = f"{ARCHIVE_ROOT}/{MANIFEST_PATH}"
    member = members.get(manifest_name)
    if member is None or not member.isfile() or member.size > MAX_MANIFEST_BYTES:
        raise BackupError("Backup manifest is missing or invalid")
    source = archive.extractfile(member)
    if source is None:
        raise BackupError("Backup manifest cannot be read")
    try:
        manifest: object = json.load(source)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BackupError("Backup manifest is not valid JSON") from error
    if not isinstance(manifest, dict):
        raise BackupError("Backup manifest has an invalid structure")
    return manifest


def _validated_manifest(
    manifest: dict[str, object], members: dict[str, tarfile.TarInfo]
) -> tuple[str, dict[str, dict[str, object]], int]:
    if manifest.get("format") != BACKUP_FORMAT or manifest.get("version") != BACKUP_VERSION:
        raise BackupError("Archive is not a recognized Bricky backup format")
    if manifest.get("databaseFormat") != "postgresql-custom":
        raise BackupError("Backup database format is unsupported")
    if manifest.get("ldrawIncluded") is not False:
        raise BackupError("Backup has an invalid LDraw inclusion marker")
    created_at = manifest.get("createdAt")
    if not isinstance(created_at, str):
        raise BackupError("Backup creation time is missing")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise BackupError("Backup creation time is invalid") from error
    model_file_count = manifest.get("modelFileCount")
    if not isinstance(model_file_count, int) or model_file_count < 0:
        raise BackupError("Backup model file count is invalid")
    raw_payloads = manifest.get("payloads")
    if not isinstance(raw_payloads, dict) or DATABASE_PATH not in raw_payloads:
        raise BackupError("Backup payload list is invalid")

    payloads: dict[str, dict[str, object]] = {}
    for raw_path, raw_metadata in raw_payloads.items():
        if not isinstance(raw_path, str) or not isinstance(raw_metadata, dict):
            raise BackupError("Backup payload metadata is invalid")
        path = PurePosixPath(raw_path)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise BackupError("Backup payload path is unsafe")
        digest = raw_metadata.get("sha256")
        size = raw_metadata.get("size")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(size, int)
            or size < 0
        ):
            raise BackupError("Backup payload checksum metadata is invalid")
        archive_name = f"{ARCHIVE_ROOT}/{path.as_posix()}"
        member = members.get(archive_name)
        if member is None or not member.isfile():
            raise BackupError(f"Backup payload is missing: {raw_path}")
        payloads[path.as_posix()] = {"sha256": digest, "size": size}

    archived_files = {
        name.removeprefix(f"{ARCHIVE_ROOT}/")
        for name, member in members.items()
        if member.isfile() and name != f"{ARCHIVE_ROOT}/{MANIFEST_PATH}"
    }
    if archived_files != set(payloads):
        raise BackupError("Backup contains unlisted payload files")
    actual_model_files = sum(path.startswith(f"{MODELS_PATH}/") for path in payloads)
    if actual_model_files != model_file_count:
        raise BackupError("Backup model file count does not match its payloads")
    return created_at, payloads, model_file_count


def validate_backup(archive_path: Path) -> BackupValidation:
    if not archive_path.is_file():
        raise BackupError("Backup archive does not exist")
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = _safe_archive_members(archive)
            manifest = _load_manifest(archive, members)
            created_at, payloads, model_file_count = _validated_manifest(
                manifest, members
            )
            for path, expected in payloads.items():
                member = members[f"{ARCHIVE_ROOT}/{path}"]
                source = archive.extractfile(member)
                if source is None:
                    raise BackupError(f"Backup payload cannot be read: {path}")
                digest, size = _sha256_stream(source)
                if digest != expected["sha256"] or size != expected["size"]:
                    raise BackupError(f"Backup payload checksum failed: {path}")
            database_digest = str(payloads[DATABASE_PATH]["sha256"])
    except (tarfile.TarError, OSError) as error:
        raise BackupError("Backup archive cannot be read") from error
    return BackupValidation(
        created_at=created_at,
        payload_count=len(payloads),
        model_file_count=model_file_count,
        database_sha256=database_digest,
    )


def prepare_restore(
    archive_path: Path, destination: Path, *, force: bool
) -> BackupValidation:
    if not force:
        raise BackupError("Restore preparation requires explicit force confirmation")
    if destination.exists():
        raise BackupError("Restore destination already exists")
    validation = validate_backup(archive_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.mkdir(mode=0o700)
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = _safe_archive_members(archive)
            for name, member in sorted(members.items()):
                target = temporary / Path(*PurePosixPath(name).parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise BackupError(f"Backup entry cannot be extracted: {name}")
                with target.open("xb") as output:
                    shutil.copyfileobj(source, output)
        os.replace(temporary, destination)
        return validation
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def replace_models(source: Path, destination: Path) -> int:
    if not source.is_dir() or source.is_symlink():
        raise BackupError("Prepared model payload is unavailable")
    destination.mkdir(parents=True, exist_ok=True)
    incoming = destination / f".restore-incoming-{uuid.uuid4().hex}"
    rollback = destination / f".restore-rollback-{uuid.uuid4().hex}"
    try:
        restored_files = _copy_models(source, incoming)
        rollback.mkdir()
    except BaseException:
        shutil.rmtree(incoming, ignore_errors=True)
        shutil.rmtree(rollback, ignore_errors=True)
        raise
    try:
        for entry in list(destination.iterdir()):
            if entry not in {incoming, rollback}:
                os.replace(entry, rollback / entry.name)
        for entry in list(incoming.iterdir()):
            os.replace(entry, destination / entry.name)
        incoming.rmdir()
        shutil.rmtree(rollback)
        return len(restored_files)
    except BaseException:
        for entry in list(destination.iterdir()):
            if entry not in {incoming, rollback}:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
        for entry in list(rollback.iterdir()):
            os.replace(entry, destination / entry.name)
        shutil.rmtree(incoming, ignore_errors=True)
        shutil.rmtree(rollback, ignore_errors=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and validate Bricky backups")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--dump", type=Path, required=True)
    create.add_argument("--models-root", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("archive", type=Path)

    prepare = subparsers.add_parser("prepare-restore")
    prepare.add_argument("archive", type=Path)
    prepare.add_argument("--destination", type=Path, required=True)
    prepare.add_argument("--force", action="store_true")

    models = subparsers.add_parser("replace-models")
    models.add_argument("--source", type=Path, required=True)
    models.add_argument("--destination", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "create":
            result = create_backup(args.dump, args.models_root, args.output)
        elif args.command == "validate":
            result = validate_backup(args.archive)
        elif args.command == "prepare-restore":
            result = prepare_restore(
                args.archive, args.destination, force=args.force
            )
        else:
            count = replace_models(args.source, args.destination)
            print(f"Restored model files: {count}")
            return 0
        print(json.dumps(result.__dict__, sort_keys=True))
        return 0
    except (BackupError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
