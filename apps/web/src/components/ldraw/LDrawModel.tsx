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
import {
  applyInstructionSceneVisibility,
  createInstructionSceneIndex,
  InstructionSceneIndex,
  parseInstructionSourceManifest,
} from "./instructionSceneIndex";

export type LDrawLoadState =
  | { kind: "loading" }
  | { kind: "ready"; model: Group; sceneIndex: InstructionSceneIndex | null }
  | { kind: "error"; message: string };

export type LDrawModelSource =
  | { kind: "synthetic"; key: string; url: string }
  | {
      kind: "official";
      key: string;
      url: string;
      materialsUrl: string;
      partsLibraryPath: string;
    }
  | {
      kind: "instruction-scope";
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

interface LoadedLDrawModel {
  model: Group;
  sceneIndex: InstructionSceneIndex | null;
}

export async function parseInstructionScopeText(
  text: string,
  loader = createLoader(),
): Promise<LoadedLDrawModel> {
  const manifest = parseInstructionSourceManifest(text);
  const model = await parseLDraw(loader, text);
  return { model, sceneIndex: createInstructionSceneIndex(model, manifest) };
}

async function loadModelSource(
  source: LDrawModelSource,
  signal: AbortSignal,
): Promise<LoadedLDrawModel> {
  const loader = createLoader();
  if (source.kind === "synthetic") {
    const response = await fetch(source.url, { signal });
    if (!response.ok) {
      throw new Error(`Model request returned HTTP ${response.status}`);
    }
    return { model: await parseLDraw(loader, await response.text()), sceneIndex: null };
  }

  loader.setPartsLibraryPath(source.partsLibraryPath);
  await loader.preloadMaterials(source.materialsUrl);

  const redMaterial = loader.getMaterial("4");
  if (redMaterial !== null) {
    const materialData = redMaterial.userData as Record<string, unknown>;
    materialData.code = "16";
    loader.addMaterial(redMaterial);
  }

  if (source.kind === "instruction-scope") {
    const response = await fetch(source.url, { signal });
    if (!response.ok) {
      throw new Error(`Instruction scope request returned HTTP ${response.status}`);
    }
    return parseInstructionScopeText(await response.text(), loader);
  }
  return { model: await loader.loadAsync(source.url), sceneIndex: null };
}

export function disposeLDrawModel(model: Group): void {
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
        const loaded = await loadModelSource(source, controller.signal);
        const model = loaded.model;
        model.rotation.x = Math.PI;

        if (!active) {
          disposeLDrawModel(model);
          return;
        }

        ownedModel = model;
        setState({ kind: "ready", model, sceneIndex: loaded.sceneIndex });
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
        disposeLDrawModel(ownedModel);
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

interface HierarchicalLDrawModelProps {
  model: Group;
  sceneIndex: InstructionSceneIndex;
  activeOccurrenceId: string;
  selectedStep: number;
}

export function HierarchicalLDrawModel({
  model,
  sceneIndex,
  activeOccurrenceId,
  selectedStep,
}: HierarchicalLDrawModelProps) {
  useLayoutEffect(() => {
    applyInstructionSceneVisibility(
      model,
      sceneIndex,
      activeOccurrenceId,
      selectedStep,
    );
  }, [activeOccurrenceId, model, sceneIndex, selectedStep]);

  return <primitive object={model} />;
}
