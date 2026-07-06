from pathlib import Path

import pytest

from app.services.ldraw_pack import LDrawPackLimitError, pack_ldraw_source

IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_packed_source_embeds_colors_and_recursive_library_dependencies(
    tmp_path: Path,
) -> None:
    library = tmp_path / "library"
    write(
        library / "LDConfig.ldr",
        "0 !COLOUR Red CODE 4 VALUE #C91A09 EDGE #333333\n",
    )
    write(
        library / "parts" / "3001.dat",
        f"0 Brick\n0 !LDRAW_ORG Part\n1 16 {IDENTITY} stud.dat\n",
    )
    write(
        library / "p" / "stud.dat",
        "0 Stud\n0 !LDRAW_ORG Primitive\n3 16 0 0 0 1 0 0 0 1 0\n",
    )
    source = f"0 Model\n1 4 {IDENTITY} 3001.dat\n".encode()

    packed = pack_ldraw_source(source, library)
    text = packed.content.decode()

    assert packed.file_count == 2
    assert "0 !COLOUR Red CODE 4" in text
    assert f"1 4 {IDENTITY} parts/3001.dat" in text
    assert f"1 16 {IDENTITY} p/stud.dat" in text
    assert "0 FILE parts/3001.dat" in text
    assert "0 FILE p/stud.dat" in text
    assert source == f"0 Model\n1 4 {IDENTITY} 3001.dat\n".encode()


def test_packed_source_enforces_dependency_limit(tmp_path: Path) -> None:
    library = tmp_path / "library"
    write(library / "parts" / "3001.dat", "0 !LDRAW_ORG Part\n")
    source = f"0 Model\n1 4 {IDENTITY} 3001.dat\n".encode()

    with pytest.raises(LDrawPackLimitError):
        pack_ldraw_source(source, library, maximum_files=0)


def test_library_index_is_scanned_once_per_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.ldraw_pack as ldraw_pack

    library = tmp_path / "library"
    write(library / "LDConfig.ldr", "0 !COLOUR Red CODE 4 VALUE #C91A09 EDGE #333333\n")
    write(library / "parts" / "3001.dat", "0 Brick\n0 !LDRAW_ORG Part\n3 16 0 0 0 1 0 0 0 1 0\n")
    source = f"0 Model\n1 4 {IDENTITY} 3001.dat\n".encode()

    ldraw_pack.clear_library_index()
    scans = 0
    original_scan = ldraw_pack._scan_library

    def counting_scan(root: Path) -> dict[str, Path]:
        nonlocal scans
        scans += 1
        return original_scan(root)

    monkeypatch.setattr(ldraw_pack, "_scan_library", counting_scan)
    try:
        first = pack_ldraw_source(source, library)
        second = pack_ldraw_source(source, library)
    finally:
        ldraw_pack.clear_library_index()

    assert first.content == second.content
    assert scans == 1
