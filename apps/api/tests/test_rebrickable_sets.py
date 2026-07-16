from __future__ import annotations

import gzip
import io
import urllib.error
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.services import rebrickable_sets as sets_service


def set_row(set_num: str, name: str = "Test Set", num_parts: str = "10") -> dict[str, str]:
    return {
        "set_num": set_num,
        "name": name,
        "year": "2020",
        "theme_id": "1",
        "num_parts": num_parts,
    }


def inventory_row(inventory_id: int, version: int, set_num: str) -> dict[str, str]:
    return {"id": str(inventory_id), "version": str(version), "set_num": set_num}


def part_row(
    inventory_id: int, part_num: str, color_id: int, quantity: int, is_spare: str = "False"
) -> dict[str, str]:
    return {
        "inventory_id": str(inventory_id),
        "part_num": part_num,
        "color_id": str(color_id),
        "quantity": str(quantity),
        "is_spare": is_spare,
    }


class TestParseSets:
    def test_parses_valid_rows(self) -> None:
        records = sets_service.parse_sets([set_row("7922-1", "Yoda's Starfighter", "309")])
        assert records == {"7922-1": sets_service.SetRecord("7922-1", "Yoda's Starfighter", 309)}

    def test_skips_malformed_rows(self) -> None:
        records = sets_service.parse_sets(
            [
                {"set_num": "", "name": "x", "num_parts": "1"},
                {"set_num": "a-1", "name": "x", "num_parts": "not-a-number"},
                {"set_num": "b-1"},
            ]
        )
        assert records == {}


class TestSelectWinningInventories:
    def test_highest_version_wins(self) -> None:
        winners = sets_service.select_winning_inventories(
            [
                inventory_row(1, 1, "7922-1"),
                inventory_row(2, 2, "7922-1"),
            ],
            known_set_nums=frozenset({"7922-1"}),
        )
        assert winners == {"7922-1": sets_service.WinningInventory(inventory_id=2, version=2)}

    def test_drops_set_nums_not_in_sets_csv(self) -> None:
        # Mirrors real data: fig-NNNNNN minifig inventories never appear in
        # sets.csv and must be excluded.
        winners = sets_service.select_winning_inventories(
            [inventory_row(1, 1, "fig-000001")],
            known_set_nums=frozenset({"7922-1"}),
        )
        assert winners == {}

    def test_skips_malformed_rows(self) -> None:
        winners = sets_service.select_winning_inventories(
            [{"id": "x", "version": "1", "set_num": "7922-1"}],
            known_set_nums=frozenset({"7922-1"}),
        )
        assert winners == {}


class TestParseSetPartRow:
    def test_maps_known_inventory(self) -> None:
        parsed = sets_service.parse_set_part_row(part_row(1, "3001", 4, 2), {1: "7922-1"})
        assert parsed == sets_service.SetPartRow("7922-1", "3001", 4, 2, False)

    def test_drops_rows_for_unknown_inventory(self) -> None:
        assert sets_service.parse_set_part_row(part_row(99, "3001", 4, 2), {1: "7922-1"}) is None

    def test_parses_is_spare_case_insensitively(self) -> None:
        parsed = sets_service.parse_set_part_row(
            part_row(1, "3001", 4, 2, is_spare="True"), {1: "7922-1"}
        )
        assert parsed is not None
        assert parsed.is_spare is True

    def test_drops_zero_or_negative_quantity(self) -> None:
        assert sets_service.parse_set_part_row(part_row(1, "3001", 4, 0), {1: "7922-1"}) is None

    def test_drops_malformed_rows(self) -> None:
        assert (
            sets_service.parse_set_part_row({"inventory_id": "1", "part_num": "3001"}, {1: "x-1"})
            is None
        )


def _gzip_csv(header: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    buffer.write(",".join(header) + "\n")
    for row in rows:
        buffer.write(",".join(row) + "\n")
    return gzip.compress(buffer.getvalue().encode("utf-8"))


class TestStreamGzipCsvRows:
    def test_streams_rows_from_a_real_gzip_payload(self) -> None:
        payload = _gzip_csv(["set_num", "name"], [["7922-1", "Yoda"], ["001-1", "Gears"]])
        response = MagicMock()
        response.read = io.BytesIO(payload).read
        response.close = MagicMock()

        with patch("urllib.request.urlopen", return_value=response):
            rows = list(
                sets_service._stream_gzip_csv_rows(
                    "http://example/sets.csv.gz", sleep=lambda _: None
                )
            )
        assert rows == [
            {"set_num": "7922-1", "name": "Yoda"},
            {"set_num": "001-1", "name": "Gears"},
        ]
        response.close.assert_called_once()


def _url_error(reason: str = "boom") -> urllib.error.URLError:
    return urllib.error.URLError(reason)


class TestOpenWithRetry:
    def test_retries_then_succeeds(self) -> None:
        sleeps: list[float] = []
        success = MagicMock()
        outcomes: list[BaseException | MagicMock] = [_url_error(), success]

        def fake_urlopen(*args: Any, **kwargs: Any) -> Any:
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = sets_service._open_with_retry(
                "http://example/x.csv.gz", sleep=lambda seconds: sleeps.append(seconds), timeout=5
            )
        assert result is success
        assert sleeps == [2.0]

    def test_aborts_after_max_attempts(self) -> None:
        with (
            patch("urllib.request.urlopen", side_effect=_url_error()),
            pytest.raises(sets_service.RebrickableSetsError),
        ):
            sets_service._open_with_retry(
                "http://example/x.csv.gz", sleep=lambda _: None, timeout=5
            )


@pytest.fixture
def synced_sets_session(catalog_session_factory: sessionmaker[Session]) -> sessionmaker[Session]:
    return catalog_session_factory


class TestPopulateSets:
    def test_populates_sets_and_parts(self, synced_sets_session: sessionmaker[Session]) -> None:
        sets_rows = [set_row("7922-1", "Yoda's Starfighter", "3")]
        inventory_rows = [inventory_row(1, 1, "7922-1"), inventory_row(2, 2, "7922-1")]
        # Two rows for the losing v1 inventory (must be excluded) and two
        # for the winning v2 inventory.
        part_rows = [
            part_row(1, "wrong", 0, 99),
            part_row(2, "3001", 4, 2),
            part_row(2, "3070b", 1, 1),
        ]
        with (
            patch.object(sets_service, "fetch_sets_csv_rows", return_value=sets_rows),
            patch.object(sets_service, "fetch_inventories_csv_rows", return_value=inventory_rows),
            patch.object(sets_service, "fetch_set_parts_csv_rows", return_value=part_rows),
        ):
            report = sets_service.populate_sets(synced_sets_session)

        assert report.set_count == 1
        assert report.part_row_count == 2

        with synced_sets_session() as session:
            status = sets_service.get_set_data_status(session)
            loaded = sets_service.load_set_parts(session, "7922-1")

        assert status.populated
        assert status.set_count == 1
        assert status.part_row_count == 2
        assert loaded is not None
        meta, rows = loaded
        assert meta == sets_service.SetMeta("7922-1", "Yoda's Starfighter", 3)
        assert {(row.source_part_id, row.source_color_id, row.quantity) for row in rows} == {
            ("3001", 4, 2),
            ("3070b", 1, 1),
        }

    def test_chunked_insert_matches_row_count(
        self, synced_sets_session: sessionmaker[Session]
    ) -> None:
        sets_rows = [set_row("x-1", "X", "20")]
        inventory_rows = [inventory_row(1, 1, "x-1")]
        part_rows = [part_row(1, f"part{i}", 0, 1) for i in range(7)]
        with (
            patch.object(sets_service, "fetch_sets_csv_rows", return_value=sets_rows),
            patch.object(sets_service, "fetch_inventories_csv_rows", return_value=inventory_rows),
            patch.object(sets_service, "fetch_set_parts_csv_rows", return_value=part_rows),
            patch.object(sets_service, "_SET_PARTS_CHUNK_ROWS", 2),
        ):
            report = sets_service.populate_sets(synced_sets_session)
        assert report.part_row_count == 7

    def test_second_populate_fully_replaces_first(
        self, synced_sets_session: sessionmaker[Session]
    ) -> None:
        with (
            patch.object(
                sets_service, "fetch_sets_csv_rows", return_value=[set_row("a-1", "A", "1")]
            ),
            patch.object(
                sets_service,
                "fetch_inventories_csv_rows",
                return_value=[inventory_row(1, 1, "a-1")],
            ),
            patch.object(
                sets_service, "fetch_set_parts_csv_rows", return_value=[part_row(1, "3001", 4, 1)]
            ),
        ):
            sets_service.populate_sets(synced_sets_session)

        with (
            patch.object(
                sets_service, "fetch_sets_csv_rows", return_value=[set_row("b-1", "B", "1")]
            ),
            patch.object(
                sets_service,
                "fetch_inventories_csv_rows",
                return_value=[inventory_row(2, 1, "b-1")],
            ),
            patch.object(
                sets_service, "fetch_set_parts_csv_rows", return_value=[part_row(2, "3002", 4, 1)]
            ),
        ):
            sets_service.populate_sets(synced_sets_session)

        with synced_sets_session() as session:
            assert sets_service.load_set_parts(session, "a-1") is None
            assert sets_service.load_set_parts(session, "b-1") is not None

    def test_requires_at_least_one_set(self, synced_sets_session: sessionmaker[Session]) -> None:
        with (
            patch.object(sets_service, "fetch_sets_csv_rows", return_value=[]),
            pytest.raises(sets_service.RebrickableSetsError),
        ):
            sets_service.populate_sets(synced_sets_session)


class TestGetSetDataStatus:
    def test_unpopulated(self, synced_sets_session: sessionmaker[Session]) -> None:
        with synced_sets_session() as session:
            status = sets_service.get_set_data_status(session)
        assert not status.populated
        assert status.populated_at is None


class TestLoadSetParts:
    def test_falls_back_to_dash_one_suffix(
        self, synced_sets_session: sessionmaker[Session]
    ) -> None:
        with (
            patch.object(
                sets_service, "fetch_sets_csv_rows", return_value=[set_row("7922-1", "Yoda", "1")]
            ),
            patch.object(
                sets_service,
                "fetch_inventories_csv_rows",
                return_value=[inventory_row(1, 1, "7922-1")],
            ),
            patch.object(
                sets_service, "fetch_set_parts_csv_rows", return_value=[part_row(1, "3001", 4, 1)]
            ),
        ):
            sets_service.populate_sets(synced_sets_session)

        with synced_sets_session() as session:
            loaded = sets_service.load_set_parts(session, "7922")
        assert loaded is not None
        assert loaded[0].set_num == "7922-1"

    def test_unknown_set_returns_none(self, synced_sets_session: sessionmaker[Session]) -> None:
        with synced_sets_session() as session:
            assert sets_service.load_set_parts(session, "nonexistent") is None

    def test_duplicate_rows_are_summed_at_query_time(
        self, synced_sets_session: sessionmaker[Session]
    ) -> None:
        with (
            patch.object(
                sets_service, "fetch_sets_csv_rows", return_value=[set_row("7922-1", "Yoda", "1")]
            ),
            patch.object(
                sets_service,
                "fetch_inventories_csv_rows",
                return_value=[inventory_row(1, 1, "7922-1")],
            ),
            patch.object(
                sets_service,
                "fetch_set_parts_csv_rows",
                return_value=[part_row(1, "3001", 4, 2), part_row(1, "3001", 4, 3)],
            ),
        ):
            sets_service.populate_sets(synced_sets_session)

        with synced_sets_session() as session:
            loaded = sets_service.load_set_parts(session, "7922-1")
        assert loaded is not None
        _meta, rows = loaded
        assert len(rows) == 1
        assert rows[0].quantity == 5
