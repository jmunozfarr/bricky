from __future__ import annotations

import re
import math
from collections import Counter
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
    official_part_ids: set[str],
    known_color_codes: set[int],
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

    declared_steps = 1 + sum(
        1 for line in main_lines if _STEP_DIRECTIVE.match(line.strip())
    )
    normalized_parts = {part_id.lower(): part_id for part_id in official_part_ids}
    quantities: Counter[tuple[str, int]] = Counter()
    issues: list[ParseIssue] = []
    issue_keys: set[tuple[str, str, str | None]] = set()

    def add_issue(code: str, message: str, filename: str | None = None) -> None:
        safe_filename = _safe_issue_filename(filename) if filename else None
        key = (code, message, safe_filename)
        if key not in issue_keys:
            issue_keys.add(key)
            issues.append(ParseIssue("warning", code, message, safe_filename))

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

    def traverse(section_key: str, parent_color: int | None, multiplier: int, stack: tuple[str, ...]) -> None:
        if section_key in stack:
            add_issue(
                "recursive_submodel_cycle",
                "Recursive MPD submodel cycle was stopped",
                sections[section_key].name,
            )
            return
        section = sections[section_key]
        reference_count = 0
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
            except (ValueError, OverflowError):
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
            color = effective_color(reference.color_code, parent_color, normalized_ref)

            if normalized_ref in sections:
                embedded = sections[normalized_ref]
                if embedded.name is not None and embedded.name.lower().endswith(".dat"):
                    add_issue(
                        "unsupported_custom_part",
                        "Embedded custom parts cannot be mapped to the official catalog",
                        embedded.name,
                    )
                    continue
                traverse(normalized_ref, color, multiplier, (*stack, section_key))
                continue

            path = PurePosixPath(normalized_ref)
            if path.parts and path.parts[0] in {"p", "s", "48", "8"}:
                continue
            if len(path.parts) >= 2 and path.parts[0:2] == ("parts", "s"):
                continue

            part_id = path.stem.lower()
            if part_id in normalized_parts:
                if color is None:
                    continue
                quantities[(normalized_parts[part_id], color)] += multiplier
                if color not in known_color_codes:
                    add_issue(
                        "unknown_color",
                        f"Color code {color} is not present in the indexed official colors",
                        normalized_ref,
                    )
            else:
                add_issue(
                    "unresolved_reference",
                    "Reference is not an embedded submodel or indexed official part",
                    normalized_ref,
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

    traverse(main_key, None, 1, ())
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
