import { Group, Object3D } from "three";

const DEFAULT_STEP_COUNT = 1;

function readPositiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= DEFAULT_STEP_COUNT
    ? value
    : null;
}

function readNonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

export function getBuildingStepCount(model: Object3D): number {
  const userData = model.userData as Record<string, unknown>;
  return readPositiveInteger(userData.numBuildingSteps) ?? DEFAULT_STEP_COUNT;
}

export function applyBuildingStepVisibility(model: Object3D, selectedStep: number): void {
  const stepCount = getBuildingStepCount(model);

  if (stepCount <= DEFAULT_STEP_COUNT) {
    model.traverse((object) => {
      if (object instanceof Group) {
        object.visible = true;
      }
    });
    return;
  }

  const safeSelectedStep = Number.isFinite(selectedStep)
    ? Math.min(Math.max(Math.trunc(selectedStep), 0), stepCount - 1)
    : 0;

  model.traverse((object) => {
    if (!(object instanceof Group)) {
      return;
    }

    const userData = object.userData as Record<string, unknown>;
    const buildingStep = readNonNegativeInteger(userData.buildingStep);

    object.visible = buildingStep === null || buildingStep <= safeSelectedStep;
  });
}
