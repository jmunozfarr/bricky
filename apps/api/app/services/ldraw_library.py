from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

DEFAULT_LIBRARY_URL = "https://library.ldraw.org/library/updates/complete.zip"
MANIFEST_VERSION = 1


class LibraryError(Exception):
    """Base error for local LDraw library operations."""


class LibraryInstallError(LibraryError):
    """Raised when an installation cannot be completed safely."""


class UnsafeArchiveError(LibraryInstallError):
    """Raised when a ZIP member could escape or create an unsafe file."""


@dataclass(frozen=True)
class FileCounts:
    dat: int
    ldr: int
    png: int

    def to_dict(self) -> dict[str, int]:
        return {"dat": self.dat, "ldr": self.ldr, "png": self.png}


@dataclass(frozen=True)
class LibraryManifest:
    installed_at: str
    source: str
    archive_sha256: str
    file_counts: FileCounts

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_version": MANIFEST_VERSION,
            "installed_at": self.installed_at,
            "source": self.source,
            "archive_sha256": self.archive_sha256,
            "file_counts": self.file_counts.to_dict(),
        }


@dataclass(frozen=True)
class LibraryStatus:
    installed: bool
    file_counts: FileCounts | None
    archive_sha256: str | None
    manifest: LibraryManifest | None
    problem: str | None = None


def manifest_path_for(library_root: Path) -> Path:
    return library_root.parent / f"{library_root.name}.manifest.json"


def validate_library(library_root: Path) -> tuple[str, ...]:
    problems: list[str] = []
    if not library_root.is_dir():
        return ("library root is missing",)
    if not (library_root / "LDConfig.ldr").is_file():
        problems.append("LDConfig.ldr is missing")
    if not (library_root / "parts").is_dir():
        problems.append("parts directory is missing")
    if not (library_root / "p").is_dir():
        problems.append("p directory is missing")
    return tuple(problems)


def count_library_files(library_root: Path) -> FileCounts:
    counts = {".dat": 0, ".ldr": 0, ".png": 0}
    for path in library_root.rglob("*"):
        if path.is_file():
            suffix = path.suffix.lower()
            if suffix in counts:
                counts[suffix] += 1
    return FileCounts(dat=counts[".dat"], ldr=counts[".ldr"], png=counts[".png"])


def _read_manifest(path: Path) -> LibraryManifest | None:
    if not path.is_file():
        return None

    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None

        installed_at = raw.get("installed_at")
        source = raw.get("source")
        archive_sha256 = raw.get("archive_sha256")
        raw_counts = raw.get("file_counts")
        if (
            not isinstance(installed_at, str)
            or not isinstance(source, str)
            or not isinstance(archive_sha256, str)
            or len(archive_sha256) != 64
            or not isinstance(raw_counts, dict)
        ):
            return None

        dat, ldr, png = (raw_counts.get(key) for key in ("dat", "ldr", "png"))
        if not (isinstance(dat, int) and isinstance(ldr, int) and isinstance(png, int)):
            return None
        if min(dat, ldr, png) < 0:
            return None

        return LibraryManifest(
            installed_at=installed_at,
            source=source,
            archive_sha256=archive_sha256,
            file_counts=FileCounts(dat=dat, ldr=ldr, png=png),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def get_library_status(library_root: Path) -> LibraryStatus:
    if not library_root.exists():
        return LibraryStatus(False, None, None, None)

    problems = validate_library(library_root)
    if problems:
        return LibraryStatus(False, None, None, None, "; ".join(problems))

    manifest_path = manifest_path_for(library_root)
    manifest = _read_manifest(manifest_path)
    if manifest is not None:
        return LibraryStatus(
            True,
            manifest.file_counts,
            manifest.archive_sha256,
            manifest,
        )

    problem = "installation manifest is missing or invalid" if manifest_path.exists() else None
    return LibraryStatus(True, count_library_files(library_root), None, None, problem)


def _copy_and_hash(source: BinaryIO, destination: Path) -> str:
    digest = hashlib.sha256()
    with destination.open("wb") as output:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest()


def _download_archive(url: str, destination: Path) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Bricky LDraw bootstrap"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return _copy_and_hash(response, destination)
    except OSError as error:
        raise LibraryInstallError(f"Unable to download the library archive: {error}") from error


def _copy_local_archive(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise LibraryInstallError(f"Local archive does not exist: {source}")
    with source.open("rb") as input_file:
        return _copy_and_hash(input_file, destination)


def _safe_member_path(member: zipfile.ZipInfo) -> PurePosixPath:
    normalized_name = member.filename.replace("\\", "/")
    path = PurePosixPath(normalized_name)
    if (
        not normalized_name
        or path.is_absolute()
        or ".." in path.parts
        or (path.parts and path.parts[0].endswith(":"))
    ):
        raise UnsafeArchiveError(f"Unsafe ZIP path: {member.filename}")

    unix_mode = member.external_attr >> 16
    file_type = stat.S_IFMT(unix_mode)
    if file_type == stat.S_IFLNK:
        raise UnsafeArchiveError(f"Symbolic links are not allowed: {member.filename}")
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise UnsafeArchiveError(f"Unsupported ZIP member type: {member.filename}")
    return path


def _extract_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    destination_resolved = destination.resolve()
    extracted_paths: set[PurePosixPath] = set()

    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                relative_path = _safe_member_path(member)
                if relative_path in extracted_paths:
                    raise UnsafeArchiveError(f"Duplicate ZIP path: {member.filename}")
                if member.flag_bits & 0x1:
                    raise UnsafeArchiveError(
                        f"Encrypted ZIP members are not allowed: {member.filename}"
                    )
                extracted_paths.add(relative_path)
                target = destination.joinpath(*relative_path.parts)
                if not target.resolve().is_relative_to(destination_resolved):
                    raise UnsafeArchiveError(f"Unsafe ZIP path: {member.filename}")

                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    except zipfile.BadZipFile as error:
        raise LibraryInstallError("The downloaded file is not a valid ZIP archive") from error


def _locate_library_root(extracted_root: Path) -> Path:
    direct_problems = validate_library(extracted_root)
    if not direct_problems:
        return extracted_root

    nested_root = extracted_root / "ldraw"
    nested_problems = validate_library(nested_root)
    if not nested_problems:
        top_level_entries = list(extracted_root.iterdir())
        if top_level_entries == [nested_root]:
            return nested_root
        raise LibraryInstallError("Archive must contain only one top-level ldraw directory")

    details = "; ".join(direct_problems)
    raise LibraryInstallError(f"Archive does not contain a valid LDraw library: {details}")


def _replace_library(candidate: Path, library_root: Path, force: bool) -> None:
    if not library_root.exists():
        candidate.rename(library_root)
        return

    if not force:
        raise LibraryInstallError("An LDraw library already exists; use --force to replace it")

    backup = library_root.parent / f".{library_root.name}.backup-{uuid.uuid4().hex}"
    library_root.rename(backup)
    try:
        candidate.rename(library_root)
    except BaseException:
        backup.rename(library_root)
        raise
    else:
        shutil.rmtree(backup)


def install_library(
    library_root: Path,
    *,
    source_url: str = DEFAULT_LIBRARY_URL,
    archive_path: Path | None = None,
    force: bool = False,
) -> LibraryManifest:
    library_root = library_root.resolve()
    if library_root == Path(library_root.anchor):
        raise LibraryInstallError("The filesystem root cannot be used as a library root")

    existing_status = get_library_status(library_root)
    if library_root.exists() and not force:
        if existing_status.installed:
            raise LibraryInstallError(
                "A valid LDraw library is already installed; use --force to replace it"
            )
        raise LibraryInstallError(
            "The library destination already exists but is invalid; use --force to replace it"
        )

    data_root = library_root.parent
    data_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".ldraw-install-", dir=data_root) as temp_name:
        temp_root = Path(temp_name)
        downloaded_archive = temp_root / "complete.zip"
        if archive_path is None:
            archive_sha256 = _download_archive(source_url, downloaded_archive)
            source_description = source_url
        else:
            archive_sha256 = _copy_local_archive(archive_path, downloaded_archive)
            source_description = f"local archive: {archive_path.name}"

        extracted_root = temp_root / "extracted"
        _extract_archive(downloaded_archive, extracted_root)
        candidate = _locate_library_root(extracted_root)
        file_counts = count_library_files(candidate)
        manifest = LibraryManifest(
            installed_at=datetime.now(UTC).isoformat(),
            source=source_description,
            archive_sha256=archive_sha256,
            file_counts=file_counts,
        )

        temporary_manifest = temp_root / "manifest.json"
        temporary_manifest.write_text(
            json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        _replace_library(candidate, library_root, force)
        os.replace(temporary_manifest, manifest_path_for(library_root))
        return manifest
