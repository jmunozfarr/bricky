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
