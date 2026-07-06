from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DEFAULT_MAX_PACKED_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_PACKED_FILES = 5_000
DEFAULT_PACK_CACHE_BYTES = 64 * 1024 * 1024


class LDrawPackError(Exception):
    pass


class LDrawPackLimitError(LDrawPackError):
    pass


@dataclass(frozen=True)
class PackedLDrawSource:
    content: bytes
    file_count: int


class PackedSourceCache:
    """LRU of packed scenes, safe for FastAPI's threadpool handlers."""

    def __init__(self, maximum_bytes: int = DEFAULT_PACK_CACHE_BYTES) -> None:
        self.maximum_bytes = maximum_bytes
        self._lock = threading.Lock()
        self._values: OrderedDict[str, PackedLDrawSource] = OrderedDict()
        self._groups: dict[str, str] = {}
        self._size = 0

    def get(self, key: str) -> PackedLDrawSource | None:
        with self._lock:
            value = self._values.pop(key, None)
            if value is None:
                return None
            self._values[key] = value
            return value

    def set(self, key: str, value: PackedLDrawSource, group: str | None = None) -> None:
        with self._lock:
            replaced = self._values.pop(key, None)
            if replaced is not None:
                self._size -= len(replaced.content)
            self._values[key] = value
            self._size += len(value.content)
            if group is None:
                self._groups.pop(key, None)
            else:
                self._groups[key] = group
            while self._size > self.maximum_bytes and self._values:
                old_key, old_value = self._values.popitem(last=False)
                self._groups.pop(old_key, None)
                self._size -= len(old_value.content)

    def evict_group(self, group: str) -> None:
        """Drop every scene packed for one model (e.g. on model deletion)."""

        with self._lock:
            for key in [key for key, owner in self._groups.items() if owner == group]:
                value = self._values.pop(key, None)
                del self._groups[key]
                if value is not None:
                    self._size -= len(value.content)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._groups.clear()
            self._size = 0


PACKED_SOURCE_CACHE = PackedSourceCache()


def _normalized(value: str) -> str | None:
    path = PurePosixPath(value.strip().replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return None
    return PurePosixPath(*(part.lower() for part in path.parts)).as_posix()


def _type_one_reference(line: str) -> str | None:
    tokens = line.strip().split(maxsplit=14)
    return tokens[14] if len(tokens) == 15 and tokens[0] == "1" else None


_LIBRARY_INDEX_LOCK = threading.Lock()
_LIBRARY_INDEX: dict[tuple[str, str], dict[str, Path]] = {}


def _scan_library(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix().lower(): path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".dat", ".ldr"}
    }


def _library_index(root: Path) -> dict[str, Path]:
    """File index cached per (root, library fingerprint).

    Scanning the installed library is tens of thousands of stat calls; a
    reinstall changes the manifest fingerprint, which retires stale entries.
    A manifest-less root is keyed by path only, so mutating such a library
    in place without reinstalling keeps the old index — an unsupported
    state, since installs always write the manifest.
    """

    from app.services.ldraw_library import get_library_status

    fingerprint = get_library_status(root).archive_sha256 or "unversioned-library"
    key = (str(root), fingerprint)
    with _LIBRARY_INDEX_LOCK:
        cached = _LIBRARY_INDEX.get(key)
        if cached is not None:
            return cached
    paths = _scan_library(root)
    with _LIBRARY_INDEX_LOCK:
        for stale in [existing for existing in _LIBRARY_INDEX if existing[0] == key[0]]:
            del _LIBRARY_INDEX[stale]
        _LIBRARY_INDEX[key] = paths
    return paths


def clear_library_index() -> None:
    with _LIBRARY_INDEX_LOCK:
        _LIBRARY_INDEX.clear()


class _LibraryResolver:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.paths = _library_index(self.root)

    def resolve(self, reference: str, current_path: str | None) -> str | None:
        normalized = _normalized(reference)
        if normalized is None:
            return None
        candidates: list[str] = []
        if normalized.startswith("s/"):
            candidates.append(f"parts/{normalized}")
        elif normalized.startswith("48/"):
            candidates.append(f"p/{normalized}")
        if current_path is not None:
            parent = PurePosixPath(current_path).parent
            candidates.append((parent / normalized).as_posix())
        candidates.extend(
            [normalized, f"parts/{normalized}", f"p/{normalized}", f"models/{normalized}"]
        )
        for candidate in candidates:
            if candidate.lower() in self.paths:
                return candidate.lower()
        return None

    def read(self, canonical_path: str) -> str:
        path = self.paths[canonical_path]
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise LDrawPackError("Library dependency escaped the installed root")
        return path.read_text(encoding="utf-8", errors="replace")


def _embedded_names(source: str) -> set[str]:
    return {
        normalized
        for line in source.splitlines()
        if line.startswith("0 FILE ") and (normalized := _normalized(line[7:])) is not None
    }


def pack_ldraw_source(
    source: bytes,
    library_root: Path,
    *,
    maximum_bytes: int = DEFAULT_MAX_PACKED_BYTES,
    maximum_files: int = DEFAULT_MAX_PACKED_FILES,
) -> PackedLDrawSource:
    text = source.decode("utf-8")
    resolver = _LibraryResolver(library_root)
    embedded = _embedded_names(text)
    dependencies: OrderedDict[str, str] = OrderedDict()

    def rewrite(content: str, current_path: str | None) -> str:
        rewritten: list[str] = []
        active_path = current_path
        for line in content.splitlines():
            if current_path is None and line.startswith("0 FILE "):
                active_path = _normalized(line[7:])
                rewritten.append(line)
                continue
            reference = _type_one_reference(line)
            if reference is None:
                rewritten.append(line)
                continue
            normalized_reference = _normalized(reference)
            if normalized_reference in embedded:
                rewritten.append(line)
                continue
            canonical = resolver.resolve(reference, active_path)
            if canonical is None:
                raise LDrawPackError(f"Library dependency is unavailable: {reference}")
            tokens = line.strip().split(maxsplit=14)
            tokens[14] = canonical
            rewritten.append(" ".join(tokens))
            if canonical not in dependencies:
                if len(dependencies) >= maximum_files:
                    raise LDrawPackLimitError("Packed scene dependency file limit exceeded")
                dependencies[canonical] = ""
        return "\n".join(rewritten) + "\n"

    rewritten_root = rewrite(text, None)
    index = 0
    while index < len(dependencies):
        canonical = list(dependencies)[index]
        dependencies[canonical] = rewrite(resolver.read(canonical), canonical)
        index += 1

    color_lines: list[str] = []
    config_path = library_root / "LDConfig.ldr"
    if config_path.is_file():
        color_lines = [
            line
            for line in config_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("0 !COLOUR ")
        ]
    chunks = ["0 !BRICKY PACKED_SOURCE 1\n", *(f"{line}\n" for line in color_lines), rewritten_root]
    for canonical, content in dependencies.items():
        chunks.extend((f"0 FILE {canonical}\n", content))
    packed = "".join(chunks).encode("utf-8")
    if len(packed) > maximum_bytes:
        raise LDrawPackLimitError("Packed scene byte limit exceeded")
    return PackedLDrawSource(content=packed, file_count=len(dependencies))
