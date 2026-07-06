from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import get_settings
from app.database import get_session_factory
from app.services.ldraw_catalog import CatalogError, get_catalog_status, rebuild_catalog


def _library_root() -> Path:
    return get_settings().ldraw_library_root


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the indexed LDraw catalog")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("rebuild", help="Transactionally rebuild the official catalog")
    commands.add_parser("status", help="Report catalog and fingerprint status")
    return parser


def _print_status() -> None:
    with get_session_factory()() as session:
        status = get_catalog_status(session, _library_root())
    print(f"Library installed: {'yes' if status.library_installed else 'no'}")
    print(f"Catalog indexed: {'yes' if status.indexed else 'no'}")
    print(f"Index stale: {'yes' if status.stale else 'no'}")
    print(f"Indexed parts: {status.part_count}")
    print(f"Indexed colors: {status.color_count}")
    print(f"Indexed at: {status.indexed_at.isoformat() if status.indexed_at else 'not indexed'}")
    print(f"Installed fingerprint: {status.installed_fingerprint or 'unavailable'}")
    print(f"Indexed fingerprint: {status.indexed_fingerprint or 'unavailable'}")


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "status":
        _print_status()
        return 0

    print("Parsing the installed official LDraw library…")
    try:
        report = rebuild_catalog(get_session_factory(), _library_root())
    except CatalogError as error:
        print(f"Catalog rebuild failed: {error}")
        return 1

    print(f"Parsed files: {report.parsed_file_count}")
    print(f"Indexed parts: {report.indexed_part_count}")
    print(f"Skipped subparts: {report.skipped_subpart_count}")
    print(f"Skipped or invalid files: {report.skipped_invalid_count}")
    print(f"Indexed colors: {report.indexed_color_count}")
    print(f"Library fingerprint: {report.library_fingerprint}")
    print(f"Completed in {report.duration_seconds:.2f} seconds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
