# Bulk inventory import (native CSV)

Roadmap item 1, Phase A. Import personal inventory in bulk from a native CSV:
dropzone → server-computed dry-run preview → explicit merge strategy → apply.
Nothing is written until the user applies; preview and apply share one
parse→classify→plan code path (`apps/api/app/services/inventory_import.py`),
so what the preview shows is exactly what apply does.

## File format

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
  (`add`|`replace`). Returns known/unknown bucket summaries, up to 500
  enriched preview rows (unknown first), and up to 100 per-line issues.
- `POST /api/inventory/import/apply` — same fields plus `includeUnknown`.
  Re-parses and re-plans server-side (stateless — no preview token), runs
  one batched upsert, returns applied/created/updated/skipped counts.

The UI lives in the inventory page's "Import CSV" dialog
(`apps/web/src/components/inventory/InventoryImportDialog.tsx`).

## Follow-ups (not implemented)

### Phase B — Rebrickable CSV / BrickLink XML (prerequisites ready 2026-07-14)

Per-format adapters produce the same parsed-rows shape as the native CSV and
feed the same plan/apply core; the new ingredient is a rebuildable ID-mapping
table, populated once by an operator CLI (classified like the catalog:
droppable and rebuildable, never referenced by personal rows).

**Verified sample files**, committed under `apps/api/tests/fixtures/` (same
249-row MOC in both formats — used as cross-validating test fixtures; a
correct importer converges both to nearly identical LDraw rows):

- `rebrickable_parts_moc.csv` — Rebrickable MOC parts export. Header
  `Part,Color,Quantity,Is Spare`; Rebrickable colour IDs (Black = 0); print
  suffixes like `32296pr0001`; assembly IDs like `78c07`. The sample has only
  `Is Spare=False` rows — Phase B always imports spares (they are parts the
  user physically owns), reported via a `spareRowCount` in the preview.
- `bricklink_wanted_list.xml` — BrickLink wanted list. Single-line
  `<INVENTORY>` of `<ITEM>` elements with `ITEMTYPE` (`P` throughout the
  sample), `ITEMID`, `COLOR`, `MINQTY`; BrickLink colour IDs (Black = 11);
  print suffixes like `32296pb01`; legacy IDs `x136`/`x346`. Parsers must
  tolerate the optional wanted-list fields absent here (`CONDITION`,
  `NOTIFY`, `REMARKS`, …).

The colour namespaces provably differ (part 32200 is colour `0` in the CSV
and colour `11` in the XML for the same black piece), as do printed-part
suffixes (`pr0001` vs `pb01`) — mapping is mandatory, not optional.

**Mapping data source (verified 2026-07-14).** The public CSV dumps on
<https://rebrickable.com/downloads/> (served from
`cdn.rebrickable.com/media/downloads/`, refreshed daily, no account) do NOT
contain external IDs — checked headers: `colors.csv` =
`id,name,rgb,is_trans,num_parts,num_sets,y1,y2`; `parts.csv` =
`part_num,name,part_cat_id,part_material`; `part_relationships.csv` and
`elements.csv` are internal-only. Rebrickable staff confirm mappings are
API-only (licensing). The source is the **Rebrickable API v3**
(auth: `Authorization: key <KEY>` header or `?key=` query; ~1 request/sec
with small bursts, 429 on breach; `page_size` max 1000):

- `GET /api/v3/lego/colors/?page_size=1000` — every colour in one request,
  each with `external_ids.{BrickLink,LDraw,LEGO,BrickOwl,Peeron}.ext_ids`.
- `GET /api/v3/lego/parts/?page_size=1000` — paginated (~64k parts ≈ 64
  requests), each part with `external_ids.{BrickLink,LDraw,BrickOwl}`
  string arrays; batched `?part_nums=a,b,c` also works for targeted fetches.

**The user's API key is in `.env` as `REBRICKABLE_API_KEY`** (reserved in
`.env.example`, passed through to the api container by both compose files).
Design constraint: the key is used only by the one-time mapping CLI
(`python -m app.cli.<name>`, modelled on `ldraw_library install`) which
downloads and persists the mappings locally; imports never touch the network
at request time, keeping the app offline-first.

Other open decisions for the planning session: unmapped-ID preview bucket UX
(IDs with no LDraw mapping), whether `MINQTY` needs any special treatment
beyond quantity, and relocating the two sample files from `docs/` to test
fixtures.

Suggested opening prompt for a fresh session:

> Read docs/ROADMAP.md, docs/BULK_INVENTORY.md, CLAUDE.md, and
> docs/ARCHITECTURE.md. I want to implement roadmap item 1 Phase B
> (Rebrickable CSV + BrickLink XML import). The sample files and the
> verified mapping-source findings are in docs/BULK_INVENTORY.md; my
> Rebrickable API key is in .env as REBRICKABLE_API_KEY. Audit the relevant
> code and propose a phased plan before writing anything.

### Phase C — "I own set NNNN"

Set data IS in the public dumps (no API key needed): `sets.csv.gz`,
`inventories.csv.gz`, and `inventory_parts.csv.gz` (rows are
`part_num,color_id,quantity,is_spare` per set inventory, in the Rebrickable
namespace). The same operator CLI ingests them into rebuildable tables and a
set number expands—through the Phase B mapping table—into rows feeding the
same preview/apply flow.
