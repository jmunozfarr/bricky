# Viewer bug intake and reproduction matrix

Phase 2 of `docs/REFACTORING_PLAN.md`. Every entry must be reproduced (or
ruled out) on both the synthetic viewer fixture (`/viewer-demo`, no LDraw
library required) and the Millennium Falcon stress model
(`docs/MILLENNIUM_FALCON_PHASE_REGRESSION.md`), across the three Playwright
browser projects, before it is fixed. One commit per defect, each with a
regression test or e2e assertion.

## Status legend

- **reported** — symptom collected, not yet reproduced
- **reproduced** — deterministic reproduction steps recorded
- **not-reproduced** — attempted, could not trigger; keep with notes
- **fixed** — commit landed with regression coverage

Priorities: **P1** breaks the viewer or loses user work; **P2** wrong or
misleading rendering/state; **P3** cosmetic or recoverable annoyance.

## User-reported bugs

Collected 2026-07-02. All four were root-caused in code review rather than by
timing measurements, so each fix ships with a regression test that fails on
the pre-fix code. Field confirmation on the Millennium Falcon model is still
pending from the user.

| ID | Symptom | Priority | Status | Fixture | Falcon | Browsers | Repro steps |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | Viewer feels slow overall on heavy models | P2 | fixed | n/a (too small) | expected | all | Orbit or scrub on a large imported model; frame cost stays at full DPR |
| B2 | Drag-to-rotate responds only ~1 in 10 attempts | P1 | fixed | yes (`/viewer-demo`) | yes | all | Wait >300 ms idle, then click-drag; rotation dies after the first pointer move |
| B3 | Ghosted parts barely distinguishable in step focus | P2 | fixed | n/a | yes | all | Open the visual builder past step 1 in "Step focus"; prior parts nearly invisible |
| B4 | Rapid slider scrubbing lags and misses the target step | P1 | fixed | n/a | yes | all | Drag the builder step slider quickly across many steps on a large model |
| B5 | 3D view does not repaint when advancing steps (Next) | P1 | fixed | intermittent | yes (2nd Next) | all | Open the Falcon builder, click Next twice; the second advance leaves the view stale |
| B6 | Builder never shows the full construction ("subparts not added") | P1 | fixed | n/a | yes | all | Falcon root renders `local` (policy) and, with limits raised, `subtree` scenes failed outright on `.dat`-typed submodels |
| B7 | LDCad-exported Technic sets (8386, 42056, 42083) "not properly loading at all" | P1 | fixed | n/a | n/a (LDCad-specific) | all | Open the builder for 42056/42083: scene hangs forever on 404 storms; 42083 root shows an empty view; flex hoses never render anywhere |
| B8 | Browser freezes while a large builder scene opens | P2 | fixed | n/a | yes | all | Open the builder on any big model; the tab is unresponsive until the parse finishes (one ~14 s main-thread task for 3450 in software WebGL) |
| B9 | Rotating full builds is very laggy on high part-count models | P2 | mitigated | n/a | yes | all | Open a full build (3450, 42056, Falcon) and drag; rotation frame times spike past 1 s |

## Audit suspects

Candidate defects flagged during the Phase 0 audit. Each needs verification:
either promote to a reproduced bug or mark not-reproduced with evidence.

| ID | Suspect | Where | Priority | Status |
| --- | --- | --- | --- | --- |
| A1 | Camera refit/orbit misbehaves on occurrence and step changes (fit semantics, damping responsiveness) | `ViewerCamera.tsx` | — | partially fixed — the responsiveness half was B2; fit semantics still unverified |
| A2 | Shared-state mutation of LRU-cached scenes: `model.rotation.x = Math.PI` applied to cached `Group` instances; mount/detach ordering | `LDrawModel.tsx`, `instructionSceneMount.ts` | — | reported |
| A3 | Incomplete disposal in `disposeLDrawModel` (textures, conditional-line materials); memory growth across repeated occurrence navigation | `LDrawModel.tsx` | — | reported |
| A4 | WebGL context-loss recovery races: canvas remount vs the persistent `sceneHost` group | `WebGlLifecycle.tsx` | — | reported |
| A5 | Stale or stuck `refreshing` state on supersession | `boundedSceneLoader.ts` (`LatestScopeLoader`) | — | reported |
| A6 | Color-16 material override (`getMaterial("4")` hack) wrong across models and themes | `LDrawModel.tsx` | — | reported |
| A7 | Step-visibility edge cases: hierarchical presentation vs flattened `buildingSteps` fallback; ghosting on repeated submodel occurrences | `hierarchicalPlayback.ts`, `buildingSteps.ts`, `instructionPresentation.ts` | — | reported |
| A8 | `subtree`/`local` strategy transitions surface HTTP 409 `scope_complexity_limit` as raw errors in the UI | viewer loaders / `VisualBuilderPage` | — | reported |

## Reproduction notes

### B2 — drag-to-rotate responds ~1 in 10 (root cause confirmed in code)

`ViewerCamera`'s change handler calls `performance.regress()`. In
`@react-three/fiber`, `regress()` replaces the store's `performance` object
(`set(state => ({ performance: { ...state.performance, current } }))`).
The controls-creation effect listed that object in its dependencies (via a
whole-store `useThree()` destructure), so the **first change event of a drag
gesture disposed and recreated `OrbitControls` mid-drag**, dropping the
pointer capture. Drags only survived when they started inside the 300 ms
regression-debounce window of a previous interaction, where `regress()`
leaves the object untouched — hence "about 1 in 10".

- Fix: subscribe to individual stable store fields (`camera`, `gl`,
  `invalidate`, `performance.regress`) — commit `fdeb2fc`.
- Regression tests: `ViewerCamera.test.tsx` (controls instance survives a
  regress-driven store update; fails on pre-fix code) and the two-gesture
  drag sequence in `e2e/builder.spec.ts`.

### B1 — overall slowness

Two contributors fixed in this pass:

1. `performance.regress()` had no subscriber, so interaction never lowered
   rendering quality. `AdaptiveViewerDpr` now scales canvas DPR with the
   store's performance factor (builder viewport regresses to 0.5) — commit
   `2415087`.
2. The presentation reapply cost described under B4.

The three.js r185 → current upgrade later in Phase 2 may recover more.

### B3 — ghosts barely distinguishable

Ghost material variants used opacity 0.22 with a 72 % lerp toward gray
`#8d7f83` — nearly invisible on both themes' viewer backgrounds. Now
opacity 0.45 with a 30 % tint, keeping the part's own color dominant;
values are exported constants covered by unit tests — commit `70439bd`.

### B4 — slider scrubbing lags and misses steps

Every `<input type="range">` change event (one per pixel of drag) ran
`InstructionPresentationController.apply()`, which restored **all**
original materials, traversed the entire scene twice, and reallocated
material arrays for every ghosted group. On large scenes this saturated the
main thread, so queued slider events landed late and the viewer "struggled
to select the correct step".

- Fix: applies are now diffed — fallback step groups are precomputed once,
  applied visibility/variant state is tracked per group, and only groups
  whose state changed are touched — commit `a6bf5e8`. Unit tests assert
  zero scene traversals for unchanged applies.
- Transport UX: a numeric step field (immediate for valid input, clamped on
  commit) was added next to Previous/Next; the slider remains as a coarse
  scrubber — commit `53f3c89`. Covered by `VisualBuilderPage.test.tsx` and
  `e2e/builder.spec.ts` (rapid scrub lands on the requested step).

### B5 — 3D view does not repaint when advancing steps (reproduced on the Falcon)

Step changes mutate the Three.js scene imperatively (visibility, materials)
behind a stable `<primitive object={...}>`, which the `frameloop="demand"`
reconciler cannot see — nothing scheduled a frame. Repaints only happened
when an incidental trigger fired: reproduced on the UCS Falcon where the
first Next repainted (parts-panel layout resize) but the second Next left
the canvas stale until the camera was touched.

- Fix: `LDrawModel` and `HierarchicalLDrawModel` now call `invalidate()`
  after every step-visibility/presentation apply and scene mount.
- Regression tests: `LDrawModel.test.tsx` (a step re-render must schedule a
  frame) and consecutive Next-repaint screenshot assertions in
  `e2e/builder.spec.ts`.

### B6 — the full construction never appears (reported as "subparts not added")

Two stacked causes, found by testing the Falcon root at raised complexity
limits:

1. **Policy, not a bug, at default limits**: the Falcon root exceeds all
   four `RENDER_MAX_*` limits (5 768 nodes / 433 occurrences / 3 264 direct
   geometry commands / 1.18 MB), so the root scene uses child-omitting
   `local` rendering: subassembly geometry is deliberately absent and the
   final step only shows root-level parts. Build mode gave no indication of
   this (only Inspect mode did) — a `builder-scope-note` now explains it.
2. **A real serializer bug behind the policy**: with limits raised, the
   `subtree` scene hard-failed ("Not every occurrence mapped to a scene
   group"). Occurrence wrapper files copied the definition's
   `0 !LDRAW_ORG` header; for `.dat`-defined submodels (the Falcon's 50
   bent-hose segments, typed `Subpart`) LDrawLoader flattens such wrappers
   into parent geometry instead of creating the named group the scene index
   requires. Wrappers now always declare `0 !LDRAW_ORG Model` and drop the
   inherited type line (BFC/LDCad meta is kept) — regression-tested in
   `test_occurrence_wrappers_always_declare_model_type`.

With the serializer fixed, the default `RENDER_MAX_*` limits were raised to
8 000 nodes / 600 occurrences / 5 000 direct geometry commands / 2 MiB —
calibrated so the Falcon root renders as a complete subtree. Stress numbers
(headless Chromium, software WebGL, so pessimistic): 31 s one-time scene
parse (then LRU-cached), ~1 s to jump to the last step showing the full
construction, ~1.4 s per step back. Rotation of the full subtree remains
the heaviest interaction; the three.js upgrade later in Phase 2 targets it.

### B7 — LDCad Technic exports don't load (8386, 42056, 42083)

Reported 2026-07-05 as "except Liberty Statue, the others all not properly
loading at all". Two independent causes:

1. **Backslash-named embedded subparts broke scene loads outright.**
   Derived-source reference lines are normalized to forward slashes, but
   embedded definition `0 FILE` headers kept the raw name (LDCad emits
   `s\42056 - 32269s01.dat`). `LDrawLoader` keys embedded files by the
   exact FILE name, so the reference never matched, the loader fell back
   to the part library, 404ed on every search path, and the 42056/42083
   builder scenes hung forever — with no error surfaced in the UI (see
   audit suspect A8). Fixed by normalizing the emitted FILE headers;
   regression-tested in
   `test_embedded_definition_headers_match_normalized_references`.
2. **The complexity policy priced baked flex geometry like part
   references.** LDCad bakes flexible parts (hoses, flex axles) into the
   MPD as raw quad/line commands: 8386 carries 239 246 of them (23.7 MB
   estimated source) while being geometrically lighter than the Falcon,
   whose triangles hide behind part reference nodes. Every scope containing
   a flex part exceeded `RENDER_MAX_DIRECT_GEOMETRY_COMMANDS = 5000`, so
   flex parts could never render at any level, 8386 showed only its root
   skeleton, and the 42083 root (three subassemblies, zero root parts)
   rendered a completely empty view. Budgets are now priced by real cost:
   12 000 nodes / 600 occurrences / 300 000 direct geometry commands /
   32 MiB, admitting 42083 (9 509 nodes, fewer physical parts than the
   Falcon) and 8386 as complete subtrees.

Follow-up (A8): a scene-load failure must surface an error in the builder
instead of an indefinite loading state.

### B8 — the tab freezes while a large builder scene opens (fixed)

`LDrawLoader.parse` is synchronous: the whole derived source builds its
Three.js graph in one main-thread task (~14 s for 3450's 2 874-part scene
in headless software WebGL; shorter but still seconds on real hardware).
Worse, the parse started before React could paint the loading state, so
the tab froze with no feedback from the moment the builder opened.

- First mitigation: `parseLDraw` yields to the next paint before parsing
  so the loading state shows immediately (kept as the no-Worker fallback).
- Fix: parsing now runs in a Web Worker (`ldrawParse.worker.ts`). The
  worker serializes the parsed graph (`ldrawSceneTransfer.ts`) with
  transferable geometry buffers; the main thread rebuilds it against a
  shared palette-preloaded loader, resolving materials by LDraw color code
  and object variant (main/edge/conditional) so the result uses the same
  material instances a main-thread parse would have produced. Shared
  palette materials are exempted from `disposeLDrawModel` (scenes in the
  LRU cache now share them). Measured on the same scenes (headless
  Chromium): worst main-thread task during a builder open dropped from
  14 034 ms (3450) to 266 ms, and 686 ms on 42083's full subtree — the tab
  stays interactive for the whole "Preparing 3D scene" phase.
- The worker bundles its own copy of three.js by design (workers cannot
  share page chunks); `check-bundle.mjs` gives it its own budget.

### B9 — rotating full builds is very laggy (mitigated)

Rotation cost tracks part count, not triangle count: every part carries
its own mesh plus edge and conditional-line `LineSegments`, so blocky
models (3450, 42056, the Falcon) push thousands of draw calls while 8386 —
fewer, geometry-heavy parts — stays smooth. DPR regression alone
(`AdaptiveViewerDpr`) does not help the draw-call-bound case.

- Mitigation: `AdaptiveViewerLines` hides every edge/conditional line
  while a performance regression is active (drag, scrub) and restores them
  on idle. LineSegments visibility is exclusively owned by this component;
  step visibility and presentation variants only write `visible` on
  Groups. Measured on 3450's full build (headless software WebGL, so
  pessimistic): worst rotation stall 15.2 s → 1.2 s; on GPU hardware the
  draw-call reduction is the dominant win.
- Fix for the static case (`inspectMergedView.ts`): inspect mode swaps in
  a merged twin of the scene's meshes — transforms baked into geometry,
  one mesh per distinct material — built lazily on first use (3450:
  2 874 parts → 3 meshes, 4.3 M vertices, 234 ms build) and cached as a
  child of the scene, so LRU disposal covers it. Only meshes are merged
  and only Mesh visibility is toggled: Groups stay with the presentation
  controller, LineSegments with AdaptiveViewerLines, keeping per-part
  edge/conditional lines for at-rest quality. Note the software-WebGL e2e
  environment cannot demonstrate the win — SwiftShader is vertex-bound
  and per-part frustum culling is lost — but real GPUs are draw-call
  bound, which is exactly what the user reported. Correctness verified in
  the browser: full-color merged inspect view, per-part step playback
  restored on mode exit.
- Still open for step playback (build mode at high steps): three.js
  upgrade when a newer release lands; possibly BatchedMesh with
  per-instance visibility if per-part draw calls remain the bottleneck.
