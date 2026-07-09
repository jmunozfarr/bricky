# Builder logic defects — investigation record

Intake date: 2026-07-09. Reference model: 42083 Bugatti Chiron (imported,
`totalPartQuantity` 3,531; playback graph 557 occurrences / 9,509 nodes,
render strategy `subtree`, `within_scope_complexity_limits`). Reported by the
user while building on real hardware; reproduced headlessly against the real
packed scenes.

## Reported symptoms

| # | Symptom |
|---|---|
| S1 | Root task shows a single 1/1 step with loose parts (wheels, body edges) plus Chiron/StartKey/Bag task cards. |
| S2 | Chiron task step 1/112 draws individual parts and one `chassisrear` card. |
| S3 | `chassisrear` correct through step 9; step 10 renders "random individual parts" plus the `rearaxle` card. |
| S4 | `rearaxle` fine to 5/17, then the same pattern; two `rearwheelsupport` cards. |
| S5 | Returning from a completed subtask and advancing the parent step does not add the completed subassembly; the loose parts that do appear look like a subset of it. |
| S6 | Later parent steps appear to gradually "add" the subassembly. |
| S7 | The viewer viewport changes size as steps change. |

## What the investigation ruled out

- **Backend graph and manifests are correct.** The chiron manifest has 112
  steps with proper per-step `parts`/`attachments`; `chassisrear` step 10 is
  exactly "0 direct parts + attach `rearaxle`", matching the source MPD.
- **Render strategy is `subtree` everywhere on this model** — the `local`
  child-omission path (`localRenderNotice`) is not involved.
- **The packed scene is complete and fully annotated.** The chassisrear
  packed source contains all 203 subtree occurrences and 3,034 annotated
  parts, including `rearaxle` and its descendants, at every local step.

## Root cause (S1–S6, one mechanism)

`InstructionPresentationController` kept a *fallback* path: any Group not in
the instruction scene index that carried `userData.buildingStep` was
shown/hidden by comparing that number against the **active task's** current
step.

`userData.buildingStep` is stamped by three.js's `LDrawLoader` as a
**flattened, cross-submodel cumulative counter** — the geometry groups inside
`__bricky_node_*` wrappers (and nested submodel internals) carry values from
the *whole parse*, not the active task's local timeline. Direct parts of the
active task happen to have matching numbers (their wrapper and inner group
agree), which is why plain steps looked fine. Everything inside an attached
subassembly has larger numbers, so it stayed hidden until the parent's step
counter grew past them:

- probe on the real chassisrear scene (before the fix): 755 unindexed groups
  hidden at step 9, **647 still hidden at the final step 24** — the model
  never fully assembled;
- at step 10, only the low-numbered slice of `rearaxle` internals showed →
  "random individual parts" (S3/S4/S5), gradually "growing" with the parent
  step (S6), and only step-1-ish slices at task entry (S1/S2).

This is exactly the flattened-vs-hierarchical conflation the architecture
docs warn about (never infer graph semantics from the flattened Three.js
tree).

## Fix

Remove the fallback entirely: indexed entries fully describe hierarchical
step semantics; unindexed groups inherit their indexed ancestor's visibility.
An attached child therefore renders **fully assembled** from its attachment
step onward, including grandchildren.

Verified against the real chassisrear packed scene after the fix:

| step | rearaxle meshes visible | whole-scene meshes visible | mis-hidden groups |
|---|---|---|---|
| 9 | 0 / 1206 | 403 / 2667 | 0 |
| 10 | 1206 / 1206 | 1609 / 2667 | 0 |
| 24 (final) | 1206 / 1206 | **2667 / 2667** | 0 |

Regression tests: `instructionPresentation.test.ts` ("never gates unindexed
geometry by its flattened building step", "shows an attached child complete,
including its own deep internals"). The flattened fallback *mode*
(`buildingSteps.ts`, used when no instruction graph exists) is unaffected —
it never used this controller.

## Source-accurate behaviour (not bugs)

- The 1/1 root step with Chiron/StartKey/Bag cards mirrors the source MPD
  (official sets ship a root model that places the car, start key, and bag in
  one step). With the fix the root now shows the fully assembled model
  instead of loose slices; the cards remain the way into each build task.

## Companion changes in this pass

- S7 fixed: the workspace grid takes a fixed viewport-derived height on
  desktop (side panel scrolls internally) and stacked layouts pin the
  viewport row — verified pixel-identical viewport boxes across steps
  1/9/10/24 on the real Bugatti chassisrear task.
- `/models` restructure: the intermediate model-detail route is retired
  (`/models/:modelId` redirects to the workspace). List cards carry the key
  facts plus View / Download source / Delete; build readiness and the
  per-part coverage list (with inline inventory editing) moved into the
  workspace inspect panel (`ModelCoveragePanel`); import warnings and the
  `?debug=viewer` instruction-graph diagnostic moved with them.

## Exit gate

- Full unit + e2e + axe matrix green.
- User field-check on the Bugatti (real GPU) before merging the branch.
