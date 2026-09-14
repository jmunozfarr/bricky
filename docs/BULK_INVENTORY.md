# Bulk inventory import

Import personal inventory in bulk: dropzone → server-computed
dry-run preview → explicit merge strategy → apply. Nothing is written until
the user applies; preview and apply share one parse→classify→plan code path
(`apps/api/app/services/inventory_import.py`), so what the preview shows is
exactly what apply does.

All three phases are shipped: A (native CSV), B (Rebrickable CSV / BrickLink
XML, via a locally populated ID-mapping table), and C ("I own set NNNN", via
locally populated set data) — see the bottom of this document for C.

## Phase A: native CSV

```csv
part_id,color_code,quantity
3001,4,2
3070b,71,10
```

- **Columns.** `part_id` (LDraw part ID, ≤64 chars), `color_code`
  (non-negative integer LDraw colour), `quantity` (integer 1…999,999). The
  header row is required; column order is free; header matching is
  case-insensitive after trimming. Extra columns are ignored and reported in
  the preview.
- **Encoding.** UTF-8, with or without a BOM (Excel's "CSV UTF-8" works).
  Other encodings (cp1252, UTF-16, semicolon-delimited regional saves) are
  rejected with one actionable error — re-save as CSV UTF-8 (comma delimited).
- **Caps.** 1 MiB per upload (`INVENTORY_MAX_UPLOAD_BYTES`, HTTP 413 above
  it) and 20,000 data rows (HTTP 422 above it). Blank lines are skipped.

## Semantics

- **Merge strategy** is explicit per import: **add** sums the CSV quantity
  onto the current one; **replace** overwrites it. There is no default —
  the UI always shows which one is active.
- **Per-row problems are data, not errors.** A bad quantity, empty part ID,
  wrong field count, or non-physical colour never fails the upload; the row
  is reported (line number + reason) and skipped. Whole-file problems
  (missing header column, wrong encoding, row/byte caps) fail with 422/413.
- **Colours 16 and 24 are rejected** per row: they are LDraw placeholder
  slots ("current colour" / "edge colour"), not physical colours.
- **Duplicate part+colour rows are summed**, then clamped to 999,999 — the
  same clamp add-strategy results get against existing stock. The preview
  reports how many rows were merged.
- **Quantity 0 is invalid.** Deleting rows via CSV is an explicit non-goal;
  remove rows through the inventory UI.
- **`~Moved to` aliases are canonicalized.** Stale IDs whose library part is
  a moved stub are rewritten to the canonical part (and merged with rows
  naming it); the preview flags them ("Renamed from …"). With no LDraw
  library installed this degrades to identity — the stub ID imports as-is
  and is re-canonicalized on a future import once the library is present.
- **Catalog-unknown rows import** (part not in the catalog, or unknown
  colour code) when "include" is left on (the default). They persist with a
  lowercase part ID and render as "Catalog metadata unavailable" — the same
  orphan handling the inventory already has, since inventory keys off
  natural LDraw identifiers, not catalog foreign keys.
- **Persisted part-ID spelling** never comes raw from the CSV: an existing
  inventory row's spelling wins, then the catalog-canonical spelling, then
  normalized lowercase. This keeps case-variant rows merging into one
  inventory row instead of double-counting coverage.
- **Concurrency is last-write-wins.** Apply re-reads the file and recomputes
  against live values in one transaction (single-user app). Re-applying the
  same file with **add** doubles quantities; with **replace** it is
  idempotent. Rows classified "unchanged" are still written, so their
  `updated_at` bumps.

## Endpoints

- `POST /api/inventory/import/preview` — multipart `file` + `strategy`
  (`add`|`replace`) + optional `format` (`native`|`rebrickable`|`bricklink`,
  auto-detected from the filename extension and, for `.csv`, the header
  shape, when omitted). Returns the resolved `format`, known/unknown bucket
  summaries, up to 500 enriched preview rows (unknown first), and up to 100
  per-line issues.
- `POST /api/inventory/import/apply` — same fields plus `includeUnknown`.
  Re-parses and re-plans server-side (stateless — no preview token), runs
  one batched upsert, returns applied/created/updated/skipped counts. The UI
  passes the `format` the preview response resolved, so preview and apply
  can never disagree about which parser ran.

The UI lives in the inventory page's "Import" dialog
(`apps/web/src/components/inventory/InventoryImportDialog.tsx`).

## Phase B: Rebrickable CSV / BrickLink XML (shipped 2026-07-16)

Per-format parsers (`apps/api/app/services/inventory_import_formats.py`)
produce a shared `ExternalRow` shape for the Rebrickable MOC parts CSV
(`Part,Color,Quantity,Is Spare` header) and the BrickLink wanted-list XML
(`<INVENTORY>` of `<ITEM>` elements: `ITEMTYPE`, `ITEMID`, `COLOR`,
`MINQTY`). `translate_external_rows` converts source-namespace colour IDs to
LDraw colour codes (an unmapped colour is a hard skip — a wrong-but-plausible
LDraw colour is worse than a reported gap) and produces the exact `CsvRow`
shape the native planner already consumes; part-ID translation is composed
into the existing `resolve_aliases` hook used for `~Moved to` resolution
(`apps/api/app/services/inventory_import.py`), so dedup and provenance work
identically across all three formats.

**Spare rows are always imported** (`Is Spare=True` parts are physically
owned), reported via `spareRowCount` in the preview rather than a toggle.
**Unmapped source IDs are strict**: a raw ID absent from the mapping table is
reported `unknownReason: "unmapped"` even if it coincidentally matches the
installed catalog — the mapping table is authoritative once populated. No
special-case code for printed-part suffixes (`pr0001`/`pb01`) or BrickLink
legacy codes (`x136`/`x346`); they map if the Rebrickable API says so and
surface as clean "unmapped" otherwise.

### ID mapping table

`external_part_id_map` and `external_color_map` (`apps/api/app/models.py`)
are rebuildable, droppable, and never referenced by personal rows — same
classification as the catalog. Populated once by
`python -m app.cli.rebrickable_mapping populate` (throttled ~1 req/sec
against the Rebrickable API v3, exponential backoff on 429/5xx, full
replace-in-transaction so a failed run never leaves a partial table);
`... status` reports freshness. The key lives in `.env` as
`REBRICKABLE_API_KEY` and is read only by this CLI — imports never touch the
network at request time.

A Rebrickable part can list *arrays* of BrickLink/LDraw external IDs; every
candidate is stored, with exactly one `is_preferred` per
`(source_system, source_part_id)` chosen by a deterministic rule (exact
match, then same-`part_num` provenance, then lexicographic). Verified
against the live API (2026-07-16): 63,588 parts fetched, 28,935 part-mapping
rows, only ~4% of `(source_system, source_part_id)` groups ambiguous — the
`ambiguous_part_count` the CLI reports.

**Cross-validated against the two committed sample fixtures**
(`apps/api/tests/fixtures/rebrickable_parts_moc.csv` and
`bricklink_wanted_list.xml`, the same 249-row MOC exported both ways): both
formats resolve all 249 rows with zero unknown/unmapped and the same total
quantity (2,466 pieces). Row-level part IDs converge exactly for 243/249
rows; the remaining 6 resolve to an alternate-but-equivalent LDraw mold
variant (e.g. `32123a` vs `32123b`) because Rebrickable's and BrickLink's own
catalogs occasionally diverge on which variant they associate with a given
physical part — genuine upstream data variance, not a mapping defect, and
exactly the ambiguity `ambiguous_part_count` exists to surface.

### Phase C — "I own set NNNN" (shipped 2026-07-16)

Set data comes from three public Rebrickable dumps (no API key —
`sets.csv.gz`, `inventories.csv.gz`, `inventory_parts.csv.gz`), ingested by
`python -m app.cli.rebrickable_mapping populate-sets` into rebuildable
`rebrickable_sets`/`rebrickable_set_parts` tables. `inventory_parts.csv.gz`
is streamed directly into a chunked bulk insert (never materialized in full)
since it carries the per-part BOM for every set and minifig Rebrickable has
ever catalogued — over 1.5M rows. A set number then expands, through Phase
B's forward mapping (`load_preferred_part_mapping`/`load_color_mapping`),
into rows feeding the exact same translate/plan/apply pipeline the
Rebrickable CSV format already uses:
`POST /api/inventory/import/set/preview` / `.../apply` (JSON body, no file,
since there's nothing to upload), reusing
`InventoryImportPreviewResponse`/`InventoryImportApplyResponse` with a
`"set"` format value and optional set metadata.

**Verified against the live dumps (2026-07-16):** `populate-sets` ingested
27,347 sets and 1,322,937 part rows in 35 seconds. `inventories.csv`
contains 44,411 distinct `set_num` values, of which exactly 17,064 are
`fig-NNNNNN` minifig inventories with no row in `sets.csv` — confirmed by
diffing the files directly, not assumed; these are excluded automatically
since the ingest only keeps rows whose `set_num` exists in `sets.csv`.
Previewing the 7,541-piece UCS Millennium Falcon (`75192-1`) resolved 720 of
726 unique part/color rows cleanly (1 not in the installed catalog, 5 with
no Rebrickable→LDraw mapping) — strong real-world confirmation of the whole
pipeline, not just the small synthetic fixtures the test suite uses.

**One winning inventory per set number: highest `version` wins.** ~4.6% of
sets (1,270 of 27,348) have multiple inventory versions (revised BOMs) in
the dump; the ingest resolves to one row per set at populate time, same
philosophy as Phase B's `is_preferred`. This is a **documented working
assumption**, not verified against rebrickable.com's own default behavior —
plausible (higher version numbers should represent corrections) but cheap
to flip later since the table is 100% rebuildable from public dumps.

**Nested sub-inventories are an explicit, visible limitation, not a silent
undercount.** Some sets bundle other sets or list minifigs as components
rather than every part directly in `inventory_parts.csv` for the top-level
inventory (Rebrickable's separate `inventory_sets.csv`/`inventory_minifigs.csv`,
not ingested here). The preview surfaces both the official `sets.csv`
`num_parts` count and the actually-expanded quantity side by side
("Official count: N · Expanded: M") so a gap is visible rather than
silently wrong — resolving nested inventories is left as future scope.

Input normalization: a bare number (`7922`) falls back to the `-1` edition
suffix Rebrickable's own `set_num` convention uses when there's no exact
match, so the common case ("I own set 7922") works without the user typing
the edition suffix.
