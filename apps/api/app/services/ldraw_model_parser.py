from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import PurePosixPath


class ModelParseError(Exception):
    """Fatal source error that prevents a meaningful imported model."""


@dataclass(frozen=True, order=True)
class BomEntry:
    part_id: str
    color_code: int
    quantity: int


@dataclass(frozen=True)
class ParseIssue:
    severity: str
    code: str
    message: str
    referenced_filename: str | None = None
    occurrence_count: int = 1


@dataclass(frozen=True)
class ReferenceResolution:
    """A persisted user decision about one normalized source reference."""

    action: str
    part_id: str | None = None
    color_code: int | None = None


@dataclass(frozen=True)
class ParsedModel:
    bom: tuple[BomEntry, ...]
    issues: tuple[ParseIssue, ...]
    declared_step_count: int
    main_file_name: str | None
    encoding: str


@dataclass(frozen=True)
class _Section:
    name: str | None
    lines: tuple[str, ...]


@dataclass(frozen=True)
class _Reference:
    color_code: int
    filename: str


_FILE_DIRECTIVE = re.compile(r"^0\s+FILE\s+(.+?)\s*$", re.IGNORECASE)
_NOFILE_DIRECTIVE = re.compile(r"^0\s+NOFILE(?:\s|$)", re.IGNORECASE)
_STEP_DIRECTIVE = re.compile(r"^0\s+(?:STEP|ROTSTEP)(?:\s|$)", re.IGNORECASE)

# Instruction exports commonly inline flexible or printed parts as custom
# sections named "<set number> - <part id>.dat" or "<part id>_bended.dat".
_SET_WRAPPER_PREFIX = re.compile(r"^\d{3,7}\s*-\s*")
_BENT_STEM_SUFFIX = re.compile(r"[_-](?:bended|bent)$")

# LDCad writes flexible parts as path sections whose geometry is generated;
# they represent a real physical part that never reaches the BOM.
_LDCAD_GENERATED_META = re.compile(r"^0\s+!LDCAD\s+(?:GENERATED|PATH)", re.IGNORECASE)


def _has_generated_marker(section: _Section) -> bool:
    return any(_LDCAD_GENERATED_META.match(line.strip()) for line in section.lines)


def _auto_map_candidates(stem: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for base in (stem, _SET_WRAPPER_PREFIX.sub("", stem)):
        for candidate in (base, _BENT_STEM_SUFFIX.sub("", base)):
            cleaned = candidate.strip()
            if cleaned and cleaned not in candidates:
                candidates.append(cleaned)
    return tuple(candidates)


def decode_model_source(content: bytes) -> tuple[str, str]:
    if not content:
        raise ModelParseError("The uploaded model is empty")
    if b"\x00" in content:
        raise ModelParseError("The uploaded model contains binary null bytes")
    try:
        if content.startswith(b"\xef\xbb\xbf"):
            text = content.decode("utf-8-sig")
            encoding = "utf-8-sig"
        else:
            text = content.decode("utf-8")
            encoding = "utf-8"
    except UnicodeDecodeError:
        try:
            text = content.decode("cp1252")
            encoding = "cp1252"
        except UnicodeDecodeError as error:
            raise ModelParseError("The model text cannot be decoded") from error

    control_count = sum(
        1 for character in text if ord(character) < 32 and character not in "\r\n\t"
    )
    if control_count > max(2, len(text) // 100):
        raise ModelParseError("The uploaded model appears to contain binary content")
    return text, encoding


def _normalize_reference(filename: str) -> str | None:
    candidate = filename.strip().replace("\\", "/")
    path = PurePosixPath(candidate)
    if not candidate or path.is_absolute() or ".." in path.parts:
        return None
    parts = tuple(part for part in path.parts if part not in ("", "."))
    return PurePosixPath(*parts).as_posix().lower() if parts else None


def normalize_reference(filename: str) -> str | None:
    """Normalize a source reference exactly like parser lookups do."""
    return _normalize_reference(filename)


def _safe_issue_filename(filename: str) -> str:
    normalized = _normalize_reference(filename)
    if normalized is not None:
        return normalized[:255]
    return PurePosixPath(filename.replace("\\", "/")).name[:255] or "invalid-reference"


def _split_sections(text: str) -> tuple[dict[str, _Section], str, str | None]:
    lines = text.splitlines()
    if not any(_FILE_DIRECTIVE.match(line.strip()) for line in lines):
        return {"__main__": _Section(None, tuple(lines))}, "__main__", None

    sections: dict[str, _Section] = {}
    current_name: str | None = None
    current_key: str | None = None
    current_lines: list[str] = []
    main_key: str | None = None

    def store_current() -> None:
        if current_key is None or current_name is None:
            return
        if current_key in sections:
            raise ModelParseError(f"Duplicate MPD file section: {current_name}")
        sections[current_key] = _Section(current_name, tuple(current_lines))

    for line in lines:
        stripped = line.strip()
        file_match = _FILE_DIRECTIVE.match(stripped)
        if file_match:
            store_current()
            current_name = file_match.group(1).strip()
            current_key = _normalize_reference(current_name)
            if current_key is None:
                raise ModelParseError("MPD contains an unsafe or invalid FILE name")
            if main_key is None:
                main_key = current_key
            current_lines = []
            continue
        if _NOFILE_DIRECTIVE.match(stripped):
            store_current()
            current_name = None
            current_key = None
            current_lines = []
            continue
        if current_key is not None:
            current_lines.append(line)
    store_current()

    if main_key is None or main_key not in sections:
        raise ModelParseError("MPD does not contain a usable main FILE section")
    return sections, main_key, sections[main_key].name


def _parse_reference(line: str) -> _Reference:
    tokens = line.split()
    if len(tokens) < 15:
        raise ValueError("type-1 line requires color, 12 numeric fields, and a filename")
    if tokens[0] != "1":
        raise ValueError("not a type-1 line")
    color_code = int(tokens[1])
    for token in tokens[2:14]:
        if not math.isfinite(float(token)):
            raise ValueError("type-1 numeric fields must be finite")
    filename = " ".join(tokens[14:]).strip()
    if not filename:
        raise ValueError("type-1 filename is missing")
    return _Reference(color_code=color_code, filename=filename)


def parse_ldraw_model(
    content: bytes,
    *,
    official_part_ids: AbstractSet[str],
    known_color_codes: AbstractSet[int],
    known_primitive_names: AbstractSet[str] = frozenset(),
    reference_resolutions: Mapping[str, ReferenceResolution] | None = None,
) -> ParsedModel:
    text, encoding = decode_model_source(content)
    sections, main_key, main_name = _split_sections(text)
    main_lines = sections[main_key].lines
    meaningful = any(
        line.strip().split(maxsplit=1)[0] in {"1", "2", "3", "4", "5"}
        for line in main_lines
        if line.strip()
    )
    if not meaningful:
        raise ModelParseError("The main model section contains no references or geometry")

    declared_steps = 1 + sum(1 for line in main_lines if _STEP_DIRECTIVE.match(line.strip()))
    normalized_parts = {part_id.lower(): part_id for part_id in official_part_ids}
    resolutions = reference_resolutions or {}
    quantities: Counter[tuple[str, int]] = Counter()
    issues: list[ParseIssue] = []
    issue_index: dict[tuple[str, str, str | None], int] = {}
    section_yield: Counter[str] = Counter()
    submodel_edges: Counter[tuple[str, str]] = Counter()

    def add_issue(
        code: str,
        message: str,
        filename: str | None = None,
        count: int = 1,
        severity: str = "warning",
    ) -> None:
        safe_filename = _safe_issue_filename(filename) if filename else None
        key = (code, message, safe_filename)
        existing = issue_index.get(key)
        if existing is None:
            issue_index[key] = len(issues)
            issues.append(ParseIssue(severity, code, message, safe_filename, count))
        else:
            current = issues[existing]
            issues[existing] = ParseIssue(
                current.severity,
                current.code,
                current.message,
                current.referenced_filename,
                current.occurrence_count + count,
            )

    def effective_color(color_code: int, parent_color: int | None, filename: str) -> int | None:
        if color_code == 16:
            if parent_color is None:
                add_issue(
                    "undetermined_color",
                    "Color 16 cannot inherit a physical color at this level",
                    filename,
                )
            return parent_color
        if color_code == 24:
            add_issue(
                "edge_color_not_physical",
                "Color 24 is an edge color and was excluded from the physical BOM",
                filename,
            )
            return None
        return color_code

    def submodel_child_color(
        color_code: int, parent_color: int | None, filename: str
    ) -> int | None:
        # Color 16 on a submodel reference is the standard "no override" idiom;
        # only leaf part references can leave a physical part without a color.
        if color_code == 16:
            return parent_color
        if color_code == 24:
            add_issue(
                "edge_color_not_physical",
                "Color 24 is an edge color and was excluded from the physical BOM",
                filename,
            )
            return None
        return color_code

    def count_physical_part(
        official_part_id: str,
        color_code: int,
        parent_color: int | None,
        reference_name: str,
        multiplier: int,
    ) -> bool:
        color = effective_color(color_code, parent_color, reference_name)
        if color is None:
            return False
        quantities[(official_part_id, color)] += multiplier
        if color not in known_color_codes:
            add_issue(
                "unknown_color",
                f"Color code {color} is not present in the indexed official colors",
                reference_name,
                count=multiplier,
            )
        return True

    def auto_mapped_part(stem: str) -> str | None:
        for candidate in _auto_map_candidates(stem):
            match = normalized_parts.get(candidate)
            if match is not None:
                return match
        return None

    def traverse(
        section_key: str, parent_color: int | None, multiplier: int, stack: tuple[str, ...]
    ) -> int:
        if section_key in stack:
            add_issue(
                "recursive_submodel_cycle",
                "Recursive MPD submodel cycle was stopped",
                sections[section_key].name,
            )
            return 0
        section = sections[section_key]
        reference_count = 0
        contributed = 0
        for line in section.lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("0"):
                continue
            line_type = stripped.split(maxsplit=1)[0]
            if line_type != "1":
                continue
            reference_count += 1
            try:
                reference = _parse_reference(stripped)
            except ValueError, OverflowError:
                add_issue(
                    "malformed_type1_reference",
                    "Malformed type-1 reference was ignored",
                )
                continue

            normalized_ref = _normalize_reference(reference.filename)
            if normalized_ref is None:
                add_issue(
                    "unresolved_reference",
                    "Unsafe or invalid external reference could not be resolved",
                    reference.filename,
                )
                continue

            resolution = resolutions.get(normalized_ref)
            if resolution is not None and resolution.action == "ignore":
                add_issue(
                    "reference_ignored",
                    "Excluded from the physical BOM by a manual resolution",
                    normalized_ref,
                    count=multiplier,
                    severity="info",
                )
                continue
            if resolution is not None and resolution.action == "map" and resolution.part_id:
                resolved_color = (
                    resolution.color_code
                    if resolution.color_code is not None
                    else reference.color_code
                )
                if count_physical_part(
                    resolution.part_id, resolved_color, parent_color, normalized_ref, multiplier
                ):
                    contributed += multiplier
                    add_issue(
                        "reference_manually_mapped",
                        f"Mapped to official part '{resolution.part_id}' by a manual resolution",
                        normalized_ref,
                        count=multiplier,
                        severity="info",
                    )
                continue

            if normalized_ref in sections:
                embedded = sections[normalized_ref]
                if embedded.name is not None and embedded.name.lower().endswith(".dat"):
                    mapped = auto_mapped_part(PurePosixPath(normalized_ref).stem)
                    if mapped is None:
                        add_issue(
                            "unsupported_custom_part",
                            "Embedded custom parts cannot be mapped to the official catalog",
                            embedded.name,
                            count=multiplier,
                        )
                    elif count_physical_part(
                        mapped, reference.color_code, parent_color, normalized_ref, multiplier
                    ):
                        contributed += multiplier
                        add_issue(
                            "custom_part_auto_mapped",
                            f"Automatically mapped to official part '{mapped}'",
                            embedded.name,
                            count=multiplier,
                            severity="info",
                        )
                    continue
                child_yield = traverse(
                    normalized_ref,
                    submodel_child_color(reference.color_code, parent_color, normalized_ref),
                    multiplier,
                    (*stack, section_key),
                )
                contributed += child_yield
                section_yield[normalized_ref] += child_yield
                submodel_edges[(section_key, normalized_ref)] += multiplier
                continue

            path = PurePosixPath(normalized_ref)
            if path.parts and path.parts[0] in {"p", "s", "48", "8"}:
                continue
            if len(path.parts) >= 2 and path.parts[0:2] == ("parts", "s"):
                continue

            part_id = path.stem.lower()
            official_part_id = normalized_parts.get(part_id)
            auto_mapped = False
            if official_part_id is None:
                if normalized_ref in known_primitive_names:
                    continue
                official_part_id = auto_mapped_part(part_id)
                auto_mapped = official_part_id is not None
            if official_part_id is None:
                add_issue(
                    "unresolved_reference",
                    "Reference is not an embedded submodel or indexed official part",
                    normalized_ref,
                    count=multiplier,
                )
                continue

            counted = count_physical_part(
                official_part_id, reference.color_code, parent_color, normalized_ref, multiplier
            )
            if counted:
                contributed += multiplier
            if auto_mapped and counted:
                add_issue(
                    "custom_part_auto_mapped",
                    f"Automatically mapped to official part '{official_part_id}'",
                    normalized_ref,
                    count=multiplier,
                    severity="info",
                )

        if (
            section_key != main_key
            and section.name is not None
            and section.name.lower().endswith(".dat")
            and reference_count == 0
        ):
            add_issue(
                "unsupported_custom_part",
                "Embedded custom part has no official catalog mapping",
                section.name,
            )
        return contributed

    traverse(main_key, None, 1, ())

    zero_yield_generated = {
        key
        for key, total in section_yield.items()
        if total == 0 and _has_generated_marker(sections[key])
    }
    for (parent_key, child_key), count in sorted(submodel_edges.items()):
        if child_key in zero_yield_generated and parent_key not in zero_yield_generated:
            add_issue(
                "generated_section_without_parts",
                "LDCad-generated section contributes no physical parts; "
                "map it to a physical part or ignore it",
                sections[child_key].name,
                count=count,
            )
    bom = tuple(
        BomEntry(part_id=part_id, color_code=color, quantity=quantity)
        for (part_id, color), quantity in sorted(quantities.items())
    )
    return ParsedModel(
        bom=bom,
        issues=tuple(issues),
        declared_step_count=declared_steps,
        main_file_name=main_name,
        encoding=encoding,
    )
