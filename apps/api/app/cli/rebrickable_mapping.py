from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.database import get_session_factory
from app.services.rebrickable_mapping import (
    RebrickableMappingError,
    get_mapping_status,
    populate_mappings,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the Rebrickable/BrickLink -> LDraw ID mapping table"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "populate", help="Fetch the Rebrickable API and transactionally replace the mapping table"
    )
    commands.add_parser("status", help="Report mapping table freshness")
    return parser


def _print_status() -> None:
    with get_session_factory()() as session:
        status = get_mapping_status(session)
    print(f"Mapping populated: {'yes' if status.populated else 'no'}")
    print(f"Part mappings: {status.part_mapping_count}")
    print(f"Color mappings: {status.color_mapping_count}")
    print(f"Ambiguous parts: {status.ambiguous_part_count}")
    print(f"Populated at: {status.populated_at.isoformat() if status.populated_at else 'never'}")
    print(f"Fetcher version: {status.fetcher_version or 'unavailable'}")


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "status":
        _print_status()
        return 0

    print("Fetching colors and parts from the Rebrickable API…")
    try:
        report = populate_mappings(get_session_factory(), get_settings().rebrickable_api_key)
    except RebrickableMappingError as error:
        print(f"Mapping populate failed: {error}")
        return 1

    print(f"Fetched colors: {report.fetched_color_count}")
    print(f"Fetched parts: {report.fetched_part_count}")
    print(
        f"Color mappings: {report.color_mapping_count} (collisions: {report.color_collision_count})"
    )
    print(f"Part mappings: {report.part_mapping_count} (ambiguous: {report.ambiguous_part_count})")
    print(f"Completed in {report.duration_seconds:.2f} seconds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
