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

- **Phase B — Rebrickable CSV / BrickLink XML.** Blocked on sample export
  files (verify real column layouts first). Needs a rebuildable
  `part_id_mappings` table populated from user-downloaded dumps by an
  operator CLI; per-format adapters then feed the same plan/apply core.
- **Phase C — "I own set NNNN".** Rebrickable set-inventory dumps ingested
  the same way; a set number expands to rows feeding the same preview/apply
  flow.
