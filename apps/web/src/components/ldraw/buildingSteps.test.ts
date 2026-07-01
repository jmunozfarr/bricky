import { Group } from "three";
import { describe, expect, it } from "vitest";

import { applyBuildingStepVisibility, getBuildingStepCount } from "./buildingSteps";

function createStepModel(stepCount: unknown): Group {
  const model = new Group();
  model.userData.numBuildingSteps = stepCount;
  return model;
}

function addStepGroup(model: Group, buildingStep: unknown): Group {
  const group = new Group();
  group.userData.buildingStep = buildingStep;
  model.add(group);
  return group;
}

describe("getBuildingStepCount", () => {
  it("reads valid building-step metadata", () => {
    expect(getBuildingStepCount(createStepModel(3))).toBe(3);
  });

  it.each([undefined, null, "3", 0, -1, 2.5, Number.NaN])(
    "falls back safely for malformed metadata: %s",
    (value) => {
      expect(getBuildingStepCount(createStepModel(value))).toBe(1);
    },
  );
});

describe("applyBuildingStepVisibility", () => {
  it("shows previous and current groups while hiding later groups", () => {
    const model = createStepModel(3);
    const previous = addStepGroup(model, 0);
    const current = addStepGroup(model, 1);
    const later = addStepGroup(model, 2);

    applyBuildingStepVisibility(model, 1);

    expect(previous.visible).toBe(true);
    expect(current.visible).toBe(true);
    expect(later.visible).toBe(false);
  });

  it("keeps groups with malformed step metadata visible", () => {
    const model = createStepModel(3);
    const missing = addStepGroup(model, undefined);
    const malformed = addStepGroup(model, "2");

    applyBuildingStepVisibility(model, 0);

    expect(missing.visible).toBe(true);
    expect(malformed.visible).toBe(true);
  });

  it("shows the complete model when it has no multiple steps", () => {
    const model = createStepModel(1);
    const group = addStepGroup(model, 8);
    group.visible = false;

    applyBuildingStepVisibility(model, 0);

    expect(group.visible).toBe(true);
  });
});
