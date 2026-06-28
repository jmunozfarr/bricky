import { useEffect, useLayoutEffect, useState } from "react";
import {
  BufferGeometry,
  Group,
  LineSegments,
  Material,
  Mesh,
  Points,
} from "three";
import { LDrawLoader } from "three/addons/loaders/LDrawLoader.js";
import { LDrawConditionalLineMaterial } from "three/addons/materials/LDrawConditionalLineMaterial.js";

import { applyBuildingStepVisibility } from "./buildingSteps";

export type LDrawLoadState =
  | { kind: "loading" }
  | { kind: "ready"; model: Group }
  | { kind: "error"; message: string };

function parseLDraw(text: string): Promise<Group> {
  return new Promise((resolve, reject) => {
    const loader = new LDrawLoader();
    loader.setConditionalLineMaterial(LDrawConditionalLineMaterial);
    loader.addDefaultMaterials();
    loader.parse(text, resolve, reject);
  });
}

function disposeModel(model: Group): void {
  const geometries = new Set<BufferGeometry>();
  const materials = new Set<Material>();

  model.traverse((object) => {
    if (
      object instanceof Mesh ||
      object instanceof LineSegments ||
      object instanceof Points
    ) {
      geometries.add(object.geometry);
      const objectMaterials = Array.isArray(object.material)
        ? object.material
        : [object.material];
      objectMaterials.forEach((material) => materials.add(material));
    }
  });

  geometries.forEach((geometry) => geometry.dispose());
  materials.forEach((material) => material.dispose());
}

export function useLDrawModel(url: string): LDrawLoadState {
  const [state, setState] = useState<LDrawLoadState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let ownedModel: Group | null = null;

    setState({ kind: "loading" });

    async function loadModel() {
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(`Model request returned HTTP ${response.status}`);
        }

        const model = await parseLDraw(await response.text());
        model.rotation.x = Math.PI;

        if (!active) {
          disposeModel(model);
          return;
        }

        ownedModel = model;
        setState({ kind: "ready", model });
      } catch (error: unknown) {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) {
          return;
        }

        const message = error instanceof Error ? error.message : "Unknown model error";
        setState({ kind: "error", message });
      }
    }

    void loadModel();

    return () => {
      active = false;
      controller.abort();
      if (ownedModel !== null) {
        disposeModel(ownedModel);
      }
    };
  }, [url]);

  return state;
}

interface LDrawModelProps {
  model: Group;
  selectedStep: number;
}

export function LDrawModel({ model, selectedStep }: LDrawModelProps) {
  useLayoutEffect(() => {
    applyBuildingStepVisibility(model, selectedStep);
  }, [model, selectedStep]);

  return <primitive object={model} />;
}
