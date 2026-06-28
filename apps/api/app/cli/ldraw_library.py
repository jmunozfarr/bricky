from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.services.ldraw_library import (
    DEFAULT_LIBRARY_URL,
    LibraryError,
    get_library_status,
    install_library,
)


def _library_root() -> Path:
    return Path(os.environ.get("LDRAW_LIBRARY_ROOT", "/data/ldraw/official"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the local official LDraw library")
    commands = parser.add_subparsers(dest="command", required=True)

    install = commands.add_parser("install", help="Install the official LDraw library")
    install.add_argument(
        "--archive",
        type=Path,
        help="Install from a ZIP already available inside the API container",
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing library after a complete replacement is ready",
    )

    commands.add_parser("status", help="Report local library status")
    return parser


def _print_status() -> None:
    status = get_library_status(_library_root())
    if not status.installed:
        print("Official LDraw library is not installed.")
        if status.problem is not None:
            print(f"Problem: {status.problem}")
        return

    print("Official LDraw library is installed.")
    if status.file_counts is not None:
        print(f"File counts: {json.dumps(status.file_counts.to_dict(), sort_keys=True)}")
    if status.manifest is not None:
        print(f"Installed at: {status.manifest.installed_at}")
        print(f"Source: {status.manifest.source}")
        print(f"Archive SHA-256: {status.manifest.archive_sha256}")
    elif status.problem is not None:
        print(f"Warning: {status.problem}")


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "status":
        _print_status()
        return 0

    try:
        manifest = install_library(
            _library_root(),
            source_url=os.environ.get("LDRAW_LIBRARY_URL", DEFAULT_LIBRARY_URL),
            archive_path=args.archive,
            force=args.force,
        )
    except LibraryError as error:
        print(f"Installation failed: {error}")
        return 1

    print("Official LDraw library installed successfully.")
    print(f"Archive SHA-256: {manifest.archive_sha256}")
    print(f"File counts: {json.dumps(manifest.file_counts.to_dict(), sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
