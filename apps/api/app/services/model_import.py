from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    ImportedModel,
    LDrawColor,
    LDrawPrimitive,
    ModelBomItem,
    ModelImportIssue,
    Part,
    Workspace,
)
from app.services.ldraw_aliases import (
    AliasResolutionStatus,
    LDrawMovedAliasResolver,
    OfficialPartRecord,
)
from app.services.ldraw_model_parser import (
    BomEntry,
    ModelParseError,
    ParsedModel,
    ParseIssue,
    parse_ldraw_model,
)
from app.services.local_workspace import LOCAL_WORKSPACE_SLUG, resolve_local_workspace

DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class ModelImportError(Exception):
    """Safe import error suitable for an HTTP 422 response."""


class ModelTooLargeError(ModelImportError):
    pass


class DuplicateModelError(ModelImportError):
    def __init__(self, existing_model_id: uuid.UUID) -> None:
        self.existing_model_id = existing_model_id
        super().__init__("An identical model source is already imported")


@dataclass(frozen=True)
class ModelImportOutcome:
    public_id: uuid.UUID
    parsed: ParsedModel


UNRESOLVED_ISSUE_CODES = frozenset(
    {
        "unresolved_reference",
        "unsupported_custom_part",
        "malformed_type1_reference",
        "moved_alias_cycle",
        "moved_alias_missing_target",
        "moved_alias_malformed",
        "moved_alias_depth_exceeded",
    }
)


@dataclass(frozen=True)
class CatalogContext:
    """Catalog rows needed to derive a model's physical BOM, loaded in one session."""

    part_records: tuple[OfficialPartRecord, ...]
    official_part_ids: frozenset[str]
    known_color_codes: frozenset[int]
    known_primitive_names: frozenset[str]


@dataclass(frozen=True)
class DerivedModelContent:
    import_status: str
    declared_step_count: int
    total_part_quantity: int
    unique_part_color_count: int
    unresolved_reference_count: int


def load_catalog_context(session: Session) -> CatalogContext:
    part_records = tuple(
        OfficialPartRecord(part_id=part_id, description=description, relative_path=relative_path)
        for part_id, description, relative_path in session.execute(
            select(Part.part_id, Part.name, Part.relative_path).where(Part.is_subpart.is_(False))
        )
    )
    return CatalogContext(
        part_records=part_records,
        official_part_ids=frozenset(part.part_id for part in part_records),
        known_color_codes=frozenset(session.scalars(select(LDrawColor.code))),
        known_primitive_names=frozenset(session.scalars(select(LDrawPrimitive.name))),
    )


def derive_parsed_model(
    source_bytes: bytes, catalog: CatalogContext, library_root: Path
) -> ParsedModel:
    """Run the full source-to-BOM pipeline shared by import and reprocess."""
    parsed = parse_ldraw_model(
        source_bytes,
        official_part_ids=catalog.official_part_ids,
        known_color_codes=catalog.known_color_codes,
        known_primitive_names=catalog.known_primitive_names,
    )
    return _canonicalize_moved_aliases(
        parsed,
        LDrawMovedAliasResolver(library_root, catalog.part_records),
    )


def derive_model_content(parsed: ParsedModel) -> DerivedModelContent:
    return DerivedModelContent(
        import_status="ready_with_warnings" if parsed.issues else "ready",
        declared_step_count=parsed.declared_step_count,
        total_part_quantity=sum(item.quantity for item in parsed.bom),
        unique_part_color_count=len(parsed.bom),
        unresolved_reference_count=sum(
            1 for issue in parsed.issues if issue.code in UNRESOLVED_ISSUE_CODES
        ),
    )


def apply_model_content(model: ImportedModel, content: DerivedModelContent) -> None:
    model.import_status = content.import_status
    model.declared_step_count = content.declared_step_count
    model.total_part_quantity = content.total_part_quantity
    model.unique_part_color_count = content.unique_part_color_count
    model.unresolved_reference_count = content.unresolved_reference_count


def replace_model_rows(session: Session, model_id: int, parsed: ParsedModel) -> None:
    session.execute(delete(ModelBomItem).where(ModelBomItem.model_id == model_id))
    session.execute(delete(ModelImportIssue).where(ModelImportIssue.model_id == model_id))
    session.add_all(
        ModelBomItem(
            model_id=model_id,
            part_id=item.part_id,
            color_code=item.color_code,
            quantity=item.quantity,
        )
        for item in parsed.bom
    )
    session.add_all(
        ModelImportIssue(
            model_id=model_id,
            severity=issue.severity,
            code=issue.code,
            message=issue.message,
            referenced_filename=issue.referenced_filename,
        )
        for issue in parsed.issues
    )


def managed_source_path(storage_root: Path, model: ImportedModel) -> Path | None:
    """Resolve a model's immutable original inside the managed storage root."""
    relative = PurePosixPath(model.relative_storage_path)
    expected_prefix = ("originals", str(model.public_id))
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) != 3
        or relative.parts[:2] != expected_prefix
        or relative.name != model.safe_filename
    ):
        return None
    root = storage_root.resolve()
    candidate = (root / Path(*relative.parts)).resolve()
    if not candidate.is_relative_to(root):
        return None
    return candidate


def _clean_original_filename(filename: str | None) -> str:
    candidate = (filename or "model.ldr").replace("\\", "/")
    basename = PurePosixPath(candidate).name
    cleaned = "".join(character for character in basename if character.isprintable())
    return cleaned[:255] or "model.ldr"


def _source_format(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in {".ldr", ".mpd"}:
        raise ModelImportError("Only .ldr and .mpd files are supported")
    return extension[1:]


def _safe_filename(original_filename: str, source_format: str) -> str:
    stem = Path(original_filename).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-_")[:200]
    return f"{safe_stem or 'model'}.{source_format}"


def _display_name(requested_name: str | None, original_filename: str) -> str:
    candidate = requested_name.strip() if requested_name else Path(original_filename).stem
    cleaned = " ".join(
        "".join(character for character in candidate if character.isprintable()).split()
    )
    if not cleaned:
        raise ModelImportError("Model name cannot be empty")
    return cleaned[:256]


def _stream_original(source: BinaryIO, destination: Path, maximum_bytes: int) -> str:
    digest = hashlib.sha256()
    total = 0
    with destination.open("xb") as output:
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > maximum_bytes:
                raise ModelTooLargeError(
                    f"Model exceeds the configured {maximum_bytes}-byte upload limit"
                )
            digest.update(chunk)
            output.write(chunk)
    if total == 0:
        raise ModelImportError("The uploaded model is empty")
    return digest.hexdigest()


def _find_duplicate(session: Session, source_sha256: str) -> ImportedModel | None:
    return session.scalar(
        select(ImportedModel)
        .join(Workspace, Workspace.id == ImportedModel.workspace_id)
        .where(
            ImportedModel.source_sha256 == source_sha256,
            Workspace.slug == LOCAL_WORKSPACE_SLUG,
        )
    )


def _canonicalize_moved_aliases(
    parsed: ParsedModel, resolver: LDrawMovedAliasResolver
) -> ParsedModel:
    resolutions = resolver.resolve_many({item.part_id for item in parsed.bom})
    quantities: Counter[tuple[str, int]] = Counter()
    issues = list(parsed.issues)
    issue_details: dict[AliasResolutionStatus, tuple[str, str]] = {
        "cycle": (
            "moved_alias_cycle",
            "Moved-part alias cycle prevented canonical resolution; "
            "the original part ID was retained",
        ),
        "missing_target": (
            "moved_alias_missing_target",
            "Moved-part alias target is unavailable; the original part ID was retained",
        ),
        "malformed": (
            "moved_alias_malformed",
            "Moved-part alias metadata or target reference is malformed; "
            "the original part ID was retained",
        ),
        "depth_exceeded": (
            "moved_alias_depth_exceeded",
            "Moved-part alias chain exceeded the safe depth limit; "
            "the original part ID was retained",
        ),
    }
    warned_part_ids: set[str] = set()

    for item in parsed.bom:
        resolution = resolutions[item.part_id]
        persisted_part_id = (
            resolution.canonical_part_id if resolution.status == "resolved" else item.part_id
        )
        quantities[(persisted_part_id, item.color_code)] += item.quantity
        if (
            resolution.status in issue_details
            and resolution.original_part_id.lower() not in warned_part_ids
        ):
            warned_part_ids.add(resolution.original_part_id.lower())
            code, message = issue_details[resolution.status]
            issues.append(
                ParseIssue(
                    severity="warning",
                    code=code,
                    message=message,
                    referenced_filename=f"{resolution.original_part_id}.dat"[:255],
                )
            )

    bom = tuple(
        BomEntry(part_id=part_id, color_code=color_code, quantity=quantity)
        for (part_id, color_code), quantity in sorted(
            quantities.items(), key=lambda item: (item[0][0].lower(), item[0][1])
        )
    )
    return ParsedModel(
        bom=bom,
        issues=tuple(issues),
        declared_step_count=parsed.declared_step_count,
        main_file_name=parsed.main_file_name,
        encoding=parsed.encoding,
    )


def import_model(
    session_factory: sessionmaker[Session],
    storage_root: Path,
    library_root: Path,
    source: BinaryIO,
    original_filename: str | None,
    requested_name: str | None,
    maximum_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> ModelImportOutcome:
    if maximum_bytes <= 0:
        raise ModelImportError("Configured upload limit must be positive")
    clean_filename = _clean_original_filename(original_filename)
    source_format = _source_format(clean_filename)
    safe_filename = _safe_filename(clean_filename, source_format)
    model_name = _display_name(requested_name, clean_filename)

    storage_root.mkdir(parents=True, exist_ok=True)
    temp_directory = Path(tempfile.mkdtemp(prefix=".model-import-", dir=storage_root))
    temp_source = temp_directory / safe_filename
    final_directory: Path | None = None
    try:
        source_sha256 = _stream_original(source, temp_source, maximum_bytes)
        with session_factory.begin() as session:
            resolve_local_workspace(session)
            duplicate = _find_duplicate(session, source_sha256)
            if duplicate is not None:
                raise DuplicateModelError(duplicate.public_id)
            catalog = load_catalog_context(session)

        source_bytes = temp_source.read_bytes()
        try:
            parsed = derive_parsed_model(source_bytes, catalog, library_root)
        except ModelParseError as error:
            raise ModelImportError(str(error)) from error

        public_id = uuid.uuid4()
        final_directory = storage_root / "originals" / str(public_id)
        final_directory.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp_directory, final_directory)
        relative_storage_path = (
            PurePosixPath("originals") / str(public_id) / safe_filename
        ).as_posix()

        try:
            with session_factory.begin() as session:
                workspace = resolve_local_workspace(session)
                duplicate = _find_duplicate(session, source_sha256)
                if duplicate is not None:
                    raise DuplicateModelError(duplicate.public_id)
                model = ImportedModel(
                    public_id=public_id,
                    workspace_id=workspace.id,
                    name=model_name,
                    original_filename=clean_filename,
                    safe_filename=safe_filename,
                    source_format=source_format,
                    relative_storage_path=relative_storage_path,
                    source_sha256=source_sha256,
                )
                apply_model_content(model, derive_model_content(parsed))
                session.add(model)
                session.flush()
                replace_model_rows(session, model.id, parsed)
        except IntegrityError as error:
            with session_factory() as lookup_session:
                duplicate = _find_duplicate(lookup_session, source_sha256)
            if duplicate is not None:
                raise DuplicateModelError(duplicate.public_id) from error
            raise
        return ModelImportOutcome(public_id=public_id, parsed=parsed)
    except BaseException:
        if final_directory is not None and final_directory.exists():
            shutil.rmtree(final_directory, ignore_errors=True)
        raise
    finally:
        if temp_directory.exists():
            shutil.rmtree(temp_directory, ignore_errors=True)
