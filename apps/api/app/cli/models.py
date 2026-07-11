from __future__ import annotations

import argparse
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.database import get_session_factory
from app.models import ImportedModel, Workspace
from app.services.local_workspace import LOCAL_WORKSPACE_SLUG
from app.services.model_import import ModelImportError
from app.services.model_reprocess import ModelReprocessError, reprocess_model


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage imported models")
    commands = parser.add_subparsers(dest="command", required=True)
    reprocess = commands.add_parser(
        "reprocess",
        help="Re-derive BOM, issues, and counters from the stored originals",
    )
    reprocess.add_argument("--all", action="store_true", help="Reprocess every imported model")
    reprocess.add_argument(
        "model_ids",
        nargs="*",
        type=uuid.UUID,
        help="Public model ids to reprocess",
    )
    return parser


def reprocess_targets(
    session_factory: sessionmaker[Session],
    storage_root: Path,
    library_root: Path,
    model_ids: Sequence[uuid.UUID] | None = None,
) -> int:
    with session_factory() as session:
        rows = (
            session.execute(
                select(ImportedModel.public_id, ImportedModel.name)
                .join(Workspace, Workspace.id == ImportedModel.workspace_id)
                .where(Workspace.slug == LOCAL_WORKSPACE_SLUG)
                .order_by(ImportedModel.id)
            )
            .tuples()
            .all()
        )
    known: dict[uuid.UUID, str] = dict(rows)
    targets = list(model_ids) if model_ids else list(known)
    failures = 0
    for public_id in targets:
        label = known.get(public_id, str(public_id))
        try:
            outcome = reprocess_model(session_factory, storage_root, library_root, public_id)
        except (ModelReprocessError, ModelImportError) as error:
            failures += 1
            print(f"{label}: FAILED ({error})")
            continue
        warning_count = sum(1 for issue in outcome.parsed.issues if issue.severity == "warning")
        print(
            f"{label}: {outcome.previous_status} -> {outcome.import_status} "
            f"({len(outcome.parsed.bom)} part/color rows, {warning_count} warnings)"
        )
    print(f"Reprocessed {len(targets) - failures} of {len(targets)} models")
    return 1 if failures else 0


def main() -> int:
    args = _build_parser().parse_args()
    if args.command != "reprocess":
        return 2
    if bool(args.all) == bool(args.model_ids):
        print("Provide either --all or one or more model ids")
        return 2
    settings = get_settings()
    return reprocess_targets(
        get_session_factory(),
        settings.model_storage_root,
        settings.ldraw_library_root,
        None if args.all else args.model_ids,
    )


if __name__ == "__main__":
    raise SystemExit(main())
