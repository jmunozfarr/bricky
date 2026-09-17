"""A synthetic indexed LDraw catalog, reusable by any test that needs one.

Follows the pattern of `create_synthetic_library` in `test_catalog.py`: write
`parts/*.dat` with real headers, a `p/` primitive, an `LDConfig.ldr`, and a
manifest carrying an `archive_sha256` fingerprint, then let `rebuild_catalog`
index it. Extracted here because more than one suite needs an *indexed*
catalog, not just a library on disk: `conftest.py` hands every test a
throwaway schema whose `parts` table is empty, so an indexed catalog has to
be built explicitly.

The seeded content deliberately covers the part ids and colors the end-to-end
fixtures reference (`apps/web/e2e/synthetic.ts` and
`inventory-import.spec.ts`), so the same helper can back the e2e catalog seed
without a network fetch of the official archive.

Note that `library_root` matters beyond indexing: the moved-alias resolver in
`model_import.derive_parsed_model` reads part files from it, so a client under
test must be created with the root returned here for `MOVED_ALIAS_PART_ID` to
canonicalize.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.services.ldraw_catalog import RebuildReport, rebuild_catalog
from app.services.ldraw_library import manifest_path_for

# Distinct from test_catalog.py's fingerprint so a seed can tell its own
# synthetic index apart from another one.
FINGERPRINT = "d" * 64

IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"

# Part ids the e2e fixtures reference: core-loop uses 3001 and 3020,
# inventory-import uses 3005, 3004, and 3622.
FIXTURE_PARTS: tuple[tuple[str, str, str], ...] = (
    ("3001", "Brick 2 x 4", "Brick"),
    ("3004", "Brick 1 x 2", "Brick"),
    ("3005", "Brick 1 x 1", "Brick"),
    ("3020", "Plate 2 x 4", "Plate"),
    ("3622", "Brick 1 x 3", "Brick"),
)

# An extra official part no fixture references, for tests that need a second
# requirement key without disturbing the fixture expectations.
SPARE_PART_ID = "3003"

# A ~Moved to alias that canonicalizes onto 3001 through the alias resolver.
MOVED_ALIAS_PART_ID = "3001a"

# An indexed p/ primitive. Referenced bare it resolves as a primitive; under
# p/ it takes the rendering-only path.
PRIMITIVE_NAME = "box.dat"

# Colors the fixtures use. 16 and 24 are special-cased by the parser and are
# never catalog rows.
FIXTURE_COLORS: tuple[tuple[int, str, str], ...] = (
    (1, "Blue", "#0055BF"),
    (2, "Green", "#237841"),
    (4, "Red", "#C91A09"),
    (14, "Yellow", "#F2CD37"),
    (19, "Tan", "#E4CD9E"),
    (27, "Lime", "#A5CA18"),
    (71, "Light_Bluish_Gray", "#A0A5A9"),
)

# A physical color code deliberately left out of the index, so a reference
# using it still counts the part while raising an `unknown_color` warning.
UNINDEXED_COLOR_CODE = 272


def write_part(
    library_root: Path,
    relative_path: str,
    description: str,
    category: str,
    author: str = "Test Author",
) -> None:
    path = library_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"0 {description}\n"
        f"0 Name: {path.name}\n"
        f"0 Author: {author}\n"
        "0 !LDRAW_ORG Part\n"
        "0 !LICENSE Licensed for testing\n"
        f"0 !CATEGORY {category}\n"
        "0 !KEYWORDS sample, test\n"
        "3 16 0 0 0 1 0 0 0 1 0\n",
        encoding="utf-8",
    )


def write_moved_alias(library_root: Path, part_id: str, target_part_id: str) -> None:
    """Write an alias the resolver accepts: matching header, one target line."""
    path = library_root / "parts" / f"{part_id}.dat"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"0 ~Moved to {target_part_id}\n"
        f"0 Name: {part_id}.dat\n"
        "0 !LDRAW_ORG Part\n"
        f"1 16 {IDENTITY} {target_part_id}.dat\n",
        encoding="utf-8",
    )


def build_synthetic_library(root: Path, *, include_moved_alias: bool = True) -> Path:
    """Write a valid LDraw library, manifest included, at `root`.

    `include_moved_alias` is on by default because the alias is a resolution
    path worth covering. `rebuild_catalog` skips only subparts, so the alias
    also lands in `parts` as a searchable row named `~Moved to 3001` and shows
    up in `/api/parts`. The end-to-end seed turns it off: no fixture needs an
    alias, and the product's part search should not offer one during a gate.
    """
    (root / "parts").mkdir(parents=True)
    (root / "p").mkdir()
    (root / "p" / PRIMITIVE_NAME).write_text("0 Primitive\n", encoding="utf-8")
    (root / "LDConfig.ldr").write_text(
        "".join(
            f"0 !COLOUR {name} CODE {code} VALUE {value} EDGE #333333\n"
            for code, name, value in FIXTURE_COLORS
        ),
        encoding="utf-8",
    )
    for part_id, description, category in FIXTURE_PARTS:
        write_part(root, f"parts/{part_id}.dat", description, category, "James Jessiman")
    write_part(root, f"parts/{SPARE_PART_ID}.dat", "Brick 2 x 2", "Brick")
    if include_moved_alias:
        write_moved_alias(root, MOVED_ALIAS_PART_ID, "3001")
    write_part(root, "parts/s/3001s01.dat", "Brick Subpart", "Subpart")
    dat_count = 9 if include_moved_alias else 8
    manifest_path_for(root).write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "installed_at": "2026-01-01T00:00:00+00:00",
                "source": "synthetic test archive",
                "archive_sha256": FINGERPRINT,
                "file_counts": {"dat": dat_count, "ldr": 1, "png": 0},
            }
        ),
        encoding="utf-8",
    )
    return root


def index_synthetic_catalog(
    factory: sessionmaker[Session], tmp_path: Path
) -> tuple[Path, RebuildReport]:
    """Build the library under `tmp_path` and index it into `factory`'s schema."""
    root = build_synthetic_library(tmp_path / "official")
    return root, rebuild_catalog(factory, root)
