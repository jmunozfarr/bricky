import { describe, expect, it } from "vitest";

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
    expect(parts.map((entry) => entry.instructionNodeId)).toEqual([
      "node-000003",
      "node-000005",
    ]);

    applyInstructionSceneVisibility(model, sceneIndex!, "occ-000001", 2);
    expect(occurrences[1]!.group.visible).toBe(true);
    expect(occurrences[2]!.group.visible).toBe(false);
  });
});
