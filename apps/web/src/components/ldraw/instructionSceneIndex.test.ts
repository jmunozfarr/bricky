import { describe, expect, it } from "vitest";
import { LineSegments, Mesh } from "three";

import { parseInstructionScopeText } from "./LDrawModel";
import { applyInstructionSceneVisibility } from "./instructionSceneIndex";

const source = `0 !BRICKY DERIVED_SOURCE 1
0 !BRICKY ROOT occ-000001
0 !BRICKY OCCURRENCE occ-000001 - 0 1 bWFpbi5sZHI
0 !BRICKY OCCURRENCE occ-000002 occ-000001 2 2 bW9kdWxlLmxkcg
0 !BRICKY OCCURRENCE occ-000003 occ-000001 3 3 bW9kdWxlLmxkcg
0 !BRICKY PART node-000003 occ-000002 1 2
0 !BRICKY PART node-000005 occ-000003 1 4
0 Name: __bricky_occ_000001.ldr
0 STEP
1 16 10 0 0 1 0 0 0 1 0 0 0 1 __bricky_occ_000002.ldr
0 STEP
1 16 -10 0 0 0 -1 0 1 0 0 0 0 1 __bricky_occ_000003.ldr
0 FILE __bricky_occ_000002.ldr
1 16 0 0 0 1 0 0 0 1 0 0 0 1 __bricky_node_000003.ldr
0 FILE __bricky_occ_000003.ldr
1 16 0 0 0 1 0 0 0 1 0 0 0 1 __bricky_node_000005.ldr
0 FILE __bricky_node_000003.ldr
0 !LDRAW_ORG Model
1 16 0 0 0 1 0 0 0 1 0 0 0 1 triangle.dat
0 FILE __bricky_node_000005.ldr
0 !LDRAW_ORG Model
1 16 0 0 0 1 0 0 0 1 0 0 0 1 triangle.dat
0 FILE triangle.dat
0 !LDRAW_ORG Part
3 16 0 0 0 10 0 0 0 10 0
0 NOFILE
`;

describe("derived LDraw scene indexing", () => {
  it("maps repeated transformed submodels by injected names, not sibling indices", async () => {
    const { model, sceneIndex } = await parseInstructionScopeText(source);

    expect(sceneIndex).not.toBeNull();
    const occurrences = sceneIndex?.entries.filter((entry) => entry.kind === "occurrence") ?? [];
    const parts = sceneIndex?.entries.filter((entry) => entry.kind === "part") ?? [];
    expect(occurrences.map((entry) => entry.occurrenceId)).toEqual([
      "occ-000001",
      "occ-000002",
      "occ-000003",
    ]);
    expect(occurrences[1]!.definitionName).toBe("module.ldr");
    expect(occurrences[2]!.definitionName).toBe("module.ldr");
    expect(occurrences[1]!.group.position.x).toBe(10);
    expect(occurrences[2]!.group.position.x).toBe(-10);
    expect(parts.map((entry) => entry.instructionNodeId)).toEqual(["node-000003", "node-000005"]);

    applyInstructionSceneVisibility(model, sceneIndex!, "occ-000001", 2);
    expect(occurrences[1]!.group.visible).toBe(true);
    expect(occurrences[2]!.group.visible).toBe(false);
  });

  it("renders direct line, face, and conditional geometry in a transformed color context", async () => {
    const directSource = `0 !BRICKY DERIVED_SOURCE 2
0 !COLOUR Red CODE 4 VALUE #C91A09 EDGE #333333
0 !BRICKY ROOT occ-000001
0 !BRICKY RENDER_STRATEGY subtree
0 !BRICKY OCCURRENCE occ-000001 - 0 1 bWFpbi5sZHI
0 !BRICKY OCCURRENCE occ-000002 occ-000001 1 2 Z2VuZXJhdGVkLWhvc2UubGRy
0 Name: __bricky_occ_000001.ldr
1 4 10 20 30 0 -1 0 1 0 0 0 0 1 __bricky_occ_000002.ldr
0 FILE __bricky_occ_000002.ldr
0 !LDCAD GENERATED [generator=path] [source=synthetic-test]
0 BFC CERTIFY CCW
2 24 0 0 0 10 0 0
3 16 0 0 0 10 0 0 0 10 0
0 STEP
4 16 0 0 0 0 10 0 10 10 0 10 0 0
5 24 0 0 0 10 0 0 0 10 0 10 10 0
0 NOFILE
`;
    const { model, sceneIndex } = await parseInstructionScopeText(directSource);
    const child = sceneIndex?.entries.find(
      (entry) => entry.kind === "occurrence" && entry.occurrenceId === "occ-000002",
    );
    const meshes: Mesh[] = [];
    const lines: LineSegments[] = [];
    child?.group.traverse((object) => {
      if (object instanceof Mesh) meshes.push(object);
      if (object instanceof LineSegments) lines.push(object);
    });

    expect(child?.group.position.toArray()).toEqual([10, 20, 30]);
    expect(meshes.length).toBeGreaterThan(0);
    expect(lines.length).toBeGreaterThan(0);
    const materials = Array.isArray(meshes[0]!.material)
      ? meshes[0]!.material
      : [meshes[0]!.material];
    expect(
      materials.some((material) => {
        const colored = material as typeof material & {
          color?: { getHexString: () => string };
        };
        return colored.color?.getHexString().toUpperCase() === "C91A09";
      }),
    ).toBe(true);
    expect(model.children.length).toBeGreaterThan(0);
  });

  it("indexes four cumulative step-2 wrappers exactly once", async () => {
    const stepTwoSource = `0 !BRICKY DERIVED_SOURCE 2
0 !COLOUR Black CODE 0 VALUE #1B2A34 EDGE #2B4354
0 !COLOUR Dark_Bluish_Grey CODE 72 VALUE #646464 EDGE #333333
0 !BRICKY ROOT occ-000001
0 !BRICKY RENDER_STRATEGY local
0 !BRICKY OCCURRENCE occ-000001 - 0 1 bWFpbi5sZHI
0 !BRICKY PART node-000001 occ-000001 1 1
0 !BRICKY PART node-000002 occ-000001 1 2
0 !BRICKY PART node-000003 occ-000001 2 3
0 !BRICKY PART node-000004 occ-000001 2 4
0 Name: __bricky_occ_000001.ldr
1 0 0 0 0 1 0 0 0 1 0 0 0 1 __bricky_node_000001.ldr
1 0 0 10 -50 0 0 1 0 1 0 -1 0 0 __bricky_node_000002.ldr
0 STEP
1 72 -140 0 -50 -1 0 0 0 1 0 0 0 -1 __bricky_node_000003.ldr
1 0 0 0 -120 -1 0 0 0 1 0 0 0 -1 __bricky_node_000004.ldr
0 FILE __bricky_node_000001.ldr
1 16 0 0 0 1 0 0 0 1 0 0 0 1 part-a.dat
0 FILE __bricky_node_000002.ldr
1 16 0 0 0 1 0 0 0 1 0 0 0 1 part-b.dat
0 FILE __bricky_node_000003.ldr
1 16 0 0 0 1 0 0 0 1 0 0 0 1 part-c.dat
0 FILE __bricky_node_000004.ldr
1 16 0 0 0 1 0 0 0 1 0 0 0 1 part-d.dat
0 FILE part-a.dat
3 16 0 0 0 10 0 0 0 10 0
0 FILE part-b.dat
3 16 0 0 0 10 0 0 0 10 0
0 FILE part-c.dat
3 16 0 0 0 10 0 0 0 10 0
0 FILE part-d.dat
3 16 0 0 0 10 0 0 0 10 0
0 NOFILE
`;
    const { model, sceneIndex } = await parseInstructionScopeText(stepTwoSource);
    const nodeIds =
      sceneIndex?.entries.flatMap((entry) =>
        entry.instructionNodeId === null ? [] : [entry.instructionNodeId],
      ) ?? [];

    expect(nodeIds).toEqual(["node-000001", "node-000002", "node-000003", "node-000004"]);
    expect(new Set(nodeIds).size).toBe(4);
    model.updateMatrixWorld(true);
    const partMatrices = sceneIndex?.entries.flatMap((entry) =>
      entry.kind === "part" ? [entry.group.matrixWorld.elements] : [],
    );
    expect(partMatrices).toHaveLength(4);
    const expectedMatrices = [
      [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
      [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 10, -50, 1],
      [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, -140, 0, -50, 1],
      [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, -120, 1],
    ];
    partMatrices?.forEach((matrix, matrixIndex) => {
      matrix.forEach((value, elementIndex) => {
        expect(value).toBeCloseTo(expectedMatrices[matrixIndex]![elementIndex]!);
      });
    });
    const meshes: Mesh[] = [];
    model.traverse((object) => {
      if (object instanceof Mesh) meshes.push(object);
    });
    expect(meshes).toHaveLength(4);
  });
});
