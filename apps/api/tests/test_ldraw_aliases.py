from __future__ import annotations

from pathlib import Path

from app.services.ldraw_aliases import (
    LDrawMovedAliasResolver,
    OfficialPartRecord,
)


IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"


def write_part(root: Path, part_id: str, description: str | None = None) -> OfficialPartRecord:
    relative_path = f"parts/{part_id}.dat"
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"0 {description or f'Part {part_id}'}\n"
        f"0 Name: {part_id}.dat\n"
        "0 !LDRAW_ORG Part\n"
        "3 16 0 0 0 1 0 0 0 1 0\n",
        encoding="utf-8",
    )
    return OfficialPartRecord(part_id, description or f"Part {part_id}", relative_path)


def write_moved(
    root: Path,
    part_id: str,
    target: str,
    *,
    description_target: str | None = None,
    transform: str = IDENTITY,
    color_code: int = 16,
) -> OfficialPartRecord:
    description = f"~Moved to {description_target or target}"
    relative_path = f"parts/{part_id}.dat"
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"0 {description}\n"
        f"0 Name: {part_id}.dat\n"
        "0 !LDRAW_ORG Part\n"
        "\n"
        f"1 {color_code} {transform} {target}.dat\n",
        encoding="utf-8",
    )
    return OfficialPartRecord(part_id, description, relative_path)


def test_direct_chain_and_case_insensitive_resolution(tmp_path: Path) -> None:
    root = tmp_path / "official"
    parts = [
        write_moved(root, "OLD", "middle", description_target="MIDDLE"),
        write_moved(root, "middle", "Final"),
        write_part(root, "final"),
    ]
    resolver = LDrawMovedAliasResolver(root, parts)

    inspection = resolver.inspect("old")
    resolution = resolver.resolve("OlD")

    assert inspection.is_moved_alias is True
    assert inspection.immediate_target == "middle"
    assert resolution.status == "resolved"
    assert resolution.immediate_target == "middle"
    assert resolution.canonical_part_id == "final"
    assert resolution.alias_chain == ("old", "middle")


def test_cycle_missing_target_and_malformed_moved_file(tmp_path: Path) -> None:
    root = tmp_path / "official"
    parts = [
        write_moved(root, "cycle-a", "cycle-b"),
        write_moved(root, "cycle-b", "cycle-a"),
        write_moved(root, "missing", "not-there"),
        write_moved(root, "malformed", "final", description_target="different"),
        write_part(root, "final"),
    ]
    resolver = LDrawMovedAliasResolver(root, parts)

    assert resolver.resolve("cycle-a").status == "cycle"
    assert resolver.resolve("cycle-a").canonical_part_id == "cycle-a"
    assert resolver.resolve("missing").status == "missing_target"
    assert resolver.resolve("missing").canonical_part_id == "missing"
    assert resolver.resolve("malformed").status == "malformed"
    assert resolver.resolve("malformed").canonical_part_id == "malformed"


def test_normal_part_and_shortcut_are_not_moved_aliases(tmp_path: Path) -> None:
    root = tmp_path / "official"
    normal = write_part(root, "3001")
    shortcut = write_part(root, "shortcut", "~Shortcut assembly")
    (root / shortcut.relative_path).write_text(
        "0 ~Shortcut assembly\n"
        "0 Name: shortcut.dat\n"
        f"1 16 {IDENTITY} 3001.dat\n",
        encoding="utf-8",
    )
    resolver = LDrawMovedAliasResolver(root, [normal, shortcut])

    assert resolver.resolve("3001").status == "unchanged"
    assert resolver.resolve("shortcut").status == "unchanged"
    assert resolver.inspect("shortcut").is_moved_alias is False


def test_transformed_alias_is_valid_and_unsafe_catalog_path_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "official"
    target = write_part(root, "target")
    transformed = write_moved(
        root,
        "transformed",
        "target",
        transform="1 0 0 1 0 0 0 1 0 0 0 1",
    )
    outside = tmp_path / "outside.dat"
    outside.write_text(
        f"0 ~Moved to target\n0 Name: escaped.dat\n1 16 {IDENTITY} target.dat\n",
        encoding="utf-8",
    )
    escaped = OfficialPartRecord("escaped", "~Moved to target", "../outside.dat")
    resolver = LDrawMovedAliasResolver(root, [target, transformed, escaped])

    assert resolver.resolve("transformed").status == "resolved"
    assert resolver.resolve("escaped").status == "malformed"


def test_alias_depth_limit_is_conservative(tmp_path: Path) -> None:
    root = tmp_path / "official"
    parts = [
        write_moved(root, "first", "second"),
        write_moved(root, "second", "final"),
        write_part(root, "final"),
    ]

    resolution = LDrawMovedAliasResolver(root, parts, maximum_depth=1).resolve("first")

    assert resolution.status == "depth_exceeded"
    assert resolution.canonical_part_id == "first"


def test_fixed_color_alias_resolves_but_subpart_target_is_not_physical(
    tmp_path: Path,
) -> None:
    root = tmp_path / "official"
    fixed_color = write_moved(root, "sticker-old", "sticker-new", color_code=47)
    canonical = write_part(root, "sticker-new")
    subpart_alias = write_moved(root, "legacy-subpart", "s/legacy")
    resolver = LDrawMovedAliasResolver(
        root, [fixed_color, canonical, subpart_alias]
    )

    assert resolver.resolve("sticker-old").status == "resolved"
    assert resolver.resolve("sticker-old").canonical_part_id == "sticker-new"
    assert resolver.resolve("legacy-subpart").status == "missing_target"
