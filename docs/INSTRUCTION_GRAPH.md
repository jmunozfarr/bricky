# MPD instruction graph (phase 1)

This phase defines and diagnoses hierarchical instructions. It does not change the production viewer, generate instructions, edit models, convert PDFs, apply LPub layout, or interpret camera directives.

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

## Intended hierarchical playback

Future hierarchical playback should use an occurrence stack:

1. Play the current occurrence's local steps in source order.
2. When its current parent step reaches a submodel attachment, enter that unique child occurrence.
3. Play all of the child's local steps recursively, then return to the suspended parent step.
4. Replay repeated occurrences independently, even when they share a model definition.
5. If an attachment has no child because of a cycle or limit, report it and continue with the next parent node.

This establishes playback ordering without implementing it in Three.js. It leaves one product decision open: a future viewer may require an explicit interaction for entering/leaving a child, or may advance through the same occurrence stack automatically. Both use the same graph.

## Three different structures

| Structure | Meaning | Current use |
|---|---|---|
| Source hierarchy | Reusable MPD definitions and their authored references | Preserves how the file is organized |
| Hierarchical instruction playback | Unique expanded occurrences plus nested local timelines | Diagnostic API only in this phase |
| Flattened Three.js building-step timeline | `LDrawLoader` groups filtered by `userData.buildingStep <= selectedStep` and one `numBuildingSteps` count | Existing visible viewer; unchanged |

The flattened viewer cannot identify repeated placements as independent playback instances and does not preserve each definition's local timeline as an independently navigable scope. The instruction graph must not be inferred back from the rendered Three.js object tree.

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

## Remaining ambiguities

- LDraw defines source structure and step boundaries, but not a single required UI for entering nested instruction scopes.
- An inherited color can remain undetermined when a root-level color-16 reference has no physical ancestor; the graph preserves `null` rather than inventing a color.
- Primitive, custom-part, and unresolved external-reference classification remains the BOM/catalog parser's responsibility.
- `ROTSTEP` camera behavior, LPub directives, callouts, multi-step page layout, and synthesized attachment/disassembly semantics are outside this phase.
