"""Re-derive a model's BOM, issues, and counters from its immutable original."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ImportedModel, ModelReferenceResolution
from app.services.ldraw_model_parser import (
    ModelParseError,
    ParsedModel,
    ReferenceResolution,
)
from app.services.local_workspace import resolve_local_workspace
from app.services.model_import import (
    ModelImportError,
    apply_model_content,
    derive_model_content,
    derive_parsed_model,
    load_catalog_context,
    managed_source_path,
    replace_model_rows,
)


class ModelReprocessError(Exception):
    """Safe reprocess error suitable for an HTTP response."""


class ModelNotFoundError(ModelReprocessError):
    pass


class ModelSourceUnavailableError(ModelReprocessError):
    pass


class ModelSourceIntegrityError(ModelReprocessError):
    pass


def load_reference_resolutions(session: Session, model_id: int) -> dict[str, ReferenceResolution]:
    rows = session.scalars(
        select(ModelReferenceResolution).where(ModelReferenceResolution.model_id == model_id)
    )
    return {
        row.source_reference: ReferenceResolution(
            action=row.action,
            part_id=row.target_part_id,
            color_code=row.color_code,
        )
        for row in rows
    }


@dataclass(frozen=True)
class ModelReprocessOutcome:
    public_id: uuid.UUID
    name: str
    previous_status: str
    import_status: str
    parsed: ParsedModel


def reprocess_model(
    session_factory: sessionmaker[Session],
    storage_root: Path,
    library_root: Path,
    public_id: uuid.UUID,
) -> ModelReprocessOutcome:
    """Re-run the import derivation pipeline against the stored original.

    The stored source is never modified; only the derived rows (BOM items,
    import issues) and derived model columns are replaced, atomically.
    """
    with session_factory.begin() as session:
        workspace = resolve_local_workspace(session)
        model = session.scalar(
            select(ImportedModel).where(
                ImportedModel.public_id == public_id,
                ImportedModel.workspace_id == workspace.id,
            )
        )
        if model is None:
            raise ModelNotFoundError("Model not found")
        source_path = managed_source_path(storage_root, model)
        if source_path is None or not source_path.is_file():
            raise ModelSourceUnavailableError("Model source not found")
        source_bytes = source_path.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != model.source_sha256:
            raise ModelSourceIntegrityError(
                "Stored model source no longer matches its recorded checksum"
            )
        catalog = load_catalog_context(session)
        resolutions = load_reference_resolutions(session, model.id)
        previous_status = model.import_status
        try:
            parsed = derive_parsed_model(source_bytes, catalog, library_root, resolutions)
        except ModelParseError as error:
            raise ModelImportError(str(error)) from error
        apply_model_content(model, derive_model_content(parsed))
        replace_model_rows(session, model.id, parsed)
        return ModelReprocessOutcome(
            public_id=model.public_id,
            name=model.name,
            previous_status=previous_status,
            import_status=model.import_status,
            parsed=parsed,
        )
