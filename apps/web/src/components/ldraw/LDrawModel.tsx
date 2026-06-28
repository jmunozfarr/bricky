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

export type LDrawModelSource =
  | { kind: "synthetic"; key: string; url: string }
  | {
      kind: "official";
      key: string;
      url: string;
      materialsUrl: string;
      partsLibraryPath: string;
    };

function createLoader(): LDrawLoader {
  const loader = new LDrawLoader();
  loader.setConditionalLineMaterial(LDrawConditionalLineMaterial);
  return loader;
}

function parseLDraw(loader: LDrawLoader, text: string): Promise<Group> {
  return new Promise((resolve, reject) => {
    loader.addDefaultMaterials();
    loader.parse(text, resolve, reject);
  });
}

async function loadModelSource(
  source: LDrawModelSource,
  signal: AbortSignal,
): Promise<Group> {
  const loader = createLoader();
  if (source.kind === "synthetic") {
    const response = await fetch(source.url, { signal });
    if (!response.ok) {
      throw new Error(`Model request returned HTTP ${response.status}`);
    }
    return parseLDraw(loader, await response.text());
  }

  loader.setPartsLibraryPath(source.partsLibraryPath);
  await loader.preloadMaterials(source.materialsUrl);

  const redMaterial = loader.getMaterial("4");
  if (redMaterial !== null) {
    const materialData = redMaterial.userData as Record<string, unknown>;
    materialData.code = "16";
    loader.addMaterial(redMaterial);
  }

  return loader.loadAsync(source.url);
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

export function useLDrawModel(source: LDrawModelSource): LDrawLoadState {
  const [state, setState] = useState<LDrawLoadState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let ownedModel: Group | null = null;

    setState({ kind: "loading" });

    async function loadModel() {
      try {
        const model = await loadModelSource(source, controller.signal);
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
  }, [source]);

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
