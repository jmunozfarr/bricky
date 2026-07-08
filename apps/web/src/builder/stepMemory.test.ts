// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import { loadStepMemory, saveStepMemory } from "./stepMemory";

describe("builder step memory", () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("round-trips per-model step progress", () => {
    saveStepMemory("model-a", new Map([["occ-000001", 7]]));
    saveStepMemory("model-b", new Map([["occ-000001", 2]]));

    expect(loadStepMemory("model-a").get("occ-000001")).toBe(7);
    expect(loadStepMemory("model-b").get("occ-000001")).toBe(2);
    expect(loadStepMemory("model-c").size).toBe(0);
  });

  it("ignores corrupt or invalid stored values", () => {
    window.localStorage.setItem("bricky:builder-steps:model-a", "not json {");
    expect(loadStepMemory("model-a").size).toBe(0);

    window.localStorage.setItem(
      "bricky:builder-steps:model-b",
      JSON.stringify({ good: 3, negative: -1, fraction: 1.5, text: "x" }),
    );
    const restored = loadStepMemory("model-b");
    expect(restored.get("good")).toBe(3);
    expect(restored.size).toBe(1);
  });

  it("degrades silently when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(() => saveStepMemory("model-a", new Map([["occ", 1]]))).not.toThrow();
    expect(loadStepMemory("model-a").size).toBe(0);
  });
});
