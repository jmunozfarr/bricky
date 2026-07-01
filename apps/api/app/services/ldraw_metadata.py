from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class PartHeader:
    part_id: str
    description: str
    relative_path: str
    author: str | None
    category: str
    org_classification: str | None
    license: str | None
    keywords: tuple[str, ...]
    is_subpart: bool
    is_shortcut: bool


@dataclass(frozen=True)
class ColorDefinition:
    code: int
    name: str
    value_hex: str
    edge_hex: str | None
    alpha: int
    luminance: int | None
    finish: str | None


def decode_ldraw_text(content: bytes) -> str:
    """Decode upstream text as UTF-8 and replace malformed byte sequences safely."""

    return content.decode("utf-8", errors="replace")


def normalize_relative_path(relative_path: str) -> str:
    normalized = PurePosixPath(relative_path.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError("LDraw source path must remain inside the library")
    return normalized.as_posix()


def _fallback_category(description: str) -> str:
    cleaned = description.lstrip("~=_ ").strip()
    if not cleaned:
        return "Other"
    first_word = re.split(r"[\s,/-]+", cleaned, maxsplit=1)[0]
    return first_word[:128].title()


def parse_part_header(content: bytes, relative_path: str) -> PartHeader:
    normalized_path = normalize_relative_path(relative_path)
    path = PurePosixPath(normalized_path)
    description = ""
    author: str | None = None
    category: str | None = None
    org_classification: str | None = None
    license_text: str | None = None
    keywords: list[str] = []

    for raw_line in decode_ldraw_text(content).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line_type = line.split(maxsplit=1)[0]
        if line_type in {"1", "2", "3", "4", "5"}:
            break
        if line_type != "0":
            continue

        body = line[1:].strip()
        if body.startswith("Name:"):
            continue
        if body.startswith("Author:"):
            author = body.removeprefix("Author:").strip() or None
        elif body.startswith("!LDRAW_ORG"):
            org_classification = body.removeprefix("!LDRAW_ORG").strip() or None
        elif body.startswith("!LICENSE"):
            license_text = body.removeprefix("!LICENSE").strip() or None
        elif body.startswith("!CATEGORY"):
            category = body.removeprefix("!CATEGORY").strip() or None
        elif body.startswith("!KEYWORDS"):
            values = body.removeprefix("!KEYWORDS").strip()
            keywords.extend(item.strip() for item in values.split(",") if item.strip())
        elif not description and body and not body.startswith(("!", "BFC", "//")):
            description = body

    part_id = path.stem.lower()
    is_subpart = len(path.parts) >= 3 and path.parts[0:2] == ("parts", "s")
    classification = (org_classification or "").lower()
    is_shortcut = (
        "shortcut" in classification
        or "alias" in classification
        or description.lower().startswith(("~moved", "~alias"))
    )
    display_name = description or part_id
    return PartHeader(
        part_id=part_id,
        description=display_name,
        relative_path=normalized_path,
        author=author,
        category=category or _fallback_category(display_name),
        org_classification=org_classification,
        license=license_text,
        keywords=tuple(keywords),
        is_subpart=is_subpart,
        is_shortcut=is_shortcut,
    )


_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_FINISHES = {"CHROME", "PEARLESCENT", "RUBBER", "MATTE_METALLIC", "METAL"}


def parse_color_config(content: bytes) -> list[ColorDefinition]:
    colors: list[ColorDefinition] = []
    for raw_line in decode_ldraw_text(content).splitlines():
        line = raw_line.strip()
        if not line.startswith("0 !COLOUR "):
            continue
        try:
            tokens = shlex.split(line.removeprefix("0 !COLOUR "))
            name = tokens[0].replace("_", " ")
            code = int(tokens[tokens.index("CODE") + 1])
            value_hex = tokens[tokens.index("VALUE") + 1].upper()
            edge_value = tokens[tokens.index("EDGE") + 1].upper()
            if not _HEX_COLOR.fullmatch(value_hex):
                continue
            edge_hex = edge_value if _HEX_COLOR.fullmatch(edge_value) else None
            alpha = int(tokens[tokens.index("ALPHA") + 1]) if "ALPHA" in tokens else 255
            luminance = (
                int(tokens[tokens.index("LUMINANCE") + 1]) if "LUMINANCE" in tokens else None
            )
            finish = next((token for token in tokens if token in _FINISHES), None)
            if "MATERIAL" in tokens:
                material_index = tokens.index("MATERIAL")
                if material_index + 1 < len(tokens):
                    finish = tokens[material_index + 1]
            colors.append(
                ColorDefinition(
                    code=code,
                    name=name,
                    value_hex=value_hex,
                    edge_hex=edge_hex,
                    alpha=max(0, min(alpha, 255)),
                    luminance=luminance,
                    finish=finish,
                )
            )
        except (ValueError, IndexError):
            continue
    return colors
