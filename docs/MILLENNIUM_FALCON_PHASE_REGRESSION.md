# Millennium Falcon hierarchical-rendering regression

This 2026-06-30 regression used the external `10179 UCS Millenium Falcon.mpd` only as temporary audit input. The MPD is not part of the change and its bytes were not modified.

## Before and after

| Metric | Before | After |
|---|---:|---:|
| Source SHA-256 | `40fcbeff2844d2482a947b3ba2dabbeff63a82b3b809159b84a96e8563296dde` | unchanged |
| Source bytes | 386,933 | unchanged |
| Definitions / expanded occurrences / nodes / depth | 202 / 433 / 5,768 / 3 | unchanged |
| Complete hierarchical root source | 1,124,146 B, type-1 only | 1,410,216 B estimate with direct geometry |
| Normal root strategy | unsafe complete subtree | `local` (`scope_complexity_limit`) |
| Root step-1 source requested by normal metadata | complete root | 1,214 B local source |
| Flattened normal path | selectable and automatically parseable | disabled by typed metadata |
| Flexible hose occurrence | `empty: true`; 177 B; no renderables | `empty: false`; 68,842 B; direct fallback retained |

Root complexity is 5,768 expanded instruction nodes, 433 expanded occurrences, 3,264 expanded direct-geometry commands, and 1,181,705 estimated derived bytes. The complete derived source measured 1,410,216 bytes; classification uses the cheaper deterministic estimate so metadata does not allocate that source. Any one of the configured limits can select local rendering; no browser-memory measurement participates in the decision. A direct request for the unsafe root subtree returns HTTP 409.

Parsing the external source and calculating cold complexity took approximately 195 ms in the development API container; complexity is then cached with the immutable playback graph. Warm summary and root occurrence metadata took 3.8 ms and 4.4 ms respectively in the API probe. Root step 1 keeps its original two local part references, 96-step navigation, and no child attachment at that step.

## Flexible geometry

`occ-000321` (`technicflexSysHose-1.ldr`) remains attached to `occ-000318` at local step 10 and keeps its repeated occurrence identity. Its bounded source contains 64 type-2, 272 type-4, and 416 type-5 commands. A real Node `LDrawLoader` parse completed in 22.053 ms and returned five objects: one mesh, two line objects, and 2,592 geometry vertices. The standalone probe did not preload `LDConfig.ldr`, so it logged material-code 71 warnings; the application loader does preload the local material file.

## Compatibility checks

- Import totals remain 5,162 physical parts, 262 unique part/color rows, and one unresolved/custom-part warning.
- Embedded custom `.dat` definitions still contribute the same 51 graph occurrences and retain existing navigation identity. Their physical BOM omission/warning is unchanged.
- Generated-flex fallback geometry remains rendering-only and does not add BOM rows.
- Root/parent breadcrumbs, attachment steps, repeated labels, and remembered local steps use the unchanged occurrence metadata. Frontend tests cover step restoration helpers, omitted-child messaging, flattened blocking, latest-pending parse coalescing, and LRU reuse/eviction.
- The normal UI code uses only the metadata-provided `mode=local&step=...` URL for this root. It does not request the original source or complete subtree. The complete endpoint is additionally rejected server-side.

No full-root browser or Node parse was launched after the change; this is intentional. The earlier audit already established multi-gigabyte growth and heap exhaustion for that path. Browser interaction was not re-run with automated browser tooling in this environment, so canvas responsiveness is supported by bounded-loader/API probes and UI contract tests rather than a new browser memory measurement.

The temporary API import was deleted normally with HTTP 204; a subsequent detail request returned 404.

## Root step-transition overlap follow-up

The 2026-07-01 follow-up compared the exact metadata-provided local sources for root steps 1 and 2. Step 1 contains two unique manifest IDs, two wrapper definitions, and one placement each for `32531.dat` and `6558.dat`. Step 2 contains four unique IDs and one placement each for `32531.dat`, `6558.dat`, `3703.dat`, and `32532.dat`. Every outer transform token matches `main.ldr`; each wrapper contains only an identity reference, so no transform is applied twice. Fresh real-loader parses produced two and four wrapper groups respectively.

An independent scene-stacking lifecycle defect was corrected, but it did not cause the remaining four-part visual overlap. Cached loader results had been rendered directly as changing React Three Fiber primitives, leaving cache ownership and canvas membership dependent on renderer replacement timing. The corrected viewer uses one stable canvas host. Its layout effect synchronously detaches the old parsed root, detaches a cached root from any former parent, and then attaches exactly one current root. Cache eviction and model changes detach before disposal. Step refreshes retain the stable host and camera controls; changing occurrence or explicitly resetting still refits the camera.

Actual parsed-scene diagnostics after the correction:

| Sequence | Active roots | Active node IDs | Inactive cached parents |
|---|---:|---:|---|
| Fresh step 1 | 1 | 2 unique | `null` |
| Step 1 → 2 | 1 | 4 unique | step 1: `null` |
| Step 1 → 2 → 1 → 2 | 1 | 4 unique | step 1: `null` |
| Step 1 → 2 → 3 → 2 | 1 | 4 unique | steps 1 and 3: `null` |
| Stale step-1 completion | unchanged at 1 | unchanged | stale root: `null` |
| Cache disabled, 1 → 2 → 1 → 2 | 1 | 4 unique | not applicable |

The original four-part source and the derived local source produce identical world matrices and bounds:

| Part | World-space minimum | World-space maximum |
|---|---|---|
| `32531.dat` | `(-40, -4, -60)` | `(40, 24, 60)` |
| `6558.dat` | approximately `(-8.001, 2.199, -80)` | `(8.001, 17.801, -20)` |
| `3703.dat` | `(-300, -4, -60)` | `(20, 24, -40)` |
| `32532.dat` | `(-60, -4, -200)` | `(60, 24, -40)` |

The broad AABB intersections are expected for open Technic frames. The `3703`/second-frame bounds meet at the authored `z=-40` boundary, and the `6558` occupies the valid pin/hole region. There is no exact duplicate transform or additional mesh in the isolated step-2 scene, so these contacts are not evidence of solid penetration.

## Four-part source-geometry diagnosis

A second 2026-07-01 diagnosis imported an exact four-placement reproduction as a temporary model and compared: the original source passed directly to `LDrawLoader`, Bricky flattened playback, and Bricky hierarchical step-2 playback. The temporary source is represented by the committed fixture; no Millennium Falcon bytes or part transform were changed. The fixture remains useful for structural step, transform, and duplicate-identity tests, but its extracted third-party geometry is defective and it is not a trusted visual-accuracy fixture.

All three paths produced four meshes. Raw and flattened playback had 19 objects; hierarchical playback had 23 because its four manifest wrapper groups add no geometry. The four final world matrices, triangle counts, and canonical world-triangle hashes matched across every path:

| Part | Triangles | World-triangle SHA-256 |
|---|---:|---|
| `32531.dat` | 6,228 | `cabd7cf124d0d27bf635a4fea4027a386631ca992155fa252586d753bffb8f9c` |
| `6558.dat` | 2,144 | `64fc74535b37f45b6a21729cf6702224e80dd3decfd76874cf8c0db2338c6692` |
| `3703.dat` | 6,402 | `8751609827cb7f12655bcd3f6c034bf24cf78adb42d466403a35951726500007` |
| `32532.dat` | 9,976 | `57c5600cfdec37798920c92c647b8fba38c838c5f7beedf9e4ac06ba881811cd` |

Every part is `BFC CERTIFY CCW`; triangle totals equal unique canonical triangle totals. Fill materials in all paths use `FrontSide`, `depthTest=true`, `depthWrite=true`, the loader's normal polygon-offset settings, and opaque rendering. This rules out a Bricky-only transform, duplicate, transparency, or incorrect double-sided-material defect.

`32531`/`3703` and `3703`/`32532` each have 37 exactly shared world-space triangles. Four camera directions produced 20–35 and 20–37 exact projected-depth ties respectively, with remaining differences no larger than approximately `2.6e-14`. `6558` shares zero triangles with either frame, so broad frame bounding boxes alone remain unsuitable evidence of pin penetration.

The same incorrect overlap was subsequently reproduced in an independent LDraw editor. That external reproduction, combined with the identical raw/flattened/hierarchical matrices and triangle hashes above, confirms that the overlap is authored in the external MPD rather than introduced by Bricky. Bricky preserves the supplied transforms and applies no global placement-depth or translation workaround. The external model remains valuable for complexity, bounded-navigation, flexible-geometry, and compatibility testing, but not as a visual-accuracy reference.
