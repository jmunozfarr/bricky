# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Bricky is a local-first LEGO parts workspace: it imports LDraw `.ldr`/`.mpd` models, preserves the original bytes, derives a physical bill of materials, tracks personal part inventory, and computes build readiness / missing parts — all offline, no cloud services, no authentication (single hidden `local-default` workspace).

## Hard rules (from AGENTS.md)

- **Never install Node.js, npm, Python, pip, or any project dependency on the host.** Everything runs through Docker Compose. If a command isn't prefixed with `docker compose ...`, it's almost certainly wrong here.
- Keep code inside the service that owns it (`apps/web` vs `apps/api`); don't reach across the boundary except through `/api`.
- Imported LDraw source files are immutable — never modify them in place. If normalization is needed, produce a derived file/row instead.
- No SaaS/third-party runtime dependencies; the app must stay locally runnable.
- English everywhere: code, comments, identifiers, commit messages, docs.
- Naming: `PascalCase` for React components, `camelCase` for TS values, `snake_case` for Python modules/functions.
- TypeScript stays strict, no `any`. Python uses type annotations throughout.
- Commit subjects are short and imperative (`feat: add health status`, `fix: handle database timeout`); keep commits scoped, no drive-by refactors mixed in.

## Commands

Copy `.env.example` to `.env` once before anything else. On Linux also set `LOCAL_UID`/`LOCAL_GID` in `.env` to `id -u`/`id -g` so bind-mounted `data/` stays owned by the host user.

Start the dev stack:

```sh
docker compose up --build
# or: ./scripts/dev-up.sh (detached)
```

- Web (Vite, hot reload): http://127.0.0.1:5173/
- API (Uvicorn, reload): http://127.0.0.1:8000/api/health
- Viewer fixture (no LDraw library required): http://127.0.0.1:5173/viewer-demo

One-time DB/LDraw setup after first `up`:

```sh
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.cli.ldraw_library install
docker compose exec api python -m app.cli.ldraw_catalog rebuild
```

### Tests / lint / build

Full gate (starts required services, runs everything, mirrors CI):

```sh
./scripts/check.sh
```

Equivalent individual commands, all run inside the running containers:

```sh
docker compose exec -T api pytest -q                  # backend tests
docker compose exec -T web npm run test                # vitest (unit)
docker compose exec -T web npm run typecheck            # tsc -b --pretty false
docker compose exec -T web npm run build                 # tsc -b && vite build
docker compose exec -T web npm run check:bundle           # bundle-size budgets
./scripts/e2e.sh                                            # Playwright + axe via compose.e2e.yaml
```

Run a single backend test: `docker compose exec -T api pytest -q tests/test_ldraw_pack.py::test_name`.
Run a single frontend test: `docker compose exec -T web npx vitest run src/path/to/file.test.ts`.
Playwright specs live in `apps/web/e2e/`; config is `apps/web/playwright.config.ts`.

Tests use synthetic fixtures/schemas — they never touch the real installed LDraw library or personal runtime data, so it's safe to run them repeatedly.

### Backup / restore (operator commands, not part of normal dev loop)

```sh
./scripts/backup.sh [--prod]
./scripts/restore.sh --force data/backups/bricky-TIMESTAMP.tar.gz
```

Restore is full replacement of DB + imported models; it refuses to run without `--force` and validates checksums/manifest first.

## Architecture

```
Browser -> Nginx (prod) / Vite (dev) -> FastAPI (/api) -> PostgreSQL 18
                                                  \-> data/models (immutable originals)
                                                  \-> data/ldraw  (official LDraw library)
```

- `apps/web` (React 19 + strict TS + Vite + R3F/Three.js): navigation, forms, rendering, prod static delivery. Talks to the backend **only** via `/api`.
- `apps/api` (Python 3.13 + FastAPI + SQLAlchemy 2 + Alembic): HTTP validation, LDraw install/index, import parsing, coverage math, managed file storage, backup validation.
- PostgreSQL is the sole source of truth for durable state; the filesystem/browser storage never substitutes for it.
- In production, Nginx is the *only* published service; API and Postgres stay on the internal Compose network. In dev, Vite (`5173`) and API (`8000`) are both published directly.

Full detail lives in `docs/ARCHITECTURE.md` (service boundaries, storage ownership table, import sequence diagram, multiuser scaling path) — read it before touching persistence or import flow.

### Backend layout (`apps/api/app`)

- `main.py` — app factory, wires routers.
- `*_api.py` (`catalog_api.py`, `inventory_api.py`, `models_api.py`) — FastAPI routers, each built by a `create_*_router(session_dependency)` factory and mounted under `/api`, `/api/inventory`, `/api/models` respectively.
- `models.py` — SQLAlchemy ORM models.
- `database.py` — session/engine setup.
- `services/` — the actual domain logic, framework-independent where possible:
  - `ldraw_library.py` / `ldraw_catalog.py` / `ldraw_metadata.py` — installing and indexing the official LDraw Parts Library.
  - `ldraw_model_parser.py` / `model_import.py` — parsing uploaded `.ldr`/`.mpd` into a physical BOM (recursive MPD resolution, color-16 inheritance, quantity multiplication).
  - `ldraw_aliases.py` — canonicalizing official `~Moved to` aliases on import only.
  - `instruction_graph.py` / `instruction_playback.py` — the separate hierarchical MPD instruction graph used for step-by-step visual playback (see below); never persisted, never feeds the physical BOM.
  - `ldraw_pack.py` — packaging/serving parts for the viewer.
  - `model_coverage.py` — build-readiness / missing-parts arithmetic (available = min(required, owned), half-up percentages).
  - `local_workspace.py` — resolves the single `local-default` workspace.
  - `cli/` — operator CLIs invoked via `python -m app.cli.<name>` (`ldraw_library`, `ldraw_catalog`, `backup`).

Key invariant: `inventory_items` and `model_bom_items` key off **natural LDraw identifiers** (part ID + numeric color), not foreign keys into the rebuildable catalog tables (`parts`, `ldraw_colors`). This lets the catalog be dropped and rebuilt without touching personal inventory or imported-model data.

### Frontend layout (`apps/web/src`)

- `pages/` — route-level components (`CatalogPage`, `InventoryPage`, `ModelsPage`, `ModelDetailPage`, `VisualBuilderPage`, `ViewerDemoPage`). 3D/viewer code is lazy-loaded so it doesn't bloat the overview/list bundles.
- `components/ldraw/` — the Three.js/R3F viewer stack: `LDrawModel.tsx`/`LDrawViewer.tsx` (rendering), `ViewerCamera.tsx`, `ViewerToolbar.tsx`, `WebGlLifecycle.tsx` (WebGL context recovery), `hierarchicalPlayback.ts` (occurrence-scoped step playback), `boundedSceneLoader.ts`/`instructionSceneMount.ts`/`instructionSceneIndex.ts` (bounded, serialized Three.js parsing since parses can't be cancelled), `viewerQuality.ts` (adaptive rendering quality), `buildingSteps.ts` (flattened-timeline fallback mode), `instructionPresentation.ts`.
- `api/` — typed fetch clients (`catalog.ts`, `inventory.ts`, `models.ts`, `client.ts`) — the only sanctioned way for the UI to reach the backend.
- `theme/` — light/dark ("oxblood") theme handling; `public/theme-init.js` applies the theme before React mounts to avoid flash.

### The two instruction/graph structures — don't conflate them

There are three distinct structures around imported models (`docs/INSTRUCTION_GRAPH.md`, `docs/ARCHITECTURE.md`):

1. **Physical BOM** (`model_import.py`, persisted `model_bom_items`) — flattened canonical part/color quantities used for inventory coverage. Only real physical parts; primitives/subparts/edges excluded.
2. **Hierarchical instruction graph** (`instruction_graph.py`/`instruction_playback.py`, never persisted) — occurrence-based graph distinguishing repeated placements of the same MPD submodel as independent playback instances, with local per-submodel step timelines. This is what `VisualBuilderPage`/hierarchical playback in the frontend consumes.
3. **Flattened Three.js building-step timeline** (`buildingSteps.ts`) — an explicit fallback mode that just filters `LDrawLoader` groups by `userData.buildingStep`; it cannot distinguish repeated placements.

Never infer graph semantics from the flattened Three.js object tree, and never let instruction-graph/playback code write into the physical BOM tables — it's rendering/navigation-only, defined separately from parsing that feeds inventory coverage.

### Complexity/safety policy for rendering

A centralized complexity policy decides between complete `subtree` rendering and child-omitting `local` rendering for large roots; unsafe roots are blocked from automatic flattened parsing rather than silently degraded. See `docs/VIEWER_STABLE_RELEASE.md` for the interaction/browser/accessibility gates this policy has to satisfy, and `docs/MILLENNIUM_FALCON_PHASE_REGRESSION.md`/`docs/VISUAL_BUILDER_DESIGN.md` for the stress-test model and visual-builder design rationale behind it.

## Data classification (see `docs/ARCHITECTURE.md` for full table)

| Storage | Classification | Recovery |
|---|---|---|
| PostgreSQL volume | Personal + rebuildable metadata | Restore `database.dump` |
| `data/models` | Personal, immutable originals | Included in backup |
| `data/ldraw` | Rebuildable upstream library | Reinstall + reindex |
| `data/backups` | Portable backup archives | N/A |

`docker compose down --volumes` permanently deletes inventory/model metadata — never run it casually.
