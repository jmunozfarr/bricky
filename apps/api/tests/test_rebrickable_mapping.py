from __future__ import annotations

import json
import urllib.error
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ExternalColorMap, ExternalPartIdMap
from app.services import rebrickable_mapping as mapping


def color(
    rb_id: int, *, ldraw: list[int] | None = None, bricklink: list[int] | None = None
) -> dict[str, Any]:
    external: dict[str, Any] = {}
    if ldraw is not None:
        external["LDraw"] = {"ext_ids": ldraw, "ext_descrs": [[]]}
    if bricklink is not None:
        external["BrickLink"] = {"ext_ids": bricklink, "ext_descrs": [[]]}
    return {"id": rb_id, "name": f"Color {rb_id}", "external_ids": external}


def part(
    part_num: str, *, ldraw: list[str] | None = None, bricklink: list[str] | None = None
) -> dict[str, Any]:
    external: dict[str, Any] = {}
    if ldraw is not None:
        external["LDraw"] = ldraw
    if bricklink is not None:
        external["BrickLink"] = bricklink
    return {"part_num": part_num, "name": f"Part {part_num}", "external_ids": external}


class TestBuildColorMappings:
    def test_simple_one_to_one(self) -> None:
        rows, collisions = mapping.build_color_mappings([color(0, ldraw=[0], bricklink=[11])])
        assert collisions == 0
        assert set(rows) == {
            mapping.ColorMappingRow("rebrickable", 0, 0),
            mapping.ColorMappingRow("bricklink", 11, 0),
        }

    def test_missing_ldraw_id_is_skipped(self) -> None:
        rows, collisions = mapping.build_color_mappings([color(5, bricklink=[99])])
        assert rows == ()
        assert collisions == 0

    def test_collision_keeps_lowest_ldraw_code(self) -> None:
        # Two Rebrickable colors both claim BrickLink id 11 with different LDraw codes.
        rows, collisions = mapping.build_color_mappings(
            [color(0, ldraw=[4], bricklink=[11]), color(1, ldraw=[2], bricklink=[11])]
        )
        assert collisions == 1
        bricklink_row = next(row for row in rows if row.source_system == "bricklink")
        assert bricklink_row.ldraw_color_code == 2

    def test_malformed_entries_are_tolerated(self) -> None:
        rows, _ = mapping.build_color_mappings(
            [{"id": "not-an-int"}, {"id": 3, "external_ids": "garbage"}, {}]
        )
        assert rows == ()


class TestBuildPartMappings:
    def test_simple_one_to_one(self) -> None:
        rows, ambiguous = mapping.build_part_mappings(
            [part("3001", ldraw=["3001"], bricklink=["3001"])]
        )
        assert ambiguous == 0
        assert set(rows) == {
            mapping.PartMappingRow("rebrickable", "3001", "3001", True),
            mapping.PartMappingRow("bricklink", "3001", "3001", True),
        }

    def test_missing_ldraw_ids_are_skipped(self) -> None:
        rows, ambiguous = mapping.build_part_mappings([part("3001", bricklink=["3001"])])
        assert rows == ()
        assert ambiguous == 0

    def test_preference_exact_match_wins(self) -> None:
        # A part declaring two LDraw ids (print variants): both its own
        # (rebrickable, part_num) group and the (bricklink, id) group it
        # contributes to are ambiguous; each prefers the exact-match candidate.
        rows, ambiguous = mapping.build_part_mappings(
            [part("32296pr0001", ldraw=["32296pb01", "32296pr0001"], bricklink=["32296pr0001"])]
        )
        assert ambiguous == 2
        preferred = [
            row
            for row in rows
            if row.source_system == "bricklink"
            and row.source_part_id == "32296pr0001"
            and row.is_preferred
        ]
        assert len(preferred) == 1
        assert preferred[0].ldraw_part_id == "32296pr0001"

    def test_preference_contributing_part_num_wins(self) -> None:
        # BrickLink id "78c07" is contributed by two different Rebrickable parts;
        # prefer the LDraw id from the part whose own part_num equals the source id.
        rows, ambiguous = mapping.build_part_mappings(
            [
                part("78c07", ldraw=["78c07a"], bricklink=["78c07"]),
                part("other", ldraw=["78c07b"], bricklink=["78c07"]),
            ]
        )
        assert ambiguous == 1
        preferred = [
            row
            for row in rows
            if row.source_system == "bricklink"
            and row.source_part_id == "78c07"
            and row.is_preferred
        ]
        assert len(preferred) == 1
        assert preferred[0].ldraw_part_id == "78c07a"

    def test_preference_falls_back_to_lexicographic(self) -> None:
        rows, ambiguous = mapping.build_part_mappings(
            [
                part("x1", ldraw=["zzz"], bricklink=["shared"]),
                part("x2", ldraw=["aaa"], bricklink=["shared"]),
            ]
        )
        assert ambiguous == 1
        preferred = [row for row in rows if row.source_part_id == "shared" and row.is_preferred]
        assert len(preferred) == 1
        assert preferred[0].ldraw_part_id == "aaa"

    def test_non_preferred_candidates_are_still_stored(self) -> None:
        rows, _ = mapping.build_part_mappings(
            [part("3070", ldraw=["3070a", "3070b"], bricklink=["3070"])]
        )
        stored_ldraw_ids = {row.ldraw_part_id for row in rows if row.source_part_id == "3070"}
        assert stored_ldraw_ids == {"3070a", "3070b"}


def _http_error(code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://example", code, "error", headers or {}, None)  # type: ignore[arg-type]


class TestFetchJsonRetry:
    def test_retries_429_honoring_retry_after(self) -> None:
        sleeps: list[float] = []
        success_response = MagicMock()
        success_response.__enter__.return_value = success_response
        success_response.__exit__.return_value = False
        success_response.read.return_value = json.dumps({"results": []}).encode()
        outcomes: list[BaseException | MagicMock] = [
            _http_error(429, {"Retry-After": "3"}),
            success_response,
        ]

        def fake_urlopen(*args: Any, **kwargs: Any) -> Any:
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            payload = mapping._fetch_json(
                "http://example", "key", sleep=lambda seconds: sleeps.append(seconds)
            )
        assert payload == {"results": []}
        assert sleeps == [3.0]

    def test_aborts_immediately_on_non_retryable_4xx(self) -> None:
        with (
            patch("urllib.request.urlopen", side_effect=_http_error(401)),
            pytest.raises(mapping.RebrickableApiError),
        ):
            mapping._fetch_json("http://example", "key", sleep=lambda _: None)

    def test_aborts_after_max_attempts_on_repeated_429(self) -> None:
        sleeps: list[float] = []
        with (
            patch("urllib.request.urlopen", side_effect=_http_error(429)),
            pytest.raises(mapping.RebrickableApiError),
        ):
            mapping._fetch_json(
                "http://example", "key", sleep=lambda seconds: sleeps.append(seconds)
            )
        assert len(sleeps) == mapping._MAX_RETRY_ATTEMPTS - 1


@pytest.fixture
def synced_mapping_session(catalog_session_factory: sessionmaker[Session]) -> sessionmaker[Session]:
    return catalog_session_factory


class TestPopulateMappings:
    def test_requires_api_key(self, synced_mapping_session: sessionmaker[Session]) -> None:
        with pytest.raises(mapping.RebrickableMappingError):
            mapping.populate_mappings(synced_mapping_session, None)

    def test_populate_writes_and_replaces(
        self, synced_mapping_session: sessionmaker[Session]
    ) -> None:
        first_colors = [color(0, ldraw=[0], bricklink=[11])]
        first_parts = [part("3001", ldraw=["3001"], bricklink=["3001"])]
        with (
            patch.object(mapping, "fetch_colors", return_value=first_colors),
            patch.object(mapping, "fetch_parts", return_value=first_parts),
        ):
            report = mapping.populate_mappings(synced_mapping_session, "test-key")
        assert report.color_mapping_count == 2
        assert report.part_mapping_count == 2

        with synced_mapping_session() as session:
            assert session.scalar(select(ExternalColorMap).limit(1)) is not None
            status = mapping.get_mapping_status(session)
        assert status.populated
        assert status.part_mapping_count == 2

        # A second populate fully replaces the first (empty this time).
        with (
            patch.object(mapping, "fetch_colors", return_value=[]),
            patch.object(mapping, "fetch_parts", return_value=[]),
        ):
            second_report = mapping.populate_mappings(synced_mapping_session, "test-key")
        assert second_report.color_mapping_count == 0
        assert second_report.part_mapping_count == 0

        with synced_mapping_session() as session:
            assert session.scalar(select(ExternalColorMap).limit(1)) is None
            assert session.scalar(select(ExternalPartIdMap).limit(1)) is None
            status = mapping.get_mapping_status(session)
        assert status.populated
        assert status.part_mapping_count == 0


class TestGetMappingStatus:
    def test_unpopulated(self, synced_mapping_session: sessionmaker[Session]) -> None:
        with synced_mapping_session() as session:
            status = mapping.get_mapping_status(session)
        assert not status.populated
        assert status.populated_at is None
