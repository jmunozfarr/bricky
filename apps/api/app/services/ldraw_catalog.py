from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session, sessionmaker

from app.models import CatalogIndexState, LDrawColor, LDrawPrimitive, Part
from app.services.ldraw_library import get_library_status
from app.services.ldraw_metadata import parse_color_config, parse_part_header

INDEXER_VERSION = "1"


class CatalogError(Exception):
    """Raised when the explicit catalog operation cannot complete."""


@dataclass(frozen=True)
class RebuildReport:
    parsed_file_count: int
    indexed_part_count: int
    skipped_subpart_count: int
    skipped_invalid_count: int
    indexed_color_count: int
    indexed_primitive_count: int
    library_fingerprint: str
    duration_seconds: float


@dataclass(frozen=True)
class CatalogStatus:
    library_installed: bool
    indexed: bool
    stale: bool
    part_count: int
    color_count: int
    indexed_at: datetime | None
    installed_fingerprint: str | None
    indexed_fingerprint: str | None


def get_catalog_status(session: Session, library_root: Path) -> CatalogStatus:
    library = get_library_status(library_root)
    state = session.get(CatalogIndexState, 1)
    installed_fingerprint = library.archive_sha256 if library.installed else None
    indexed = state is not None
    stale = state is not None and (
        installed_fingerprint is None or state.library_fingerprint != installed_fingerprint
    )
    return CatalogStatus(
        library_installed=library.installed,
        indexed=indexed,
        stale=stale,
        part_count=state.part_count if state is not None else 0,
        color_count=state.color_count if state is not None else 0,
        indexed_at=state.indexed_at if state is not None else None,
        installed_fingerprint=installed_fingerprint,
        indexed_fingerprint=state.library_fingerprint if state is not None else None,
    )


def rebuild_catalog(session_factory: sessionmaker[Session], library_root: Path) -> RebuildReport:
    started = datetime.now(UTC)
    library = get_library_status(library_root)
    if not library.installed:
        detail = f": {library.problem}" if library.problem else ""
        raise CatalogError(f"Official LDraw library is not installed or valid{detail}")
    if library.archive_sha256 is None:
        raise CatalogError("Installed library manifest has no usable fingerprint")

    parts_root = library_root / "parts"
    part_rows: list[dict[str, object]] = []
    parsed_file_count = 0
    skipped_subpart_count = 0
    skipped_invalid_count = 0
    seen_part_ids: set[str] = set()

    for source_path in sorted(parts_root.rglob("*.dat")):
        relative_path = source_path.relative_to(library_root).as_posix()
        try:
            header = parse_part_header(source_path.read_bytes(), relative_path)
            parsed_file_count += 1
            if header.is_subpart:
                skipped_subpart_count += 1
                continue
            if source_path.parent != parts_root or header.part_id in seen_part_ids:
                skipped_invalid_count += 1
                continue
            seen_part_ids.add(header.part_id)
            part_rows.append(
                {
                    "part_id": header.part_id,
                    "name": header.description,
                    "relative_path": header.relative_path,
                    "author": header.author,
                    "category": header.category,
                    "org_classification": header.org_classification,
                    "license": header.license,
                    "keywords": ", ".join(header.keywords) or None,
                    "is_subpart": False,
                    "is_shortcut": header.is_shortcut,
                }
            )
        except OSError, ValueError:
            skipped_invalid_count += 1

    primitives_root = library_root / "p"
    primitive_names: set[str] = set()
    if primitives_root.is_dir():
        for source_path in primitives_root.rglob("*.dat"):
            relative_name = source_path.relative_to(primitives_root).as_posix().lower()
            if len(relative_name) <= 255:
                primitive_names.add(relative_name)

    try:
        color_definitions = parse_color_config((library_root / "LDConfig.ldr").read_bytes())
    except OSError as error:
        raise CatalogError(f"Unable to read LDConfig.ldr: {error}") from error
    color_rows = [
        {
            "code": color.code,
            "name": color.name,
            "value_hex": color.value_hex,
            "edge_hex": color.edge_hex,
            "alpha": color.alpha,
            "luminance": color.luminance,
            "finish": color.finish,
        }
        for color in color_definitions
    ]

    indexed_at = datetime.now(UTC)
    try:
        with session_factory.begin() as session:
            session.execute(delete(CatalogIndexState))
            session.execute(delete(Part))
            session.execute(delete(LDrawColor))
            session.execute(delete(LDrawPrimitive))
            if part_rows:
                session.execute(insert(Part), part_rows)
            if color_rows:
                session.execute(insert(LDrawColor), color_rows)
            if primitive_names:
                session.execute(
                    insert(LDrawPrimitive),
                    [{"name": name} for name in sorted(primitive_names)],
                )
            session.add(
                CatalogIndexState(
                    id=1,
                    library_fingerprint=library.archive_sha256,
                    indexed_at=indexed_at,
                    part_count=len(part_rows),
                    color_count=len(color_rows),
                    indexer_version=INDEXER_VERSION,
                )
            )
    except Exception as error:
        raise CatalogError(f"Database rebuild failed: {error}") from error

    duration = (datetime.now(UTC) - started).total_seconds()
    return RebuildReport(
        parsed_file_count=parsed_file_count,
        indexed_part_count=len(part_rows),
        skipped_subpart_count=skipped_subpart_count,
        skipped_invalid_count=skipped_invalid_count,
        indexed_color_count=len(color_rows),
        indexed_primitive_count=len(primitive_names),
        library_fingerprint=library.archive_sha256,
        duration_seconds=duration,
    )
