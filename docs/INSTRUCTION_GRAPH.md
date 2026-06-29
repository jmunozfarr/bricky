# MPD instruction graph and hierarchical playback

Phase one defines and diagnoses hierarchical instructions. Phase two uses that stable graph for interactive occurrence-local playback while retaining the original flattened viewer as an explicit fallback. Bricky does not generate MPDs, generate instructions, edit models, or convert instruction PDFs. It also does not apply LPub layouts/callouts or camera directives.

## Supported source subset

The framework-independent graph parser supports:

- LDR files and MPD `0 FILE` / `0 NOFILE` sections;
- type-1 part and embedded-submodel references;
- the type-1 translation, 3×3 local matrix, and color code;
- color `16` inheritance through occurrence ancestry;
- `0 STEP` and `0 ROTSTEP` as local step boundaries;
- repeated and transformed occurrences of one definition;
- recursive references, represented as a stopped attachment plus a structured issue.

Type-2 through type-5 geometry, comments, and other meta commands do not create instruction nodes. `ROTSTEP` starts a step but its rotation/camera payload is intentionally ignored. External type-1 references are graph leaves; the graph parser does not decide whether they are official parts, primitives, aliases, or missing files. Those catalog and physical-BOM decisions remain in the existing BOM parser.

Empty authored steps are retained in a model definition. Step numbers are one-based. MPD names are normalized case-insensitively with POSIX separators for reference matching, while the declared section name remains the displayed `sourceSubmodelName`.

## Representation

The graph has two deliberately separate layers:

1. A **model definition** exists once per source section. It owns its local steps and ordered type-1 nodes. Nested step definitions therefore stay attached to the source submodel rather than being copied into a global timeline.
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
5. Before the parent attachment step the child subtree is hidden. At and after that step the complete child subtree appears at the authored transform.
6. Entering a child loads only that occurrence subtree with the selected occurrence at local origin. Returning to the parent restores the parent's session-local step.

Playback progress is React session state and is not persisted. Jumping forward may show an attached child as complete even if the user did not enter it; this is navigation, not build enforcement. Attachment has no animation.

## Three different structures

| Structure | Meaning | Current use |
|---|---|---|
| Source hierarchy | Reusable MPD definitions and their authored references | Preserves how the file is organized |
| Hierarchical instruction playback | Unique expanded occurrences plus nested local timelines | Default imported-model mode for valid graphs |
| Flattened Three.js building-step timeline | `LDrawLoader` groups filtered by `userData.buildingStep <= selectedStep` and one `numBuildingSteps` count | Explicit fallback mode |

The flattened viewer cannot identify repeated placements as independent playback instances and does not preserve each definition's local timeline as an independently navigable scope. The instruction graph must not be inferred back from the rendered Three.js object tree.

## Rendering and mapping architecture

Inspection of the Three.js `LDrawLoader` scene showed that non-primitive submodels retain filename and transform data, but two identical repeated references have no stable source identity beyond sibling order. Primitive geometry is also merged upward. Directly matching the original scene tree to expanded occurrence IDs would therefore require a fragile ordering heuristic.

Bricky instead returns an in-memory derived MPD for one active occurrence subtree. It is never persisted. The response:

- places the active occurrence at local origin;
- rewrites submodel sections to unique `__bricky_occ_...` names;
- wraps local part references in unique `__bricky_node_...` model sections;
- preserves authored local transforms and effective colors;
- keeps official part filenames safe and resolvable through `/api/ldraw/`;
- contains a compact `0 !BRICKY` manifest mapping scene names to definition, occurrence, parent, local step, attachment step, and traversal position.

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
GET /api/models/{model_id}/instruction-occurrences/{occurrence_id}/source
```

The summary selects hierarchical or flattened mode. Occurrence metadata contains breadcrumbs, boundaries, one current-step child page (maximum 100; UI default 50), repeated-definition positions, and the scene URL. Unknown or foreign occurrences return 404. Derived source URLs expose no filesystem paths.

Immutable parsed graph data is held in a bounded process cache keyed by source identity. The browser caches occurrence/step metadata for the mounted viewer, cancels superseded metadata and source requests where the loader permits, and keeps a scope source stable across local-step changes. The UI paginates immediate children and never creates one DOM node per scene object. The developer tree stays closed and unloaded by default.

## Fallback conditions

Hierarchical mode is the default only when graph expansion completed without issues. Cycles, configured safety limits, malformed graph references, unsafe render references, or graph parsing errors select flattened mode and show a reason. The mode selector always preserves flattened playback; users can also switch to it from a valid hierarchy. A derived-scene assertion or loader error is shown as a structured hierarchical rendering error, and flattened mode remains available.

## Safety limits and issues

Defaults are configurable through Compose environment variables:

| Variable | Default |
|---|---:|
| `INSTRUCTION_GRAPH_MAX_NESTING_DEPTH` | 32 |
| `INSTRUCTION_GRAPH_MAX_EXPANDED_OCCURRENCES` | 10,000 |
| `INSTRUCTION_GRAPH_MAX_INSTRUCTION_NODES` | 100,000 |

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

One development-container/Node run on 2026-06-29 recorded:

| Physical occurrences | Summary | Root metadata | Root scene source | Initial API | Loader parse | Three.js objects | Approx. Node heap delta |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 133 B | 8,848 B | 33,729 B | 22.293 ms | 34.995 ms | 401 | 7,159,776 B |
| 1,000 | 133 B | 8,900 B | 338,932 B | 94.541 ms | 181.964 ms | 4,001 | 35,370,528 B |
| 5,000 | 133 B | 8,900 B | 1,702,933 B | 477.061 ms | 696.429 ms | 20,001 | 47,888,104 B |

Changing to a one-part child scope took 6.6–9.3 ms through the cached API and 0.5–1.0 ms for the local Node loader diagnostic. The heap number is a Node/Vitest proxy, not a browser heap guarantee. Network, WebGL upload, and device-specific frame costs are not represented. No timing or memory value is a test threshold.

## Remaining ambiguities

- An inherited color can remain undetermined when a root-level color-16 reference has no physical ancestor; the graph preserves `null` rather than inventing a color.
- Primitive, custom-part, and unresolved external-reference classification remains the BOM/catalog parser's responsibility.
- Aborted `LDrawLoader` internal part fetches cannot all be cancelled, but superseded results are ignored and disposed.
- Derived source size necessarily scales with the active render subtree even though navigation metadata stays bounded.
- `ROTSTEP` camera behavior, part animation, LPub directives, callouts, multi-step page layout, substitutions, `.io`, GLB, PDF conversion, and synthesized attachment/disassembly semantics remain outside scope.
