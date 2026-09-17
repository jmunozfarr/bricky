"""Give the end-to-end gate an indexed catalog, without a network fetch.

Run from `scripts/e2e.sh`, before Playwright starts; by hand, from the repository root:

    docker compose -f compose.yaml run --rm -e PYTHONPATH=. api python tests/seed_e2e_catalog.py

A one-shot `run --rm` container rather than `exec` into a running one, so the seed does not
need the stack already up, and pinned to `compose.yaml` because `tests/` reaches the container
only through the development api service's `apps/api` bind mount, which the production stack
does not have.

Why the gate needs this. `apps/web/e2e` asserts concrete coverage numbers
(`40% covered` / `3 pieces missing`, `60% covered` / `2 pieces missing`), and
those are only reachable with an *indexed* catalog: `load_catalog_context`
builds `official_part_ids` from the `parts` table, so with zero rows every
official reference takes the unresolved branch in `ldraw_model_parser` and the
BOM comes out empty. The gate used to document the opposite as fact. Installing
the official archive would fix it by putting a large network download, an
archive cache, and a licensing question into a gate that is otherwise hermetic,
so this seeds the synthetic library `synthetic_catalog.py` already builds for
the API suite instead — the same part ids and colors the fixtures reference,
deterministic, and indexed in well under a second.

Two constraints shape the implementation.

**The library is built outside `LDRAW_LIBRARY_ROOT`, and thrown away.** Only
the `parts` / `ldraw_colors` / `ldraw_primitives` rows are wanted; nothing
reads the library files again once `rebuild_catalog` has parsed them. Writing a
six-part stub to the configured root would instead make `/api/ldraw/LDConfig.ldr`
resolve, which is the guard `builder.spec.ts` skips on, and its four WebGL
tests would start driving scenes built from single-triangle placeholders.
Installing the real library stays the documented manual step (README, and
`docs/OPERATIONS.md`), so those four tests keep skipping in CI. That is a known
gap, stated rather than silent: because the skip precedes their database guard,
their assertions have effectively never run and should be expected to surface
failures the first time a real library is present.

**It refuses to replace a real catalog.** `rebuild_catalog` deletes and
repopulates all four catalog tables, and the e2e stack runs against the
developer's personal database — `core-loop.spec.ts` snapshots and restores real
inventory rows for exactly that reason. So the seed runs only when nothing is
indexed or when what is indexed is its own synthetic fingerprint, and it
verifies that `inventory_items` is untouched either way.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from synthetic_catalog import FINGERPRINT, build_synthetic_library

from app.core.config import get_settings
from app.database import get_session_factory
from app.models import InventoryItem
from app.services.ldraw_catalog import CatalogError, get_catalog_status, rebuild_catalog


def inventory_row_count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(InventoryItem)) or 0


def main() -> int:
    settings = get_settings()
    library_root = settings.ldraw_library_root
    factory = get_session_factory()

    with factory() as session:
        status = get_catalog_status(session, library_root)

    if status.indexed and status.indexed_fingerprint != FINGERPRINT:
        print(
            "Refusing to seed: this database already has a catalog indexed from another "
            f"library ({status.part_count} parts, fingerprint "
            f"{(status.indexed_fingerprint or 'unknown')[:12]}…).\n"
            "Rebuilding would replace it with a six-part stub, so the seed stops here. "
            "The end-to-end coverage assertions need an indexed catalog and you have one, "
            "so they will run against yours."
        )
        return 0

    if status.library_installed:
        # Nothing is indexed, so no real catalog is at risk, but the fingerprint
        # this seed records will not match the installed library.
        print(
            f"Note: a real LDraw library is installed at {library_root} but has never been "
            "indexed. Seeding marks the catalog stale against it; run "
            "`python -m app.cli.ldraw_catalog rebuild` to index the real library afterwards."
        )

    inventory_before = inventory_row_count(factory)

    # A throwaway root: the rows are the artifact, and a stub at the configured
    # root would make the library look installed. See the module docstring.
    with tempfile.TemporaryDirectory(prefix="bricky-e2e-catalog-") as temporary:
        root = build_synthetic_library(Path(temporary) / "official", include_moved_alias=False)
        try:
            report = rebuild_catalog(factory, root)
        except CatalogError as error:
            print(f"Catalog seed failed: {error}")
            return 1

    inventory_after = inventory_row_count(factory)
    if inventory_after != inventory_before:
        print(
            "Catalog seed changed inventory_items "
            f"({inventory_before} rows before, {inventory_after} after); this must never happen."
        )
        return 1

    print(
        f"Seeded a synthetic catalog: {report.indexed_part_count} parts, "
        f"{report.indexed_color_count} colors, {report.indexed_primitive_count} primitives "
        f"in {report.duration_seconds:.2f}s. "
        f"Inventory untouched ({inventory_after} rows). "
        "The official library is still not installed, so the 3D scene specs keep skipping."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
