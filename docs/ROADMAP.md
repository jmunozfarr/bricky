# Roadmap: post-v1 improvements

Status snapshot (2026-07-12): the first idea of the app is complete. All
phases of `REFACTORING_PLAN.md` shipped, the import-warning remediation work
landed (reprocess pipeline, parser fixes, auto-mapping, manual reference
resolutions, Import health panel), and the viewer red-material regression is
fixed. All 8 imported models derive correct BOMs; the only remaining import
warnings are genuine `generated_section_without_parts` gaps (LDCad flexible
elements) awaiting user mapping through the Import health panel.

This document is the backlog for what comes next, in recommended order. Each
item is scoped so a fresh session can pick it up cold: read this file plus
`CLAUDE.md` (hard rules, commands) and `docs/ARCHITECTURE.md` (boundaries,
data classification) before planning. Suggested opening prompt:

> Read docs/ROADMAP.md, CLAUDE.md, and docs/ARCHITECTURE.md. I want to
> implement roadmap item N. Audit the current state of the relevant code and
> propose a phased plan before writing anything.

Working conventions that applied to all recent work and should continue:
one feature per branch, short imperative commits, merge to `main` with
`--no-ff`, backend + web gates green before merge (`./scripts/check.sh`),
OpenAPI types regenerated when routes change (`npm run generate:api`).

Constraints that bear on every item below (details in `CLAUDE.md`):

- Local-first, no SaaS or third-party runtime dependencies. Importing
  **user-provided files** (CSV/XML exports, downloaded data dumps) is fine;
  calling external APIs at runtime is not.
- Personal data (`inventory_items`, `model_bom_items`,
  `model_reference_resolutions`) keys off natural LDraw identifiers
  (part ID + numeric colour code), never FKs into rebuildable catalog tables.
- Imported model originals are immutable; anything derived must be a
  separate row/file.
- Everything runs through Docker Compose; never install toolchains on the
  host.

---

## 1. Bulk inventory input (highest leverage)

> **Status (2026-07-16).** Phases A and B shipped: native CSV import with
> dry-run preview, add/replace strategy, alias canonicalization, and
> unknown-row handling; Rebrickable CSV and BrickLink wanted-list XML import
> via a locally populated Rebrickable-API-backed ID mapping table
> (`python -m app.cli.rebrickable_mapping populate`), cross-validated against
> real sample files — see `docs/BULK_INVENTORY.md`. Phase C ("I own set
> NNNN") is not started; the same mapping table and CLI are its prerequisite
> and are already in place.

**Why.** Coverage/readiness is the app's core promise, but it is only as good
as the inventory behind it, and per-row manual entry does not scale past a
handful of parts. Every other roadmap item compounds on real inventory data.

**What.** Import inventory in bulk from files the user provides:

- Phase A — a native CSV format (documented columns: LDraw part ID, LDraw
  colour code, quantity) with a dropzone UI, dry-run preview (rows parsed /
  rows unknown to catalog / resulting quantity changes) and an explicit merge
  strategy choice (add vs replace per part+colour).
- Phase B — Rebrickable CSV exports and BrickLink wanted-list XML.
- Phase C — "I own set NNNN" → add that set's full inventory, sourced from
  the Rebrickable data dumps as user-downloaded files.

**The crux: identifier mapping.** BrickLink part/colour IDs and Rebrickable
part/colour IDs are different namespaces from LDraw's. Phase A avoids the
problem entirely (native format speaks LDraw). Phases B/C need a local
mapping table populated from user-provided dump files — treat schema
verification of those files as the first design task (do not trust column
layouts from memory; get sample files from the user). Store mappings in a
rebuildable table, classified like the catalog.

**Where.** `apps/api/app/inventory_api.py` (router factory pattern),
`apps/api/app/services/` for the parser (framework-independent, like
`ldraw_model_parser.py`), `apps/web/src/pages/InventoryPage.tsx`, dropzone
precedent in the models upload flow, dialog/toast primitives in
`apps/web/src/components/ui/`.

**Open decisions.** Native CSV column names; whether unknown part IDs import
anyway (natural keys permit it — the catalog page already handles
`catalogAvailable: false`) or are held back in the preview.

## 2. Missing-parts export / shopping list

> **Status (2026-07-16).** Single-model export shipped:
> `GET /api/models/{id}/missing-parts?format=csv|bricklink-xml` and two
> export buttons in the coverage panel. Native CSV round-trips through the
> existing import; BrickLink XML resolves LDraw IDs through item 1's
> mapping table (new reverse lookups in `rebrickable_mapping.py`), dropping
> and reporting a count for rows with no BrickLink match rather than
> guessing. Aggregation across multiple selected models is not built —
> see the note below.

**Why.** Turns "73% covered" from a fact into an action: buy exactly what is
missing.

**What.** Export the missing-parts list for one model — done — and later an
aggregate across selected models ("what do I need to build these three?").

**Where.** The coverage arithmetic lives in
`apps/api/app/services/model_coverage.py`; the export serializers are pure
functions in `apps/api/app/services/missing_parts_export.py` (row records
in, CSV/XML string out — no model ID or session), so an aggregation
endpoint can reuse them unchanged. **Caveat for that future endpoint:**
`calculate_model_coverage` does not merge duplicate `(part, color)`
requirements — each requirement row independently looks up the full owned
quantity, so naively concatenating BOMs from multiple models would
double-count owned stock. The aggregation endpoint must pre-sum required
quantities per `(part, color)` across the selected models before calling
`calculate_model_coverage`, sum owned once, and only then compute
missing = required − available.

## 3. Built-model allocation

**Why.** The builder currently states "pieces are not reserved or consumed";
inventory is a single global pool. Marking a model as *built* should move its
parts from available to in-use so other models' coverage reflects reality.

**What.** A personal `inventory_allocations`-style table (model natural
reference + part ID + colour + quantity), a "Mark as built / dismantled"
action in the model workspace, and coverage math updated to
`available = owned − allocated_to_other_models`. Readiness summary and the
models list must reflect it.

**Design care.** This is a data-model change: think through partial builds,
editing inventory below allocated levels (allow with a warning surface, or
clamp?), deleting an allocated model (cascade frees the parts), and how
allocation interacts with the model's own coverage view. Worth a design
section in `docs/ARCHITECTURE.md` alongside the storage ownership table.

## 4. Import health follow-ups

**Why.** 59 `generated_section_without_parts` warnings remain across 5
models, and the same section stems repeat everywhere
(`technicflexaxle-*`, `technicflexsyshose-*`, `rubberbandround-*`,
`shock-*_springmesh`, `technicribhose-*`). Resolving them one model at a
time works today but is repetitive.

**What.**
- "Apply to other models" on a resolution: copy a `map`/`ignore` resolution
  to every model containing the same source reference, reprocessing each.
  Decide between bulk-copy (keeps the per-model table as sole source of
  truth) and a workspace-level default-resolutions table consulted at parse
  time (more machinery; only worth it if defaults should affect *future*
  imports too).
- Flex-length suggestions in the map dialog: LDCad generated sections carry
  `0 // The path is approx X mm (Y)` comments; the backend could surface the
  parsed length per flagged section so the dialog can pre-rank axle/hose
  parts of matching length instead of relying on a name-stem search.

**Where.** `apps/api/app/api/models.py` (resolution endpoints),
`apps/api/app/services/ldraw_model_parser.py` (section access),
`apps/web/src/components/models/ImportHealthPanel.tsx`.

## 5. Build-mode part checklist

**Why.** At-the-table building: tick off parts as you place them in the
current step. Small state, real UX value.

**What.** A checkbox per row in the step part list, persisted per
model/occurrence/step in localStorage exactly like builder step memory —
follow the `apps/web/src/builder/stepMemory.ts` pattern (personal
device-local convenience state; deliberately not in PostgreSQL).

## 6. LAN / tablet access for the builder

**Why.** The natural place to use the visual builder is a tablet next to the
bricks. The tablet viewport already works (webkit-tablet e2e project); the
blockers are network exposure and trust.

**What.** Production nginx currently binds `127.0.0.1` only
(`compose.prod.yaml`: `127.0.0.1:${PROD_WEB_PORT:-8080}:8080`). Add an
opt-in env (e.g. `PROD_BIND_ADDRESS`) to publish on the LAN, and document
the security stance explicitly: the app has **no authentication** by design,
so LAN exposure means trusting every device on the network — consider an
optional nginx basic-auth layer behind the same env switch. Verify WebGL
performance and touch controls on a real tablet; consider a PWA manifest so
it installs to the home screen.

## 7. Settings / status page

**Why.** Operational state is currently invisible from the UI: library
version, catalog freshness, backup recency all live in CLIs.

**What.** A settings page surfacing existing endpoints
(`/api/library/status`, `/api/catalog/status`, `/api/health`) plus catalog
rebuild and backup triggers as new endpoints wrapping the existing services.
Keep **restore** CLI-only: it is a destructive full replacement and does not
belong behind a button.

---

## Design polish

No dedicated redesign pass is planned. The Phase 6 UI system (primitives,
dialogs, toasts, theming, a11y matrix) is in good shape; treat visual design
as continuous refinement inside each feature above, holding the existing
gates (axe matrix, phone-viewport overflow checks) as the bar.

## Known outstanding user data work (no code required)

The 59 remaining generated-section warnings are resolved through the
existing Import health panel (map each flex section to its real part, or
ignore). Item 4 makes this faster but is not a prerequisite.
