from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.database import get_session_factory
from app.services.rebrickable_mapping import (
    RebrickableMappingError,
    get_mapping_status,
    populate_mappings,
)
from app.services.rebrickable_sets import (
    RebrickableSetsError,
    get_set_data_status,
    populate_sets,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Rebrickable-sourced ID mapping and set data"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "populate", help="Fetch the Rebrickable API and transactionally replace the mapping table"
    )
    commands.add_parser(
        "populate-sets",
        help="Download the public Rebrickable set dumps and transactionally replace set data",
    )
    commands.add_parser("status", help="Report mapping and set data freshness")
    return parser


def _print_status() -> None:
    with get_session_factory()() as session:
        mapping_status = get_mapping_status(session)
        set_status = get_set_data_status(session)
    print(f"Mapping populated: {'yes' if mapping_status.populated else 'no'}")
    print(f"Part mappings: {mapping_status.part_mapping_count}")
    print(f"Color mappings: {mapping_status.color_mapping_count}")
    print(f"Ambiguous parts: {mapping_status.ambiguous_part_count}")
    print(
        "Mapping populated at: "
        f"{mapping_status.populated_at.isoformat() if mapping_status.populated_at else 'never'}"
    )
    print(f"Mapping fetcher version: {mapping_status.fetcher_version or 'unavailable'}")
    print()
    print(f"Set data populated: {'yes' if set_status.populated else 'no'}")
    print(f"Sets: {set_status.set_count}")
    print(f"Set part rows: {set_status.part_row_count}")
    print(
        "Set data populated at: "
        f"{set_status.populated_at.isoformat() if set_status.populated_at else 'never'}"
    )
    print(f"Set data fetcher version: {set_status.fetcher_version or 'unavailable'}")


def _populate_mapping() -> int:
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


def _populate_sets() -> int:
    print("Downloading and ingesting the public Rebrickable set dumps…")
    try:
        report = populate_sets(get_session_factory())
    except RebrickableSetsError as error:
        print(f"Set data populate failed: {error}")
        return 1

    print(f"Sets ingested: {report.set_count}")
    print(f"Set part rows ingested: {report.part_row_count}")
    print(f"Completed in {report.duration_seconds:.2f} seconds")
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "status":
        _print_status()
        return 0
    if args.command == "populate-sets":
        return _populate_sets()
    return _populate_mapping()


if __name__ == "__main__":
    raise SystemExit(main())
