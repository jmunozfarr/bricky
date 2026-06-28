from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.ldraw_library import (
    LibraryInstallError,
    UnsafeArchiveError,
    get_library_status,
    install_library,
    manifest_path_for,
)


def create_library_archive(
    archive_path: Path,
    *,
    nested: bool = False,
    include_config: bool = True,
    include_parts: bool = True,
) -> Path:
    prefix = "ldraw/" if nested else ""
    with zipfile.ZipFile(archive_path, "w") as archive:
        if include_config:
            archive.writestr(f"{prefix}LDConfig.ldr", "0 LDraw color configuration\n")
        if include_parts:
            archive.writestr(f"{prefix}parts/3001.dat", "0 Brick 2 x 4\n")
        archive.writestr(f"{prefix}p/box.dat", "0 Box primitive\n")
        archive.writestr(f"{prefix}models/example.ldr", "0 Example model\n")
        archive.writestr(f"{prefix}textures/sample.png", b"synthetic png")
        archive.writestr(f"{prefix}README.txt", "Synthetic test library\n")
    return archive_path


def test_installs_valid_direct_root_archive(tmp_path: Path) -> None:
    archive = create_library_archive(tmp_path / "direct.zip")
    library_root = tmp_path / "data" / "official"

    manifest = install_library(library_root, archive_path=archive)

    assert (library_root / "LDConfig.ldr").is_file()
    assert (library_root / "parts" / "3001.dat").is_file()
    assert (library_root / "README.txt").read_text() == "Synthetic test library\n"
    assert manifest.file_counts.to_dict() == {"dat": 2, "ldr": 2, "png": 1}
    assert len(manifest.archive_sha256) == 64


def test_installs_archive_with_top_level_ldraw_directory(tmp_path: Path) -> None:
    archive = create_library_archive(tmp_path / "nested.zip", nested=True)
    library_root = tmp_path / "data" / "official"

    install_library(library_root, archive_path=archive)

    assert (library_root / "p" / "box.dat").is_file()
    assert not (library_root / "ldraw").exists()


def test_rejects_archive_without_ldconfig(tmp_path: Path) -> None:
    archive = create_library_archive(tmp_path / "missing-config.zip", include_config=False)

    with pytest.raises(LibraryInstallError, match="LDConfig.ldr is missing"):
        install_library(tmp_path / "official", archive_path=archive)


def test_rejects_archive_without_parts_directory(tmp_path: Path) -> None:
    archive = create_library_archive(tmp_path / "missing-parts.zip", include_parts=False)

    with pytest.raises(LibraryInstallError, match="parts directory is missing"):
        install_library(tmp_path / "official", archive_path=archive)


def test_rejects_zip_path_traversal(tmp_path: Path) -> None:
    archive = create_library_archive(tmp_path / "traversal.zip")
    with zipfile.ZipFile(archive, "a") as zip_file:
        zip_file.writestr("../escaped.txt", "unsafe")

    with pytest.raises(UnsafeArchiveError, match="Unsafe ZIP path"):
        install_library(tmp_path / "data" / "official", archive_path=archive)

    assert not (tmp_path / "data" / "escaped.txt").exists()


def test_rejects_symbolic_link_member(tmp_path: Path) -> None:
    archive = create_library_archive(tmp_path / "symlink.zip")
    link = zipfile.ZipInfo("parts/link.dat")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "a") as zip_file:
        zip_file.writestr(link, "../outside.dat")

    with pytest.raises(UnsafeArchiveError, match="Symbolic links are not allowed"):
        install_library(tmp_path / "official", archive_path=archive)


def test_refuses_existing_installation_without_force(tmp_path: Path) -> None:
    archive = create_library_archive(tmp_path / "library.zip")
    library_root = tmp_path / "official"
    install_library(library_root, archive_path=archive)

    with pytest.raises(LibraryInstallError, match="already installed"):
        install_library(library_root, archive_path=archive)


def test_status_when_library_is_not_installed(tmp_path: Path) -> None:
    status = get_library_status(tmp_path / "official")

    assert status.installed is False
    assert status.file_counts is None
    assert status.archive_sha256 is None
    assert status.problem is None


def test_status_reads_a_valid_manifest(tmp_path: Path) -> None:
    archive = create_library_archive(tmp_path / "library.zip")
    library_root = tmp_path / "official"
    installed_manifest = install_library(library_root, archive_path=archive)

    status = get_library_status(library_root)

    assert manifest_path_for(library_root).is_file()
    assert status.installed is True
    assert status.manifest == installed_manifest
    assert status.file_counts == installed_manifest.file_counts
    assert status.archive_sha256 == installed_manifest.archive_sha256


def test_api_library_status_when_not_installed(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "official"))

    response = client.get("/api/library/status")
    static_response = client.get("/api/ldraw/LDConfig.ldr")

    assert response.status_code == 200
    assert response.json() == {
        "installed": False,
        "fileCounts": None,
        "archiveSha256": None,
    }
    assert static_response.status_code == 404


def test_api_status_and_static_files_for_installed_library(tmp_path: Path) -> None:
    archive = create_library_archive(tmp_path / "library.zip")
    library_root = tmp_path / "official"
    manifest = install_library(library_root, archive_path=archive)
    client = TestClient(create_app(library_root))

    status_response = client.get("/api/library/status")
    part_response = client.get("/api/ldraw/parts/3001.dat")
    missing_response = client.get("/api/ldraw/parts/missing.dat")

    assert status_response.status_code == 200
    assert status_response.json() == {
        "installed": True,
        "fileCounts": {"dat": 2, "ldr": 2, "png": 1},
        "archiveSha256": manifest.archive_sha256,
    }
    assert part_response.status_code == 200
    assert part_response.text == "0 Brick 2 x 4\n"
    assert missing_response.status_code == 404
