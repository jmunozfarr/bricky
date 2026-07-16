from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session, sessionmaker

from app.models import ExternalColorMap, ExternalIdMapState, ExternalPartIdMap

DEFAULT_API_BASE = "https://rebrickable.com/api/v3/lego"
FETCHER_VERSION = "1"

# Rebrickable allows ~1 request/sec with small bursts; this throttle keeps a
# full parts paginated fetch (~65 requests) from ever approaching 429 as the
# steady state.
_MIN_REQUEST_INTERVAL_SECONDS = 1.1
_MAX_RETRY_ATTEMPTS = 5
_BACKOFF_INITIAL_SECONDS = 2.0
_BACKOFF_CAP_SECONDS = 60.0
_REQUEST_TIMEOUT_SECONDS = 30

SleepFn = Callable[[float], None]


class RebrickableMappingError(Exception):
    """Raised when the mapping populate run cannot complete safely."""


class RebrickableApiError(RebrickableMappingError):
    """Raised when the Rebrickable API request ultimately fails."""


@dataclass(frozen=True)
class PartMappingRow:
    source_system: str
    source_part_id: str
    ldraw_part_id: str
    is_preferred: bool


@dataclass(frozen=True)
class ColorMappingRow:
    source_system: str
    source_color_id: int
    ldraw_color_code: int


@dataclass(frozen=True)
class PopulateReport:
    fetched_color_count: int
    fetched_part_count: int
    part_mapping_count: int
    color_mapping_count: int
    ambiguous_part_count: int
    color_collision_count: int
    duration_seconds: float


@dataclass(frozen=True)
class MappingStatus:
    populated: bool
    populated_at: datetime | None
    part_mapping_count: int
    color_mapping_count: int
    ambiguous_part_count: int
    fetcher_version: str | None


def _fetch_json(
    url: str, api_key: str, *, sleep: SleepFn, timeout: int = _REQUEST_TIMEOUT_SECONDS
) -> dict[str, Any]:
    """One throttled, retried GET. Retries on 429 (honoring Retry-After) and
    5xx with capped exponential backoff; any other failure aborts immediately
    so a one-shot operator run fails loudly rather than limping."""
    backoff = _BACKOFF_INITIAL_SECONDS
    for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"key {api_key}",
                "User-Agent": "Bricky Rebrickable mapping CLI",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload: object = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt == _MAX_RETRY_ATTEMPTS:
                raise RebrickableApiError(
                    f"Rebrickable API request failed ({error.code}): {url}"
                ) from error
            retry_after = error.headers.get("Retry-After") if error.headers else None
            delay = float(retry_after) if retry_after and retry_after.isdigit() else backoff
            sleep(min(delay, _BACKOFF_CAP_SECONDS))
            backoff = min(backoff * 2, _BACKOFF_CAP_SECONDS)
            continue
        except (OSError, json.JSONDecodeError) as error:
            if attempt == _MAX_RETRY_ATTEMPTS:
                raise RebrickableApiError(
                    f"Unable to reach the Rebrickable API: {error}"
                ) from error
            sleep(min(backoff, _BACKOFF_CAP_SECONDS))
            backoff = min(backoff * 2, _BACKOFF_CAP_SECONDS)
            continue
        if not isinstance(payload, dict):
            raise RebrickableApiError(f"Unexpected Rebrickable API response shape: {url}")
        return payload
    raise RebrickableApiError(f"Rebrickable API request exhausted retries: {url}")


def fetch_colors(
    api_key: str, *, base_url: str = DEFAULT_API_BASE, sleep: SleepFn = time.sleep
) -> list[dict[str, Any]]:
    payload = _fetch_json(f"{base_url}/colors/?page_size=1000", api_key, sleep=sleep)
    results = payload.get("results")
    return list(results) if isinstance(results, list) else []


def fetch_parts(
    api_key: str, *, base_url: str = DEFAULT_API_BASE, sleep: SleepFn = time.sleep
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    url: str | None = f"{base_url}/parts/?page_size=1000"
    first = True
    while url is not None:
        if not first:
            sleep(_MIN_REQUEST_INTERVAL_SECONDS)
        first = False
        payload = _fetch_json(url, api_key, sleep=sleep)
        page_results = payload.get("results")
        if isinstance(page_results, list):
            results.extend(page_results)
        next_url = payload.get("next")
        url = next_url if isinstance(next_url, str) else None
    return results


def build_color_mappings(
    colors_json: Iterable[dict[str, Any]],
) -> tuple[tuple[ColorMappingRow, ...], int]:
    """Pure transform: colors' external_ids -> one LDraw code per source ID.

    Colors are low-cardinality (~250); force one-to-one, lowest LDraw code
    on ties, and report how many source IDs collided.
    """
    candidates: dict[tuple[str, int], list[int]] = {}
    for color in colors_json:
        rb_id = color.get("id")
        if not isinstance(rb_id, int):
            continue
        external = color.get("external_ids")
        external = external if isinstance(external, dict) else {}
        ldraw_entry = external.get("LDraw")
        ldraw_ids = _int_ext_ids(ldraw_entry)
        if not ldraw_ids:
            continue
        candidates.setdefault(("rebrickable", rb_id), []).extend(ldraw_ids)
        bricklink_entry = external.get("BrickLink")
        for bricklink_id in _int_ext_ids(bricklink_entry):
            candidates.setdefault(("bricklink", bricklink_id), []).extend(ldraw_ids)

    rows: list[ColorMappingRow] = []
    collisions = 0
    for (source_system, source_id), ldraw_candidates in sorted(candidates.items()):
        distinct = sorted(set(ldraw_candidates))
        if len(distinct) > 1:
            collisions += 1
        rows.append(ColorMappingRow(source_system, source_id, distinct[0]))
    return tuple(rows), collisions


def _int_ext_ids(entry: object) -> list[int]:
    if not isinstance(entry, dict):
        return []
    raw_ids = entry.get("ext_ids")
    if not isinstance(raw_ids, list):
        return []
    return [value for value in raw_ids if isinstance(value, int)]


@dataclass(frozen=True)
class _PartCandidate:
    ldraw_part_id: str
    contributing_part_num: str


def build_part_mappings(
    parts_json: Iterable[dict[str, Any]],
) -> tuple[tuple[PartMappingRow, ...], int]:
    """Pure transform: parts' external_ids -> LDraw candidates per source ID.

    Stores every candidate (a Rebrickable part can list arrays of BrickLink
    and LDraw IDs), marking exactly one row per (source_system,
    source_part_id) preferred via a deterministic rule: (a) a candidate
    equal to the source ID case-insensitively, (b) else a candidate
    contributed by the Rebrickable part whose own part_num equals the
    source ID, (c) else the lexicographically smallest.
    """
    candidates: dict[tuple[str, str], list[_PartCandidate]] = {}
    for part in parts_json:
        part_num = part.get("part_num")
        if not isinstance(part_num, str) or not part_num:
            continue
        external = part.get("external_ids")
        external = external if isinstance(external, dict) else {}
        ldraw_ids = _str_ext_ids(external.get("LDraw"))
        if not ldraw_ids:
            continue
        part_candidates = [_PartCandidate(ldraw_id, part_num) for ldraw_id in ldraw_ids]
        candidates.setdefault(("rebrickable", part_num), []).extend(part_candidates)
        for bricklink_id in _str_ext_ids(external.get("BrickLink")):
            candidates.setdefault(("bricklink", bricklink_id), []).extend(part_candidates)

    rows: list[PartMappingRow] = []
    ambiguous_count = 0
    for (source_system, source_id), entries in sorted(candidates.items()):
        distinct_ldraw_ids = sorted({entry.ldraw_part_id for entry in entries})
        if len(distinct_ldraw_ids) > 1:
            ambiguous_count += 1
        preferred = _choose_preferred_part_id(source_id, distinct_ldraw_ids, entries)
        rows.extend(
            PartMappingRow(source_system, source_id, ldraw_id, ldraw_id == preferred)
            for ldraw_id in distinct_ldraw_ids
        )
    return tuple(rows), ambiguous_count


def _str_ext_ids(entry: object) -> list[str]:
    if not isinstance(entry, list):
        return []
    return [value for value in entry if isinstance(value, str) and value]


def _choose_preferred_part_id(
    source_id: str, distinct_ldraw_ids: list[str], entries: list[_PartCandidate]
) -> str:
    for ldraw_id in distinct_ldraw_ids:
        if ldraw_id.lower() == source_id.lower():
            return ldraw_id
    for entry in entries:
        if entry.contributing_part_num == source_id:
            return entry.ldraw_part_id
    return distinct_ldraw_ids[0]


def populate_mappings(
    session_factory: sessionmaker[Session],
    api_key: str | None,
    *,
    base_url: str = DEFAULT_API_BASE,
    sleep: SleepFn = time.sleep,
) -> PopulateReport:
    """Fetch everything into memory, then replace both tables + the state
    row in one transaction — a mid-run network failure leaves the previous
    mapping intact, matching the `ldraw_catalog rebuild` precedent."""
    if not api_key:
        raise RebrickableMappingError("REBRICKABLE_API_KEY is not configured")

    started = datetime.now(UTC)
    colors_json = fetch_colors(api_key, base_url=base_url, sleep=sleep)
    parts_json = fetch_parts(api_key, base_url=base_url, sleep=sleep)
    color_rows, color_collisions = build_color_mappings(colors_json)
    part_rows, ambiguous_count = build_part_mappings(parts_json)
    populated_at = datetime.now(UTC)

    try:
        with session_factory.begin() as session:
            session.execute(delete(ExternalIdMapState))
            session.execute(delete(ExternalPartIdMap))
            session.execute(delete(ExternalColorMap))
            if part_rows:
                session.execute(
                    insert(ExternalPartIdMap),
                    [
                        {
                            "source_system": row.source_system,
                            "source_part_id": row.source_part_id,
                            "ldraw_part_id": row.ldraw_part_id,
                            "is_preferred": row.is_preferred,
                        }
                        for row in part_rows
                    ],
                )
            if color_rows:
                session.execute(
                    insert(ExternalColorMap),
                    [
                        {
                            "source_system": row.source_system,
                            "source_color_id": row.source_color_id,
                            "ldraw_color_code": row.ldraw_color_code,
                        }
                        for row in color_rows
                    ],
                )
            session.add(
                ExternalIdMapState(
                    id=1,
                    populated_at=populated_at,
                    part_mapping_count=len(part_rows),
                    color_mapping_count=len(color_rows),
                    ambiguous_part_count=ambiguous_count,
                    fetcher_version=FETCHER_VERSION,
                )
            )
    except RebrickableMappingError:
        raise
    except Exception as error:
        raise RebrickableMappingError(f"Database populate failed: {error}") from error

    duration = (datetime.now(UTC) - started).total_seconds()
    return PopulateReport(
        fetched_color_count=len(colors_json),
        fetched_part_count=len(parts_json),
        part_mapping_count=len(part_rows),
        color_mapping_count=len(color_rows),
        ambiguous_part_count=ambiguous_count,
        color_collision_count=color_collisions,
        duration_seconds=duration,
    )


def get_mapping_status(session: Session) -> MappingStatus:
    state = session.get(ExternalIdMapState, 1)
    if state is None:
        return MappingStatus(
            populated=False,
            populated_at=None,
            part_mapping_count=0,
            color_mapping_count=0,
            ambiguous_part_count=0,
            fetcher_version=None,
        )
    return MappingStatus(
        populated=True,
        populated_at=state.populated_at,
        part_mapping_count=state.part_mapping_count,
        color_mapping_count=state.color_mapping_count,
        ambiguous_part_count=state.ambiguous_part_count,
        fetcher_version=state.fetcher_version,
    )
