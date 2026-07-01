import { describe, expect, it } from "vitest";

import { disposeLDrawModel, parseInstructionScopeText } from "./LDrawModel";

function occurrenceId(index: number): string {
  return `occ-${String(index).padStart(6, "0")}`;
}

function nodeId(index: number): string {
  return `node-${String(index).padStart(6, "0")}`;
}

function occurrenceFile(id: string): string {
  return `__bricky_${id.replace("-", "_")}.ldr`;
}

function nodeFile(id: string): string {
  return `__bricky_${id.replace("-", "_")}.ldr`;
}

function generatedDerivedSource(physicalParts: number): string {
  const lines = [
    "0 !BRICKY DERIVED_SOURCE 1",
    "0 !BRICKY ROOT occ-000001",
    "0 !BRICKY OCCURRENCE occ-000001 - 0 1 bWFpbi5sZHI",
  ];
  for (let index = 1; index <= physicalParts; index += 1) {
    const childId = occurrenceId(index + 1);
    const partId = nodeId(index * 2);
    lines.push(
      `0 !BRICKY OCCURRENCE ${childId} occ-000001 1 ${index + 1} cmVwZWF0ZWQubGRy`,
      `0 !BRICKY PART ${partId} ${childId} 1 ${index * 2}`,
    );
  }
  lines.push("0 Name: __bricky_occ_000001.ldr");
  for (let index = 1; index <= physicalParts; index += 1) {
    lines.push(
      `1 16 ${index * 20} 0 0 1 0 0 0 1 0 0 0 1 ${occurrenceFile(occurrenceId(index + 1))}`,
    );
  }
  for (let index = 1; index <= physicalParts; index += 1) {
    const childId = occurrenceId(index + 1);
    const partId = nodeId(index * 2);
    lines.push(
      `0 FILE ${occurrenceFile(childId)}`,
      `1 16 0 0 0 1 0 0 0 1 0 0 0 1 ${nodeFile(partId)}`,
    );
  }
  for (let index = 1; index <= physicalParts; index += 1) {
    const partId = nodeId(index * 2);
    lines.push(
      `0 FILE ${nodeFile(partId)}`,
      "0 !LDRAW_ORG Model",
      "1 16 0 0 0 1 0 0 0 1 0 0 0 1 triangle.dat",
    );
  }
  lines.push("0 FILE triangle.dat", "0 !LDRAW_ORG Part", "3 16 0 0 0 10 0 0 0 10 0", "0 NOFILE");
  return `${lines.join("\n")}\n`;
}

describe("hierarchical rendering diagnostics", () => {
  it("records non-threshold loader diagnostics for generated scopes", async () => {
    for (const physicalParts of [100, 1_000, 5_000]) {
      const source = generatedDerivedSource(physicalParts);
      const heapBefore = process.memoryUsage().heapUsed;
      const started = performance.now();
      const loaded = await parseInstructionScopeText(source);
      const initialLoadMs = performance.now() - started;
      const approximateHeapDeltaBytes = Math.max(0, process.memoryUsage().heapUsed - heapBefore);

      const scopeSource = generatedDerivedSource(1);
      const scopeStarted = performance.now();
      const scope = await parseInstructionScopeText(scopeSource);
      const occurrenceScopeChangeMs = performance.now() - scopeStarted;
      const diagnostics = {
        physicalPartOccurrences: physicalParts,
        derivedSourceBytes: new TextEncoder().encode(source).byteLength,
        initialLoadMs: Number(initialLoadMs.toFixed(3)),
        occurrenceScopeChangeMs: Number(occurrenceScopeChangeMs.toFixed(3)),
        threeObjectCount: loaded.sceneIndex?.objectCount ?? 0,
        approximateNodeHeapDeltaBytes: approximateHeapDeltaBytes,
      };
      console.log(`instruction-playback render diagnostic: ${JSON.stringify(diagnostics)}`);

      expect(loaded.sceneIndex?.entries.length).toBe(physicalParts * 2 + 1);
      expect(loaded.sceneIndex?.objectCount).toBeGreaterThan(physicalParts * 2);
      expect(scope.sceneIndex?.entries.length).toBe(3);
      disposeLDrawModel(loaded.model);
      disposeLDrawModel(scope.model);
    }
  }, 30_000);
});
