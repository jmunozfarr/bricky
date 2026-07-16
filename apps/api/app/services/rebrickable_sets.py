from __future__ import annotations

import csv
import gzip
import io
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import IO, Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import RebrickableSet, RebrickableSetDataState, RebrickableSetPart
from app.services.inventory_import_formats import ExternalRow

DEFAULT_DOWNLOADS_BASE = "https://cdn.rebrickable.com/media/downloads"
FETCHER_VERSION = "1"

_MAX_RETRY_ATTEMPTS = 5
_BACKOFF_INITIAL_SECONDS = 2.0
_BACKOFF_CAP_SECONDS = 60.0
_REQUEST_TIMEOUT_SECONDS = 120
_SET_PARTS_CHUNK_ROWS = 5_000

SleepFn = Callable[[float], None]


class RebrickableSetsError(Exception):
    """Raised when the set-data populate run cannot complete safely."""


@dataclass(frozen=True)
class SetRecord:
    set_num: str
    name: str
    num_parts: int


@dataclass(frozen=True)
class WinningInventory:
    inventory_id: int
    version: int


@dataclass(frozen=True)
class SetPartRow:
    set_num: str
    part_num: str
    color_id: int
    quantity: int
    is_spare: bool


@dataclass(frozen=True)
class PopulateSetsReport:
    set_count: int
    part_row_count: int
    duration_seconds: float


@dataclass(frozen=True)
class SetDataStatus:
    populated: bool
    populated_at: datetime | None
    set_count: int
    part_row_count: int
    fetcher_version: str | None


@dataclass(frozen=True)
class SetMeta:
    set_num: str
    name: str
    num_parts: int


def _open_with_retry(url: str, *, sleep: SleepFn, timeout: int) -> IO[bytes]:
    """Retries the initial connection with capped exponential backoff
    (mirroring `rebrickable_mapping._fetch_json`). Once the stream opens,
    a read failure aborts the whole populate run rather than retrying
    mid-stream -- nothing has been committed yet, matching this project's
    one-shot operator-command philosophy."""
    backoff = _BACKOFF_INITIAL_SECONDS
    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
        request = urllib.request.Request(url, headers={"User-Agent": "Bricky Rebrickable sets"})
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except (urllib.error.URLError, OSError) as error:
            last_error = error
            if attempt == _MAX_RETRY_ATTEMPTS:
                break
            sleep(min(backoff, _BACKOFF_CAP_SECONDS))
            backoff = min(backoff * 2, _BACKOFF_CAP_SECONDS)
    raise RebrickableSetsError(f"Unable to download {url}: {last_error}")


def _stream_gzip_csv_rows(
    url: str, *, sleep: SleepFn, timeout: int = _REQUEST_TIMEOUT_SECONDS
) -> Iterator[dict[str, str]]:
    response = _open_with_retry(url, sleep=sleep, timeout=timeout)
    try:
        with gzip.GzipFile(fileobj=response) as gzip_file:
            text = io.TextIOWrapper(gzip_file, encoding="utf-8", newline="")
            yield from csv.DictReader(text)
    finally:
        response.close()


def fetch_sets_csv_rows(
    base_url: str = DEFAULT_DOWNLOADS_BASE, *, sleep: SleepFn = time.sleep
) -> Iterator[dict[str, str]]:
    return _stream_gzip_csv_rows(f"{base_url}/sets.csv.gz", sleep=sleep)


def fetch_inventories_csv_rows(
    base_url: str = DEFAULT_DOWNLOADS_BASE, *, sleep: SleepFn = time.sleep
) -> Iterator[dict[str, str]]:
    return _stream_gzip_csv_rows(f"{base_url}/inventories.csv.gz", sleep=sleep)


def fetch_set_parts_csv_rows(
    base_url: str = DEFAULT_DOWNLOADS_BASE, *, sleep: SleepFn = time.sleep
) -> Iterator[dict[str, str]]:
    return _stream_gzip_csv_rows(f"{base_url}/inventory_parts.csv.gz", sleep=sleep)


def parse_sets(rows: Iterable[dict[str, Any]]) -> dict[str, SetRecord]:
    records: dict[str, SetRecord] = {}
    for row in rows:
        set_num = row.get("set_num")
        name = row.get("name")
        if not set_num or name is None:
            continue
        try:
            num_parts = int(row["num_parts"])
        except KeyError, TypeError, ValueError:
            continue
        records[set_num] = SetRecord(set_num=set_num, name=name, num_parts=num_parts)
    return records


def select_winning_inventories(
    rows: Iterable[dict[str, Any]], known_set_nums: AbstractSet[str]
) -> dict[str, WinningInventory]:
    """One inventory per known set number: highest `version` wins (a
    working assumption, not verified against rebrickable.com's own
    default -- cheap to flip since this table is fully rebuildable).
    Set numbers absent from `known_set_nums` (chiefly `fig-NNNNNN` minifig
    inventories, which never appear in sets.csv) are dropped."""
    winners: dict[str, WinningInventory] = {}
    for row in rows:
        set_num = row.get("set_num")
        if set_num is None or set_num not in known_set_nums:
            continue
        try:
            inventory_id = int(row["id"])
            version = int(row["version"])
        except KeyError, TypeError, ValueError:
            continue
        current = winners.get(set_num)
        if current is None or version > current.version:
            winners[set_num] = WinningInventory(inventory_id, version)
    return winners


def parse_set_part_row(
    row: dict[str, Any], inventory_to_set_num: Mapping[int, str]
) -> SetPartRow | None:
    try:
        inventory_id = int(row["inventory_id"])
    except KeyError, TypeError, ValueError:
        return None
    set_num = inventory_to_set_num.get(inventory_id)
    if set_num is None:
        return None
    part_num = row.get("part_num")
    if not part_num:
        return None
    try:
        color_id = int(row["color_id"])
        quantity = int(row["quantity"])
    except KeyError, TypeError, ValueError:
        return None
    if quantity <= 0:
        return None
    is_spare = str(row.get("is_spare", "")).strip().lower() == "true"
    return SetPartRow(set_num, part_num, color_id, quantity, is_spare)


def populate_sets(
    session_factory: sessionmaker[Session],
    *,
    base_url: str = DEFAULT_DOWNLOADS_BASE,
    sleep: SleepFn = time.sleep,
) -> PopulateSetsReport:
    """Fetches `sets.csv`/`inventories.csv` fully into memory (small: tens
    of thousands of rows), resolves one winning inventory per set, then
    streams `inventory_parts.csv` (over a million rows) directly into a
    chunked bulk insert without ever materializing the full decompressed
    file or row list. One transaction for the full replace + state row --
    a failed run leaves the previous snapshot untouched."""
    started = datetime.now(UTC)
    sets_by_num = parse_sets(fetch_sets_csv_rows(base_url, sleep=sleep))
    if not sets_by_num:
        raise RebrickableSetsError("No sets were parsed from the sets dump")

    winners = select_winning_inventories(
        fetch_inventories_csv_rows(base_url, sleep=sleep), frozenset(sets_by_num)
    )
    if not winners:
        raise RebrickableSetsError("No set inventories were resolved from the inventories dump")
    inventory_to_set_num = {winner.inventory_id: set_num for set_num, winner in winners.items()}

    populated_at = datetime.now(UTC)
    part_row_count = 0
    try:
        with session_factory.begin() as session:
            session.execute(delete(RebrickableSetDataState))
            session.execute(delete(RebrickableSetPart))
            session.execute(delete(RebrickableSet))
            session.execute(
                insert(RebrickableSet),
                [
                    {
                        "set_num": record.set_num,
                        "name": record.name,
                        "num_parts": record.num_parts,
                        "chosen_version": winners[record.set_num].version,
                    }
                    for record in sets_by_num.values()
                    if record.set_num in winners
                ],
            )

            chunk: list[dict[str, object]] = []
            for raw_row in fetch_set_parts_csv_rows(base_url, sleep=sleep):
                parsed = parse_set_part_row(raw_row, inventory_to_set_num)
                if parsed is None:
                    continue
                chunk.append(
                    {
                        "set_num": parsed.set_num,
                        "part_num": parsed.part_num,
                        "color_id": parsed.color_id,
                        "quantity": parsed.quantity,
                        "is_spare": parsed.is_spare,
                    }
                )
                part_row_count += 1
                if len(chunk) >= _SET_PARTS_CHUNK_ROWS:
                    session.execute(insert(RebrickableSetPart), chunk)
                    chunk = []
            if chunk:
                session.execute(insert(RebrickableSetPart), chunk)

            session.add(
                RebrickableSetDataState(
                    id=1,
                    populated_at=populated_at,
                    set_count=len(winners),
                    part_row_count=part_row_count,
                    fetcher_version=FETCHER_VERSION,
                )
            )
    except RebrickableSetsError:
        raise
    except Exception as error:
        raise RebrickableSetsError(f"Database populate failed: {error}") from error

    duration = (datetime.now(UTC) - started).total_seconds()
    return PopulateSetsReport(
        set_count=len(winners), part_row_count=part_row_count, duration_seconds=duration
    )


def get_set_data_status(session: Session) -> SetDataStatus:
    state = session.get(RebrickableSetDataState, 1)
    if state is None:
        return SetDataStatus(
            populated=False,
            populated_at=None,
            set_count=0,
            part_row_count=0,
            fetcher_version=None,
        )
    return SetDataStatus(
        populated=True,
        populated_at=state.populated_at,
        set_count=state.set_count,
        part_row_count=state.part_row_count,
        fetcher_version=state.fetcher_version,
    )


def load_set_parts(
    session: Session, set_num: str
) -> tuple[SetMeta, tuple[ExternalRow, ...]] | None:
    """Resolves `set_num` (exact match, then a `-1` edition-suffix fallback
    per Rebrickable's convention) and returns its official metadata plus
    aggregated BOM rows. Duplicate `(part_num, color_id, is_spare)` rows in
    the source dump are summed here at query time, not at populate time."""
    normalized = set_num.strip()
    record = session.get(RebrickableSet, normalized)
    if record is None and "-" not in normalized:
        candidate = f"{normalized}-1"
        record = session.get(RebrickableSet, candidate)
        if record is not None:
            normalized = candidate
    if record is None:
        return None

    rows = session.execute(
        select(
            RebrickableSetPart.part_num,
            RebrickableSetPart.color_id,
            RebrickableSetPart.is_spare,
            func.sum(RebrickableSetPart.quantity),
        )
        .where(RebrickableSetPart.set_num == normalized)
        .group_by(
            RebrickableSetPart.part_num, RebrickableSetPart.color_id, RebrickableSetPart.is_spare
        )
        .order_by(RebrickableSetPart.part_num, RebrickableSetPart.color_id)
    ).all()

    external_rows = tuple(
        ExternalRow(
            line_number=index + 1,
            source_part_id=part_num,
            source_color_id=color_id,
            quantity=int(quantity),
            is_spare=is_spare,
        )
        for index, (part_num, color_id, is_spare, quantity) in enumerate(rows)
    )
    meta = SetMeta(set_num=normalized, name=record.name, num_parts=record.num_parts)
    return meta, external_rows
