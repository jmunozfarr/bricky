# Refactoring and upgrade plan

Audit date: 2026-07-01. This plan records the agreed phases for the technical,
architectural, and UI/UX refactoring of Bricky. Each phase is independently
shippable and gated by `./scripts/check.sh`. Phases live on `refactor/*`
branches and merge to `main` only when the full gate is green.

The audit verdict: the MVP architecture (service boundaries, immutability,
natural-key isolation, bounded parsing) is sound and is intentionally
preserved. The plan is surgical, not a rewrite.

## Phase summary

Status as of 2026-07-09. Every completed phase is merged to `main`; the
working tree is clean and `./scripts/check.sh` is green.

| Phase | Scope | Estimate | Status |
|---|---|---|---|
| 0 | Baseline: scoped commits, `v0.1.0-mvp` tag, green gate | 0.5 day | ✅ done |
| 1 | Toolchain and CI: ruff, mypy, ESLint, Prettier, GitHub Actions | 1–2 days | ✅ done |
| 2 | 3D viewer stabilization (dedicated bug-fixing phase) | 4–6 days | ✅ done (B1–B9, audit A1–A8; user field-confirmed) |
| 3 | Backend structural refactor | 3–5 days | ✅ done |
| 4 | Backend performance and correctness | 2–4 days | ✅ done |
| 5 | Frontend data layer (TanStack Query + OpenAPI types) | 3–4 days | ✅ done |
| 6 | UI system and UX fixes | 4–6 days | ✅ done (+ immersive fullscreen, assembled-first flow) |
| 7 | Platform and dependency upgrades | 1–2 days | ✅ done |
| 8 | UX feature investments (optional) | 1–2 weeks | ✅ done |

Carried-over follow-ups, none blocking:
- **Builder/viewer e2e in CI**: the specs run on the dev machine but
  self-skip in CI, which has no installed LDraw library (and the repo has no
  git remote yet). Wire the library — or a fixture subset — into CI when a
  remote exists.
- **Phase 2 real-fix backlog** (mitigated, not urgent): move build-mode
  step playback to `BatchedMesh` if per-part draw calls ever lag on real
  GPUs; the three.js upgrade is a no-op until a release past 0.185.1 lands.
- Per-phase detail and gotchas live in the memory note
  `refactoring-plan-progress.md`; bug reproductions in `docs/VIEWER_BUGS.md`.

## Phase 0 — Baseline

- Commit the outstanding working tree in scoped commits (builder feature,
  e2e gate, docs, agent guidance).
- Tag `v0.1.0-mvp`.
- Run `./scripts/check.sh` and record the green baseline.

## Phase 1 — Toolchain and CI

- Python: `pyproject.toml` with ruff (lint + format, line length 100) and
  mypy (with the pydantic plugin); pins added to `requirements.in`/`.lock`;
  all checks run inside the api container.
- Frontend: ESLint 9 flat config (typescript-eslint type-checked,
  `react-hooks`, `jsx-a11y`) plus Prettier; exact-pinned devDependencies;
  all checks run inside the web container.
- `scripts/check.sh` gains lint/format/type steps; README and CLAUDE.md
  document the commands.
- GitHub Actions workflow runs the same compose-based gate on push/PR.

## Phase 2 — 3D viewer stabilization

A dedicated phase: the viewer is the buggiest user-facing surface, so it gets
its own defect burn-down with reproducible gates *before* broader refactors
touch the same code.

1. **Bug intake and reproduction matrix** (`docs/VIEWER_BUGS.md`): collect
   user-reported symptoms plus audit suspects; reproduce each on the
   synthetic fixture and the Millennium Falcon stress model across the three
   e2e browser projects; classify P1–P3 with reproduction steps.
   Audit suspects to verify:
   - camera refit/orbit behavior on occurrence and step changes
     (`ViewerCamera` fit semantics, damping responsiveness);
   - shared-state mutation of cached scenes (`model.rotation.x = Math.PI`
     applied to LRU-cached `Group` instances; mount/detach ordering in
     `ExclusiveInstructionSceneMount`);
   - disposal completeness in `disposeLDrawModel` (textures, conditional-line
     materials) and memory growth across repeated occurrence navigation;
   - WebGL context-loss recovery races (canvas remount vs the persistent
     `sceneHost` group);
   - stale or stuck `refreshing` states in `LatestScopeLoader` supersession;
   - the color-16 material override (`getMaterial("4")` hack) across models
     and themes;
   - step-visibility edge cases: hierarchical presentation vs the flattened
     `buildingSteps` fallback, ghosting on repeated submodel occurrences;
   - `subtree`/`local` strategy transitions surfacing HTTP 409
     `scope_complexity_limit` as raw errors in the UI.
2. **Diagnostics**: extend the `?debug=viewer` panel with renderer statistics
   (draw calls, geometry/texture counts, JS heap, scene-cache entries) so
   defects are observable rather than anecdotal.
3. **Fix in priority order**: one commit per defect, each with a regression
   test (vitest for pure logic, Playwright for interaction). Extend e2e
   beyond `/viewer-demo` to a real builder flow: import a synthetic MPD
   through the API in test setup, then drive occurrence navigation, steps,
   camera presets, and theme switches.
4. **three.js + React Three Fiber upgrade** (moved here from the platform
   phase): bump three r185 to current with `@types/three`, re-verify
   `LDrawLoader` internals (material handling, conditional-line material
   import path), and re-run the full matrix.
   *Checked 2026-07-05: npm latest is three 0.185.1 / fiber 9.6.1 /
   `@types/three` 0.185.0 — exactly what is installed, so there is nothing
   to upgrade to yet. Re-check when a newer three lands; the interaction
   perf work moved to worker parsing and geometry batching instead
   (`docs/VIEWER_BUGS.md` B8/B9).*
5. **Performance regression smoke**: assert the design targets from
   `VISUAL_BUILDER_DESIGN.md` in e2e (step transitions issue no scene or
   library requests; builder-ready budget) using request counting.

Exit gate: reproduction matrix green on Chromium, Firefox, and WebKit; no
known P1/P2 viewer defects; the builder e2e suite runs in CI.

## Phase 3 — Backend structural refactor

- `app/core/config.py` (pydantic-settings); lazy engine creation.
- Split `models_api.py` (1,573 lines) into `app/schemas/` (shared
  `CamelModel` base with `alias_generator=to_camel`), `app/api/models.py`,
  `app/api/instructions.py`; extract build-manifest assembly into
  `services/build_manifest.py`; one home for shared router helpers.
- Seed the `local-default` workspace in an Alembic data migration; remove the
  per-request upsert and all commits from GET handlers.
- Health endpoint uses the SQLAlchemy engine pool.
- Gate: pytest green and an empty OpenAPI schema diff (contract unchanged).

## Phase 4 — Backend performance and correctness

- Cache the LDraw library file index per library fingerprint (currently
  `rglob` of the whole library per pack-cache miss).
- Key the playback cache by `source_sha256` with lazy byte loading (currently
  keyed by full file bytes, re-read and re-hashed per request).
- Scope build-manifest queries to referenced parts/colors (currently loads
  all ~20k catalog parts and the full inventory per request); cache alias
  resolutions per library fingerprint.
- Lock `PackedSourceCache` (threadpool access) and evict per model.
- Functional indexes on `lower(part_id)` for `parts`, `inventory_items`, and
  `model_bom_items`.
- `If-None-Match`/304 handling on source endpoints.
- Gate: cache-behavior unit tests plus before/after timings on the stress
  model.

## Phase 5 — Frontend data layer

- TanStack Query v5: typed query/mutation hooks per API domain; replace the
  hand-rolled `AsyncState` machines, AbortController plumbing, and the
  `inventory/events.ts` bus (query invalidation); keep the `refreshing` UX
  via `placeholderData: keepPreviousData`.
- Generate API types from the FastAPI OpenAPI schema (`openapi-typescript`)
  and add a drift check to the gate.
- Gate: vitest and full e2e green; entry-bundle budget still met.

## Phase 6 — UI system and UX fixes

- Split `styles.css` (2,115 lines) into tokens/base/feature files and
  deduplicate patterns; keep the existing token system.
- Extract shared primitives: `Button`, `Pagination`, `SegmentedControl`,
  `StatusPill`, `EmptyState`, `Alert`, `Dialog`, `Toast`.
- Replace `window.confirm` with an accessible dialog; add toast feedback for
  saves/imports/deletes.
- Upload dropzone with progress; move Viewer demo out of primary navigation;
  remove development language from UI copy; card layout for tables at phone
  widths; persist visual-builder step progress to `localStorage`.
- Gate: axe e2e clean across routes and themes, including a phone viewport.

## Phase 7 — Platform and dependency upgrades

- Python 3.13 → 3.14, Node 22 → 24 LTS, FastAPI/uvicorn/SQLAlchemy/psycopg/
  Playwright to current (Playwright image and package stay in lockstep).
- Nginx: enable gzip (or precompressed assets) and add a Content-Security-
  Policy header.
- Optional: enable the React Compiler in the Vite build.
- The three.js upgrade is handled in Phase 2, not here.

*Done 2026-07-09.* Python 3.14.6 (ruff/mypy targets bumped; the formatter
adopted PEP 758 unparenthesized except clauses), Node 24 LTS, fastapi
0.139.0 (starlette 1.3), uvicorn 0.51.0, psycopg 3.3.4, mypy 2.2.0, nginx
1.30 with gzip and a same-origin CSP (verified by the read-only
`scripts/csp-smoke.mjs` against the prod stack). Already current, so
no-ops: SQLAlchemy 2.0.51, alembic, pydantic, ruff, pytest, httpx,
`@playwright/test` 1.61.1 (image lockstep holds), three 0.185.1,
postgres 18; ESLint stays pinned to 9.x until jsx-a11y supports 10.
React Compiler enabled via plugin-react's `reactCompilerPreset` with
`src/components/ldraw/**` excluded — fully-compiled R3F components
crash-unmounted the builder under parallel e2e stress (they mutate
three.js objects imperatively, the react-hooks/immutability carve-out).

## Phase 8 — UX feature investments (optional)

- Part thumbnails: an operator CLI pre-renders sprites into a derived data
  directory (originals stay immutable); wire into catalog, inventory, BOM,
  and coverage rows.
- Core-loop e2e (import → coverage → builder) on synthetic fixtures; coverage
  reporting; automated perf assertions for the builder targets.
- Printable per-step parts list; optional PWA manifest/offline shell.

*Done 2026-07-09, four user-chosen tracks (the PWA item was dropped in
favour of a builder-logic pass):*

- **Builder logic** (`fix/builder-logic`, user field-confirmed on the
  Bugatti): attached subassemblies now render fully assembled — the
  presentation fallback compared three.js's flattened cross-submodel
  `buildingStep` against the active task's local steps and hid attached
  child geometry (`docs/BUILDER_LOGIC_BUGS.md`). Plus a fixed-size builder
  viewport and the `/models` restructure (detail route folded into the
  list and the workspace inspect panel).
- **Core-loop e2e** (`test/core-loop-e2e`): import → readiness → workspace
  coverage → guided steps → UI delete on the synthetic fixture; the
  coverage flow runs without the LDraw library or catalog (verified against
  a library-less API) so CI executes it. Request-count builder budgets;
  pytest-cov + @vitest/coverage-v8 report-only in `check.sh`; `e2e/` is now
  type-checked.
- **Part thumbnails** (`feat/part-thumbnails`): `scripts/render-thumbnails.sh`
  renders parts through the app's own viewer (`/thumbnail-harness` +
  Playwright image) into derived `data/thumbnails`, served at
  `/api/thumbnails`; wired into catalog/inventory/coverage/step rows with a
  neutral-tile fallback. Individual lazy PNGs instead of the planned sprite
  sheets — simpler and request count is a non-issue locally.
- **Printable parts list** (same branch): `/models/:modelId/print` prints
  one section per distinct submodel definition with per-step part rows and
  a print stylesheet.

## Explicit non-goals

- No async-SQLAlchemy rewrite (no benefit at single-user scale).
- No CSS framework or component library; componentize the existing token CSS.
- No API versioning, authentication, queues, or service splits.
- No changes to import/BOM/coverage semantics.

## Standing constraints

Everything runs through Docker Compose (no host installs); code stays inside
the owning service; imported sources remain immutable; no SaaS runtime
dependencies; commits stay scoped with short imperative subjects.
