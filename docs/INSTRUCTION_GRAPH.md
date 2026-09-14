# MPD instruction graph and hierarchical playback

Phase one defines and diagnoses hierarchical instructions. Phase two uses that stable graph for interactive occurrence-local playback. The current phase preserves authored direct geometry and bounds rendering independently from navigation metadata. Bricky does not generate MPDs, generate instructions, edit models, or convert instruction PDFs. It also does not apply LPub layouts/callouts or camera directives.

## Supported source subset

The framework-independent graph parser supports:

- LDR files and MPD `0 FILE` / `0 NOFILE` sections;
- type-1 part and embedded-submodel references;
- the type-1 translation, 3×3 local matrix, and color code;
- color `16` inheritance through occurrence ancestry;
- `0 STEP` and `0 ROTSTEP` as local step boundaries;
- repeated and transformed occurrences of one definition;
- direct type-2 lines, type-3 triangles, type-4 quadrilaterals, and type-5 conditional lines;
- direct-geometry color tokens, coordinates, definition identity, local step, and source order;
- safe render metadata required by direct geometry, including BFC and LDCad fallback comments;
- recursive references, represented as a stopped attachment plus a structured issue.

Type-2 through type-5 commands are drawable definition-local content. They do not create physical BOM items, child occurrences, or synthetic type-1 references. `ROTSTEP` starts a step but its rotation/camera payload is intentionally ignored. External type-1 references are graph leaves; the graph parser does not decide whether they are official parts, primitives, aliases, or missing files. Those catalog and physical-BOM decisions remain in the existing BOM parser.

Empty authored steps are retained in a model definition. Step numbers are one-based. MPD names are normalized case-insensitively with POSIX separators for reference matching, while the declared section name remains the displayed `sourceSubmodelName`.

## Representation

The graph has two deliberately separate layers:

1. A **model definition** exists once per source section. It owns its local steps, ordered type-1 nodes, direct geometry, and safe render metadata. Nested step definitions therefore stay attached to the source submodel rather than being copied into a global timeline.
2. A **model occurrence** exists once per expanded placement. It has a stable ID, parent occurrence, source definition, local transform, effective inherited color, depth, traversal order, attachment step, and child occurrence IDs. Repeated references to one definition always produce distinct occurrences.

Expanded instruction nodes bind a definition node to an occurrence. A submodel attachment node belongs to the parent occurrence and uses the parent's local step number; its `childOccurrenceId` points to the placed child. A part node belongs to the occurrence whose definition contains that part. The global node list follows deterministic depth-first preorder: emit an attachment, traverse that child, then resume the parent.

The root is `occ-000001`, has depth zero, identity local transform, no parent, no attachment step, and no effective inherited color. IDs and traversal order are deterministic for identical source bytes and limits; they are diagnostic identifiers, not persisted database identities.

`instructionNodeCount` counts expanded type-1 nodes, including both physical-reference leaves and submodel attachments. `maximumNestingDepth` is the deepest occurrence actually expanded, with the root at zero.

## Hierarchical playback semantics

Hierarchical playback uses an occurrence scope:

1. Play the current occurrence's local steps in source order.
2. When its current parent step reaches a submodel attachment, enter that unique child occurrence.
3. Play all of the child's local steps recursively, then return to the suspended parent step.
4. Replay repeated occurrences independently, even when they share a model definition.
5. Before the parent attachment step the child subtree is absent or hidden. At and after that step the complete child subtree appears at the authored transform in `subtree` mode.
6. Entering a child loads only that occurrence subtree with the selected occurrence at local origin. Returning to the parent restores the parent's session-local step.

Playback progress is React session state and is not persisted. Jumping forward may show an attached child as complete even if the user did not enter it; this is navigation, not build enforcement. Attachment has no animation.

## Three different structures

| Structure | Meaning | Current use |
|---|---|---|
| Source hierarchy | Reusable MPD definitions and their authored references | Preserves how the file is organized |
| Hierarchical instruction playback | Unique expanded occurrences plus nested local timelines | Default imported-model mode for valid graphs |
| Flattened Three.js building-step timeline | `LDrawLoader` groups filtered by `userData.buildingStep <= selectedStep` and one `numBuildingSteps` count | Explicit fallback mode |

The flattened viewer cannot identify repeated placements as independent playback instances and does not preserve each definition's local timeline as an independently navigable scope. The instruction graph must not be inferred back from the rendered Three.js object tree.

## Render strategies

Each occurrence has a deterministic recommendation:

| Strategy | Canvas content | Navigation metadata |
|---|---|---|
| `subtree` | Active definition through its selected step plus complete already-attached child subtrees | Breadcrumbs, parent/root links, and child attachments |
| `local` | Active definition's own type-1 content and direct geometry through its selected step; embedded custom definitions needed by that local content are included | The same metadata, including children omitted from the canvas |

`local` does not mean the assembly is geometrically complete. The UI explicitly says that completed child geometry is omitted for memory safety, while attachment steps and child entry remain semantically correct.

## Rendering and mapping architecture

Inspection of the Three.js `LDrawLoader` scene showed that non-primitive submodels retain filename and transform data, but two identical repeated references have no stable source identity beyond sibling order. Primitive geometry is also merged upward. Directly matching the original scene tree to expanded occurrence IDs would therefore require a fragile ordering heuristic.

Bricky instead returns an in-memory derived MPD for one active occurrence subtree. It is never persisted. The response:

- places the active occurrence at local origin and restores its inherited current/edge color context when direct geometry requires it;
- rewrites submodel sections to unique `__bricky_occ_...` names;
- wraps local part references in unique `__bricky_node_...` model sections;
- preserves authored local transforms and effective colors;
- keeps official part filenames safe and resolvable through `/api/ldraw/`;
- emits direct commands in their source definition, relative order, coordinates, and local step without rewriting them as references;
- contains a compact `0 !BRICKY` manifest mapping scene names to definition, occurrence, parent, local step, attachment step, traversal position, and render strategy.

The typed browser scene index maps `Group.name` to these unique manifest identities and asserts that every occurrence and local part maps exactly once. It never uses sibling array position. Hierarchical visibility resets loader group visibility, then applies graph-local steps and parent attachment steps; flattened `userData.buildingStep` values are not hierarchical truth. Geometry/material cleanup remains the existing traversal-based disposal path.

## Playback API and payload strategy

The full diagnostic graph remains available but is not fetched during normal model-detail loading:

```text
GET /api/models/{model_id}/instruction-graph
```

Normal playback uses:

```text
GET /api/models/{model_id}/instruction-playback
GET /api/models/{model_id}/instruction-occurrences/{occurrence_id}?step={step}&childOffset={offset}
GET /api/models/{model_id}/instruction-occurrences/{occurrence_id}/source?mode={subtree|local}&step={step}
```

The summary and occurrence responses expose the recommended/selected strategy, reason, complexity values, flattened-rendering permission, and an explicit step/mode source URL. Occurrence metadata still contains breadcrumbs, boundaries, one current-step child page (maximum 100; UI default 50), repeated-definition positions, and child attachment data in both strategies. Unknown or foreign occurrences return 404; invalid modes return 422; an unsafe subtree request returns 409. Derived source URLs expose no filesystem paths.

Immutable parsed graph data is held in a bounded process cache keyed by source identity. The browser caches occurrence/step metadata for the mounted viewer and preserves fetch cancellation. Three.js parsing itself cannot be cancelled after it begins, so bounded parses run one at a time; rapid changes retain only the newest pending scope, stale completed scenes are disposed, and successful scenes use a three-entry LRU cleared when the model changes. Cached scene ownership is separate from canvas membership: one stable canvas host synchronously detaches the prior parsed root before attaching the next, and every inactive cached root is parentless. The UI paginates immediate children and never creates one DOM node per scene object. The developer tree stays closed and unloaded by default.

Imported and occurrence-derived playback use normal `LDrawLoader` material and depth behavior. Derived sources preserve authored placement transforms exactly; Bricky does not introduce renderer offsets to conceal overlap or contact defects in an imported model.

## Fallback conditions

Hierarchical mode is the default when graph expansion completed without issues. Small compatible scopes retain complete-subtree rendering and the explicit flattened option. A model whose root exceeds render limits starts in bounded `local` mode, disables normal flattened loading, and directs the user through hierarchical occurrences. Graph failures may still use flattened fallback only when metadata says full-model rendering is within policy. A derived-scene assertion or loader error remains a structured rendering error.

## Safety limits and issues

Defaults are configurable through Compose environment variables:

| Variable | Default |
|---|---:|
| `INSTRUCTION_GRAPH_MAX_NESTING_DEPTH` | 32 |
| `INSTRUCTION_GRAPH_MAX_EXPANDED_OCCURRENCES` | 10,000 |
| `INSTRUCTION_GRAPH_MAX_INSTRUCTION_NODES` | 100,000 |

Rendering has a separate centralized safety policy:

| Variable | Default |
|---|---:|
| `RENDER_MAX_EXPANDED_INSTRUCTION_NODES` | 4,000 |
| `RENDER_MAX_EXPANDED_OCCURRENCES` | 250 |
| `RENDER_MAX_DIRECT_GEOMETRY_COMMANDS` | 2,000 |
| `RENDER_MAX_DERIVED_SOURCE_BYTES` | 524,288 |

The subtree recommendation changes to `local` when any value is greater than its limit; equality remains allowed. The byte value is a deterministic complete-step estimate based on manifest, wrapper, step, meta, and geometry sizes; classification does not allocate the complete source. These are conservative safety-policy values based on project diagnostics, not universal hardware guarantees, and browser memory measurements are not decision inputs. The 100-piece synthetic scope remains `subtree`; 1,000- and 5,000-piece generated roots select `local`; the audited 5,768-node root also selects `local`.

Expansion is iterative and bounded. A cycle, depth limit, occurrence limit, or node limit returns the partial deterministic graph with `truncated: true` and a structured issue. The source definitions are still available for diagnosis. Limits affect only the diagnostic graph; they do not alter the stored source or existing BOM.

The diagnostic endpoint is:

```text
GET /api/models/{model_id}/instruction-graph
```

It parses the preserved source on demand and does not persist a second representation. The model detail page exposes it only in a closed-by-default **Developer diagnostic** panel; opening the panel does not alter viewer state.

## Synthetic corpus

Fixtures are under `apps/api/tests/fixtures/instruction_graph/`; the generated repeated fixture is in `apps/api/tests/instruction_fixture_factory.py`.

| Fixture | Definitions | Expanded occurrences | Instruction nodes | Depth | Physical BOM quantity |
|---|---:|---:|---:|---:|---:|
| Flat steps | 1 | 1 | 3 | 0 | 3 |
| One stepped submodel | 2 | 2 | 3 | 1 | 2 |
| Nested stepped submodels | 3 | 3 | 5 | 2 | 3 |
| Repeated submodel | 2 | 3 | 4 | 1 | 2 |
| Transformed occurrences | 2 | 3 | 4 | 1 | 2 |
| Explicit attachment steps | 2 | 3 | 5 | 1 | 3 |
| Direct generated hose fallback | 2 | 2 | 2 | 1 | 1 |
| Recursion cycle | 3 | 3 | 3 | 2 | 0 |
| Excessive nesting | 6 | 6 at defaults | 6 | 5 | 1 |
| Generated repeated model (`N` parts) | 2 | `N + 1` | `2N` | 1 | `N` |

Tests verify every fixture, definition-local steps, distinct occurrences, parent attachment ownership, transforms, colors, deterministic traversal, safe limits/cycles, and unchanged BOM quantities.

## Benchmark-style diagnostics

Run the non-threshold diagnostics inside Compose:

```sh
docker compose exec -T api pytest -q tests/test_instruction_graph_diagnostics.py -s
```

One development-container run on 2026-06-29 recorded:

| Physical occurrences | Parse duration | Expanded occurrences | Nodes | Depth | JSON output size |
|---:|---:|---:|---:|---:|---:|
| 100 | 2.760 ms | 101 | 200 | 1 | 112,914 bytes |
| 1,000 | 31.932 ms | 1,001 | 2,000 | 1 | 1,127,818 bytes |
| 5,000 | 138.670 ms | 5,001 | 10,000 | 1 | 5,655,818 bytes |

Durations are observations, not pass/fail thresholds. Tests assert structural counts only, so slower hosts do not fail.

### Phase-two playback diagnostics

Run the API and real-loader diagnostics inside Compose:

```sh
docker compose exec -T api pytest -q tests/test_instruction_playback_diagnostics.py -s
docker compose exec -T web npm run test -- src/components/ldraw/instructionPlaybackDiagnostics.test.ts
```

The raw loader stress fixture intentionally bypasses the API policy. A 2026-06-30 run recorded:

| Physical occurrences | Summary | Root metadata | Root scene source | Initial API | Loader parse | Three.js objects | Approx. Node heap delta |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 407 B | 9,167 B | 33,708 B (`subtree`) | 25.112 ms | 36.626 ms | 401 | 7,386,224 B |
| 1,000 | 401 B | 9,208 B | 176 B (`local`) | 61.679 ms | 198.221 ms raw stress source | 4,001 raw | 35,766,064 B raw |
| 5,000 | 403 B | 9,210 B | 176 B (`local`) | 303.641 ms | 694.985 ms raw stress source | 20,001 raw | 171,096,480 B raw |

Changing to a one-part child scope took 6.6–9.3 ms through the cached API and 0.5–1.0 ms for the local Node loader diagnostic. The heap number is a Node/Vitest proxy, not a browser heap guarantee. Network, WebGL upload, and device-specific frame costs are not represented. No timing or memory value is a test threshold.

## Remaining ambiguities

- An inherited color can remain undetermined when a root-level color-16 reference has no physical ancestor; the graph preserves `null` rather than inventing a color.
- Primitive, custom-part, and unresolved external-reference classification remains the BOM/catalog parser's responsibility.
- Once `LDrawLoader.parse` begins there is no true cancellation; serialization, latest-pending coalescing, stale disposal, and the LRU contain rather than eliminate that work.
- Local rendering intentionally omits attached child geometry from the canvas; it does not alter attachment navigation or physical BOM interpretation.
- Custom physical-part BOM warnings/omission and generated-flex BOM behavior are unchanged. Direct geometry affects rendering only.
- `ROTSTEP` camera behavior, part animation, LPub directives, callouts, multi-step page layout, substitutions, `.io`, GLB, PDF conversion, and synthesized attachment/disassembly semantics remain outside scope.

No third-party model geometry is committed.
