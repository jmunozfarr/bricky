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

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    ImportedModel,
    LDrawColor,
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
            part_records = [
                OfficialPartRecord(
                    part_id=part_id,
                    description=description,
                    relative_path=relative_path,
                )
                for part_id, description, relative_path in session.execute(
                    select(Part.part_id, Part.name, Part.relative_path).where(
                        Part.is_subpart.is_(False)
                    )
                )
            ]
            official_parts = {part.part_id for part in part_records}
            known_colors = set(session.scalars(select(LDrawColor.code)))

        source_bytes = temp_source.read_bytes()
        try:
            parsed = parse_ldraw_model(
                source_bytes,
                official_part_ids=official_parts,
                known_color_codes=known_colors,
            )
            parsed = _canonicalize_moved_aliases(
                parsed,
                LDrawMovedAliasResolver(library_root, part_records),
            )
        except ModelParseError as error:
            raise ModelImportError(str(error)) from error

        public_id = uuid.uuid4()
        final_directory = storage_root / "originals" / str(public_id)
        final_directory.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp_directory, final_directory)
        relative_storage_path = (
            PurePosixPath("originals") / str(public_id) / safe_filename
        ).as_posix()

        unresolved_codes = {
            "unresolved_reference",
            "unsupported_custom_part",
            "malformed_type1_reference",
            "moved_alias_cycle",
            "moved_alias_missing_target",
            "moved_alias_malformed",
            "moved_alias_depth_exceeded",
        }
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
                    import_status="ready_with_warnings" if parsed.issues else "ready",
                    declared_step_count=parsed.declared_step_count,
                    total_part_quantity=sum(item.quantity for item in parsed.bom),
                    unique_part_color_count=len(parsed.bom),
                    unresolved_reference_count=sum(
                        1 for issue in parsed.issues if issue.code in unresolved_codes
                    ),
                )
                session.add(model)
                session.flush()
                session.add_all(
                    ModelBomItem(
                        model_id=model.id,
                        part_id=item.part_id,
                        color_code=item.color_code,
                        quantity=item.quantity,
                    )
                    for item in parsed.bom
                )
                session.add_all(
                    ModelImportIssue(
                        model_id=model.id,
                        severity=issue.severity,
                        code=issue.code,
                        message=issue.message,
                        referenced_filename=issue.referenced_filename,
                    )
                    for issue in parsed.issues
                )
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
