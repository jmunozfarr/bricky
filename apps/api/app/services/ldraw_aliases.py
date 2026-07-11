from __future__ import annotations

import math
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from app.services.ldraw_metadata import decode_ldraw_text, parse_part_header

AliasResolutionStatus = Literal[
    "unchanged",
    "resolved",
    "cycle",
    "missing_target",
    "malformed",
    "depth_exceeded",
]


@dataclass(frozen=True)
class OfficialPartRecord:
    part_id: str
    description: str
    relative_path: str


@dataclass(frozen=True)
class AliasInspection:
    part_id: str
    is_moved_alias: bool
    immediate_target: str | None
    malformed: bool


@dataclass(frozen=True)
class AliasResolution:
    original_part_id: str
    canonical_part_id: str
    is_moved_alias: bool
    immediate_target: str | None
    status: AliasResolutionStatus
    alias_chain: tuple[str, ...]


_MOVED_PREFIX = re.compile(r"^~Moved\s+to(?:\s|$)", re.IGNORECASE)
_MOVED_DESCRIPTION = re.compile(r"^~Moved\s+to\s+(\S+)\s*$", re.IGNORECASE)
_SAFE_PART_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def normalize_part_id(part_id: str) -> str | None:
    candidate = part_id.strip()
    if not _SAFE_PART_ID.fullmatch(candidate):
        return None
    return candidate.lower()


def _normalize_target(target: str, *, require_dat_suffix: bool) -> str | None:
    candidate = target.strip().replace("\\", "/")
    path = PurePosixPath(candidate)
    if path.is_absolute() or ".." in path.parts or len(path.parts) not in {1, 2}:
        return None
    if len(path.parts) == 2 and path.parts[0].lower() != "s":
        return None
    if require_dat_suffix:
        if path.suffix.lower() != ".dat":
            return None
        path = path.with_suffix("")
    elif path.suffix:
        return None
    if any(_SAFE_PART_ID.fullmatch(part) is None for part in path.parts):
        return None
    return PurePosixPath(*(part.lower() for part in path.parts)).as_posix()


class LDrawMovedAliasResolver:
    """Resolve validated official LDraw moved aliases within one library root."""

    def __init__(
        self,
        library_root: Path,
        parts: Iterable[OfficialPartRecord],
        *,
        maximum_depth: int = 16,
    ) -> None:
        if maximum_depth < 1:
            raise ValueError("Maximum alias depth must be positive")
        self._library_root = library_root.resolve()
        self._maximum_depth = maximum_depth
        self._parts = {
            normalized: part
            for part in parts
            if (normalized := normalize_part_id(part.part_id)) is not None
        }
        self._inspection_cache: dict[str, AliasInspection] = {}
        self._resolution_cache: dict[str, AliasResolution] = {}

    def inspect(self, part_id: str) -> AliasInspection:
        normalized = normalize_part_id(part_id)
        if normalized is None:
            return AliasInspection(part_id, False, None, False)
        cached = self._inspection_cache.get(normalized)
        if cached is not None:
            return cached
        record = self._parts.get(normalized)
        if record is None or _MOVED_PREFIX.match(record.description) is None:
            inspection = AliasInspection(
                record.part_id if record is not None else part_id,
                False,
                None,
                False,
            )
        else:
            inspection = self._inspect_moved_record(normalized, record)
        self._inspection_cache[normalized] = inspection
        return inspection

    def resolve(self, part_id: str) -> AliasResolution:
        normalized = normalize_part_id(part_id)
        if normalized is None:
            return AliasResolution(part_id, part_id, False, None, "unchanged", ())
        cached = self._resolution_cache.get(normalized)
        if cached is not None:
            return cached

        original_record = self._parts.get(normalized)
        original_id = original_record.part_id if original_record is not None else part_id
        current = normalized
        chain: list[str] = []
        immediate_target: str | None = None
        is_alias = False

        for _depth in range(self._maximum_depth):
            if current in chain:
                return self._cache_resolution(
                    normalized,
                    AliasResolution(
                        original_id,
                        original_id,
                        is_alias,
                        immediate_target,
                        "cycle",
                        (*chain, current),
                    ),
                )
            inspection = self.inspect(current)
            if inspection.malformed:
                return self._cache_resolution(
                    normalized,
                    AliasResolution(
                        original_id,
                        original_id,
                        True,
                        immediate_target,
                        "malformed",
                        (*chain, current),
                    ),
                )
            if not inspection.is_moved_alias:
                canonical_record = self._parts.get(current)
                canonical_id = (
                    canonical_record.part_id if canonical_record is not None else original_id
                )
                status: AliasResolutionStatus = "resolved" if is_alias else "unchanged"
                return self._cache_resolution(
                    normalized,
                    AliasResolution(
                        original_id,
                        canonical_id,
                        is_alias,
                        immediate_target,
                        status,
                        tuple(chain),
                    ),
                )

            is_alias = True
            target = inspection.immediate_target
            if immediate_target is None:
                immediate_target = target
            chain.append(current)
            if target is None or not self._target_exists(target):
                return self._cache_resolution(
                    normalized,
                    AliasResolution(
                        original_id,
                        original_id,
                        True,
                        immediate_target,
                        "missing_target",
                        tuple(chain),
                    ),
                )
            current = target

        return self._cache_resolution(
            normalized,
            AliasResolution(
                original_id,
                original_id,
                is_alias,
                immediate_target,
                "depth_exceeded",
                tuple(chain),
            ),
        )

    def resolve_many(self, part_ids: set[str]) -> dict[str, AliasResolution]:
        return {part_id: self.resolve(part_id) for part_id in sorted(part_ids, key=str.lower)}

    def _inspect_moved_record(
        self, normalized_id: str, record: OfficialPartRecord
    ) -> AliasInspection:
        source_path = self._safe_source_path(record)
        if source_path is None:
            return AliasInspection(record.part_id, True, None, True)
        try:
            content = source_path.read_bytes()
            header = parse_part_header(content, record.relative_path)
        except OSError, ValueError:
            return AliasInspection(record.part_id, True, None, True)

        catalog_match = _MOVED_DESCRIPTION.fullmatch(record.description)
        source_match = _MOVED_DESCRIPTION.fullmatch(header.description)
        if catalog_match is None or source_match is None:
            return AliasInspection(record.part_id, True, None, True)
        catalog_target = _normalize_target(catalog_match.group(1), require_dat_suffix=False)
        source_target = _normalize_target(source_match.group(1), require_dat_suffix=False)
        reference_target = self._validated_target_reference(content)
        if (
            catalog_target is None
            or source_target is None
            or reference_target is None
            or catalog_target != source_target
            or source_target != reference_target
            or normalize_part_id(header.part_id) != normalized_id
        ):
            return AliasInspection(record.part_id, True, None, True)
        return AliasInspection(record.part_id, True, source_target, False)

    def _validated_target_reference(self, content: bytes) -> str | None:
        geometry: list[str] = []
        for raw_line in decode_ldraw_text(content).splitlines():
            line = raw_line.strip()
            if line and line.split(maxsplit=1)[0] in {"1", "2", "3", "4", "5"}:
                geometry.append(line)
        if len(geometry) != 1:
            return None
        tokens = geometry[0].split()
        if len(tokens) != 15 or tokens[0] != "1":
            return None
        try:
            int(tokens[1])
            transform = tuple(float(token) for token in tokens[2:14])
        except ValueError:
            return None
        if not all(math.isfinite(value) for value in transform):
            return None
        return _normalize_target(tokens[14], require_dat_suffix=True)

    def _safe_source_path(self, record: OfficialPartRecord) -> Path | None:
        relative = PurePosixPath(record.relative_path.replace("\\", "/"))
        expected_id = normalize_part_id(record.part_id)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or len(relative.parts) != 2
            or relative.parts[0].lower() != "parts"
            or relative.suffix.lower() != ".dat"
            or normalize_part_id(relative.stem) != expected_id
        ):
            return None
        candidate = (self._library_root / Path(*relative.parts)).resolve()
        if not candidate.is_relative_to(self._library_root):
            return None
        return candidate

    def _target_exists(self, target: str) -> bool:
        record = self._parts.get(target)
        if record is None:
            return False
        path = self._safe_source_path(record)
        return path is not None and path.is_file()

    def _cache_resolution(self, normalized_id: str, resolution: AliasResolution) -> AliasResolution:
        self._resolution_cache[normalized_id] = resolution
        return resolution


_RESOLVER_CACHE_LOCK = threading.Lock()
_RESOLVER_CACHE: dict[tuple[str, str], LDrawMovedAliasResolver] = {}


def cached_moved_alias_resolver(
    library_root: Path,
    library_fingerprint: str,
    load_parts: Callable[[], list[OfficialPartRecord]],
) -> LDrawMovedAliasResolver:
    """Reuse one resolver per (root, library fingerprint).

    Building a resolver requires the full official part list; caching it also
    preserves its internal inspection/resolution caches across requests. A
    reinstall or catalog rebuild changes the fingerprint and retires stale
    entries.
    """

    key = (str(library_root.resolve()), library_fingerprint)
    with _RESOLVER_CACHE_LOCK:
        cached = _RESOLVER_CACHE.get(key)
        if cached is not None:
            return cached
    resolver = LDrawMovedAliasResolver(library_root, load_parts())
    with _RESOLVER_CACHE_LOCK:
        for stale in [existing for existing in _RESOLVER_CACHE if existing[0] == key[0]]:
            del _RESOLVER_CACHE[stale]
        _RESOLVER_CACHE[key] = resolver
    return resolver


def clear_alias_resolver_cache() -> None:
    with _RESOLVER_CACHE_LOCK:
        _RESOLVER_CACHE.clear()
