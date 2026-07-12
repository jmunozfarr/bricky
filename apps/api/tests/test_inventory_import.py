from __future__ import annotations

import io

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.services.inventory_import as inventory_import
from app.models import InventoryItem, LDrawColor, Part
from app.services.inventory_import import (
    InventoryImportError,
    InventoryImportTooLargeError,
    ParsedCsv,
    apply_import_plan,
    build_import_plan,
    parse_inventory_csv,
    plan_inventory_import,
    read_csv_upload,
    summarize_changes,
)
from app.services.local_workspace import resolve_local_workspace


def parsed(*rows: tuple[str, int, int]) -> ParsedCsv:
    return ParsedCsv(
        rows=tuple(
            inventory_import.CsvRow(
                line_number=index + 2, part_id=part_id, color_code=color, quantity=quantity
            )
            for index, (part_id, color, quantity) in enumerate(rows)
        ),
        issues=(),
        total_data_rows=len(rows),
        ignored_columns=(),
    )


def plan_for(
    csv_rows: list[tuple[str, int, int]],
    strategy: inventory_import.Strategy = "add",
    *,
    aliases: dict[str, str] | None = None,
    catalog: dict[str, str] | None = None,
    colors: frozenset[int] = frozenset({1, 4}),
    current: dict[tuple[str, int], tuple[str, int]] | None = None,
) -> inventory_import.ImportPlan:
    return plan_inventory_import(
        parsed(*csv_rows),
        strategy,
        canonical_by_source=aliases or {},
        catalog_casing_by_normalized=catalog if catalog is not None else {"3001": "3001"},
        known_color_codes=colors,
        current_rows=current or {},
    )


def test_parse_happy_path_with_bom_crlf_and_blank_lines() -> None:
    data = b"\xef\xbb\xbfpart_id,color_code,quantity\r\n3001,4,10\r\n\r\n 3070b ,1,2\r\n"
    result = parse_inventory_csv(data)
    assert result.issues == ()
    assert result.total_data_rows == 2
    assert result.ignored_columns == ()
    assert [(row.part_id, row.color_code, row.quantity) for row in result.rows] == [
        ("3001", 4, 10),
        ("3070b", 1, 2),
    ]


def test_parse_header_is_case_insensitive_and_order_free() -> None:
    data = b"Quantity, PART_ID ,Color_Code\n7,3001,4\n"
    result = parse_inventory_csv(data)
    assert result.rows == (
        inventory_import.CsvRow(line_number=2, part_id="3001", color_code=4, quantity=7),
    )


def test_parse_reports_ignored_and_duplicate_columns() -> None:
    data = b"part_id,part_id,color_code,quantity,notes\n3001,ignored,4,1,hello\n"
    result = parse_inventory_csv(data)
    assert result.ignored_columns == ("part_id", "notes")
    assert result.rows[0].part_id == "3001"


def test_parse_missing_required_column_raises() -> None:
    with pytest.raises(InventoryImportError, match="color_code"):
        parse_inventory_csv(b"part_id,quantity\n3001,1\n")


def test_parse_without_header_raises() -> None:
    with pytest.raises(InventoryImportError, match="header"):
        parse_inventory_csv(b"")


def test_parse_rejects_non_utf8_bytes() -> None:
    utf16 = "part_id,color_code,quantity\n3001,4,1\n".encode("utf-16")
    with pytest.raises(InventoryImportError, match="UTF-8"):
        parse_inventory_csv(utf16)


def test_parse_row_issues_cover_all_codes() -> None:
    data = (
        b"part_id,color_code,quantity\n"
        b"3001,4\n"  # line 2: too short
        b",4,1\n"  # line 3: empty part id
        b"%s,4,1\n"  # line 4: over-long part id
        b"3001,x,1\n"  # line 5: color not integer
        b"3001,-1,1\n"  # line 6: negative color
        b"3001,16,1\n"  # line 7: placeholder color
        b"3001,24,1\n"  # line 8: placeholder color
        b"3001,4,0\n"  # line 9: zero quantity
        b"3001,4,-2\n"  # line 10: negative quantity
        b"3001,4,1000000\n"  # line 11: above cap
        b"3001,4,1.5\n"  # line 12: not an integer
        b"3001,4,abc\n"  # line 13: not an integer
    ) % (b"x" * 65)
    result = parse_inventory_csv(data)
    assert result.rows == ()
    assert result.total_data_rows == 12
    assert [(issue.line_number, issue.code) for issue in result.issues] == [
        (2, "wrong_field_count"),
        (3, "missing_part_id"),
        (4, "bad_part_id"),
        (5, "bad_color_code"),
        (6, "bad_color_code"),
        (7, "non_physical_color"),
        (8, "non_physical_color"),
        (9, "bad_quantity"),
        (10, "bad_quantity"),
        (11, "bad_quantity"),
        (12, "bad_quantity"),
        (13, "bad_quantity"),
    ]


def test_parse_row_cap_raises() -> None:
    data = b"part_id,color_code,quantity\n" + b"3001,4,1\n" * 3
    with pytest.raises(InventoryImportError, match="more than 2"):
        parse_inventory_csv(data, max_rows=2)


def test_read_csv_upload_enforces_cap_and_rejects_empty() -> None:
    with pytest.raises(InventoryImportTooLargeError):
        read_csv_upload(io.BytesIO(b"x" * 65), maximum_bytes=64)
    with pytest.raises(InventoryImportError, match="empty"):
        read_csv_upload(io.BytesIO(b""), maximum_bytes=64)
    assert read_csv_upload(io.BytesIO(b"data"), maximum_bytes=64) == b"data"


def test_plan_classifies_create_update_unchanged_for_both_strategies() -> None:
    current = {("3001", 4): ("3001", 5)}
    added = plan_for([("3001", 4, 3), ("3001", 1, 2)], "add", current=current)
    by_key = {(c.normalized_part_id, c.color_code): c for c in added.changes}
    assert by_key[("3001", 4)].change == "update"
    assert by_key[("3001", 4)].resulting_quantity == 8
    assert by_key[("3001", 1)].change == "create"
    assert by_key[("3001", 1)].resulting_quantity == 2

    replaced = plan_for([("3001", 4, 5)], "replace", current=current)
    assert replaced.changes[0].change == "unchanged"
    assert replaced.changes[0].resulting_quantity == 5


def test_plan_add_clamps_at_maximum_quantity() -> None:
    current = {("3001", 4): ("3001", 999_998)}
    plan = plan_for([("3001", 4, 5)], "add", current=current)
    assert plan.changes[0].resulting_quantity == 999_999
    assert plan.changes[0].change == "update"

    saturated = plan_for([("3001", 4, 5)], "add", current={("3001", 4): ("3001", 999_999)})
    assert saturated.changes[0].change == "unchanged"


def test_plan_sums_in_file_duplicates_and_clamps() -> None:
    plan = plan_for([("3001", 4, 999_998), ("3001", 4, 5), ("3001", 4, 1)], "replace")
    assert plan.duplicate_row_count == 2
    assert plan.changes[0].quantity == 999_999


def test_plan_merges_casing_variants_and_prefers_existing_spelling() -> None:
    plan = plan_for(
        [("3070B", 4, 1), ("3070b", 4, 2)],
        "add",
        catalog={"3070b": "3070b"},
        current={("3070b", 4): ("3070B", 3)},
    )
    assert len(plan.changes) == 1
    change = plan.changes[0]
    assert change.part_id == "3070B"
    assert change.source_part_ids == ("3070B", "3070b")
    assert change.quantity == 3
    assert change.resulting_quantity == 6
    assert change.canonicalized_from is None


def test_plan_spelling_falls_back_to_catalog_then_normalized() -> None:
    catalog_only = plan_for([("3070B", 4, 1)], catalog={"3070b": "3070b"})
    assert catalog_only.changes[0].part_id == "3070b"

    unknown = plan_for([("Custom-Part", 4, 1)], catalog={})
    assert unknown.changes[0].part_id == "custom-part"
    assert unknown.changes[0].unknown_reason == "part"


def test_plan_alias_canonicalization_merges_and_reports() -> None:
    plan = plan_for(
        [("3001old", 4, 2), ("3001", 4, 3)],
        "add",
        aliases={"3001old": "3001"},
    )
    assert len(plan.changes) == 1
    change = plan.changes[0]
    assert change.canonicalized_from == "3001old"
    assert change.quantity == 5
    assert change.unknown_reason is None
    assert plan.duplicate_row_count == 1


def test_plan_unknown_reasons_prefer_part_over_color() -> None:
    plan = plan_for(
        [("mystery", 999, 1), ("3001", 999, 1)],
        catalog={"3001": "3001"},
    )
    by_key = {c.normalized_part_id: c for c in plan.changes}
    assert by_key["mystery"].unknown_reason == "part"
    assert by_key["3001"].unknown_reason == "color"


def test_plan_unknown_part_with_existing_orphan_row_keeps_quantities() -> None:
    plan = plan_for(
        [("orphan", 4, 2)],
        "add",
        catalog={},
        current={("orphan", 4): ("Orphan", 7)},
    )
    change = plan.changes[0]
    assert change.unknown_reason == "part"
    assert change.part_id == "Orphan"
    assert change.current_quantity == 7
    assert change.resulting_quantity == 9


def test_summarize_changes_counts_buckets() -> None:
    plan = plan_for(
        [("3001", 4, 1), ("unknown", 4, 1), ("3001", 999, 1)],
        current={("3001", 4): ("3001", 1)},
    )
    known = summarize_changes(c for c in plan.changes if c.unknown_reason is None)
    unknown = summarize_changes(c for c in plan.changes if c.unknown_reason is not None)
    assert known.row_count == 1
    assert known.unchanged_count == 0
    assert known.update_count == 1
    assert unknown.row_count == 2
    assert unknown.missing_part_count == 1
    assert unknown.missing_color_count == 1
    assert unknown.create_count == 2


def seed_catalog(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        session.add_all(
            [
                Part(
                    part_id="3001",
                    name="Brick 2 x 4",
                    relative_path="parts/3001.dat",
                    category="Brick",
                    is_subpart=False,
                    is_shortcut=False,
                ),
                Part(
                    part_id="3070b",
                    name="Tile 1 x 1",
                    relative_path="parts/3070b.dat",
                    category="Tile",
                    is_subpart=False,
                    is_shortcut=False,
                ),
                LDrawColor(code=1, name="Blue", value_hex="#0055BF", alpha=255),
                LDrawColor(code=4, name="Red", value_hex="#C91A09", alpha=255),
            ]
        )


def identity_aliases(part_ids: set[str]) -> dict[str, str]:
    return {}


def test_build_import_plan_uses_bounded_lookups(
    catalog_session_factory: sessionmaker[Session],
) -> None:
    seed_catalog(catalog_session_factory)
    with catalog_session_factory.begin() as session:
        workspace = resolve_local_workspace(session)
        session.add(
            InventoryItem(workspace_id=workspace.id, part_id="3001", color_code=4, quantity=5)
        )
    source = parse_inventory_csv(
        b"part_id,color_code,quantity\n3001,4,3\n3070B,1,2\nmystery,4,1\n3001,999,1\n"
    )
    with catalog_session_factory() as session:
        workspace = resolve_local_workspace(session)
        plan = build_import_plan(session, workspace.id, source, "add", identity_aliases)

    by_key = {(c.normalized_part_id, c.color_code): c for c in plan.changes}
    assert by_key[("3001", 4)].current_quantity == 5
    assert by_key[("3001", 4)].resulting_quantity == 8
    assert by_key[("3070b", 1)].part_id == "3070b"
    assert by_key[("3070b", 1)].change == "create"
    assert by_key[("mystery", 4)].unknown_reason == "part"
    assert by_key[("3001", 999)].unknown_reason == "color"


def test_apply_import_plan_add_replace_and_unknown_filter(
    catalog_session_factory: sessionmaker[Session],
) -> None:
    seed_catalog(catalog_session_factory)
    source = parse_inventory_csv(b"part_id,color_code,quantity\n3001,4,3\nmystery,4,2\n")
    with catalog_session_factory.begin() as session:
        workspace = resolve_local_workspace(session)
        workspace_id = workspace.id
        plan = build_import_plan(session, workspace_id, source, "add", identity_aliases)
        counts = apply_import_plan(session, workspace_id, plan, include_unknown=False)
    assert counts.applied_rows == 1
    assert counts.created == 1
    assert counts.skipped_unknown == 1
    assert counts.quantity_delta == 3

    with catalog_session_factory.begin() as session:
        plan = build_import_plan(session, workspace_id, source, "add", identity_aliases)
        counts = apply_import_plan(session, workspace_id, plan, include_unknown=True)
    assert counts.applied_rows == 2
    assert counts.updated == 1
    assert counts.quantity_delta == 5

    with catalog_session_factory.begin() as session:
        plan = build_import_plan(session, workspace_id, source, "replace", identity_aliases)
        counts = apply_import_plan(session, workspace_id, plan, include_unknown=True)
    assert counts.updated == 1
    assert counts.unchanged == 1

    with catalog_session_factory() as session:
        rows = {
            (item.part_id, item.color_code): item.quantity
            for item in session.scalars(select(InventoryItem))
        }
    assert rows == {("3001", 4): 3, ("mystery", 4): 2}


def test_apply_import_plan_chunks_large_batches(
    catalog_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_catalog(catalog_session_factory)
    monkeypatch.setattr(inventory_import, "_UPSERT_CHUNK_ROWS", 2)
    source = parse_inventory_csv(
        b"part_id,color_code,quantity\na,4,1\nb,4,2\nc,4,3\nd,4,4\ne,4,5\n"
    )
    with catalog_session_factory.begin() as session:
        workspace = resolve_local_workspace(session)
        plan = build_import_plan(session, workspace.id, source, "add", identity_aliases)
        counts = apply_import_plan(session, workspace.id, plan, include_unknown=True)
    assert counts.applied_rows == 5

    with catalog_session_factory() as session:
        stored = sorted(
            (item.part_id, item.quantity) for item in session.scalars(select(InventoryItem))
        )
    assert stored == [("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5)]
