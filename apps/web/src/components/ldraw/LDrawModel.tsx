import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { BufferGeometry, Group, LineSegments, Material, Mesh, Object3D, Points } from "three";
import { LDrawLoader } from "three/addons/loaders/LDrawLoader.js";
import { LDrawConditionalLineMaterial } from "three/addons/materials/LDrawConditionalLineMaterial.js";

import { applyBuildingStepVisibility } from "./buildingSteps";
import { LatestScopeLoader, ScopeLoadSupersededError } from "./boundedSceneLoader";
import {
  createInstructionSceneIndex,
  InstructionSceneIndex,
  parseInstructionSourceManifest,
} from "./instructionSceneIndex";
import { ExclusiveInstructionSceneMount } from "./instructionSceneMount";
import {
  InstructionPresentationController,
  InstructionPresentationMode,
} from "./instructionPresentation";

export type LDrawLoadState =
  | { kind: "loading" }
  | {
      kind: "refreshing";
      model: Group;
      sceneIndex: InstructionSceneIndex | null;
      sourceKey: string;
      fitKey: string;
    }
  | {
      kind: "ready";
      model: Group;
      sceneIndex: InstructionSceneIndex | null;
      sourceKey: string;
      fitKey: string;
    }
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
      modelId: string;
      scopeId: string;
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

export interface LoadedLDrawModel {
  model: Group;
  sceneIndex: InstructionSceneIndex | null;
}

export async function parseInstructionScopeText(
  text: string,
  loader = createLoader(),
): Promise<LoadedLDrawModel> {
  const manifest = parseInstructionSourceManifest(text);
  const model = await parseLDraw(loader, text);
  const sceneIndex = createInstructionSceneIndex(model, manifest);
  return { model, sceneIndex };
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

  return { model: await loader.loadAsync(source.url), sceneIndex: null };
}

async function loadInstructionScopeSource(
  source: Extract<LDrawModelSource, { kind: "instruction-scope" }>,
  signal: AbortSignal,
): Promise<LoadedLDrawModel> {
  const loader = createLoader();
  loader.setPartsLibraryPath(source.partsLibraryPath);
  await loader.preloadMaterials(source.materialsUrl);
  const redMaterial = loader.getMaterial("4");
  if (redMaterial !== null) {
    const materialData = redMaterial.userData as Record<string, unknown>;
    materialData.code = "16";
    loader.addMaterial(redMaterial);
  }
  const response = await fetch(source.url, { signal });
  if (!response.ok) {
    throw new Error(`Instruction scope request returned HTTP ${response.status}`);
  }
  return parseInstructionScopeText(await response.text(), loader);
}

function isRenderObject(object: Object3D): object is Mesh | LineSegments | Points {
  return object instanceof Mesh || object instanceof LineSegments || object instanceof Points;
}

export function disposeLDrawModel(model: Group): void {
  model.removeFromParent();
  const geometries = new Set<BufferGeometry>();
  const materials = new Set<Material>();

  model.traverse((object) => {
    if (isRenderObject(object)) {
      geometries.add(object.geometry);
      const objectMaterials = Array.isArray(object.material) ? object.material : [object.material];
      objectMaterials.forEach((material) => materials.add(material));
    }
  });

  geometries.forEach((geometry) => geometry.dispose());
  materials.forEach((material) => material.dispose());
}

const instructionSceneLoader = new LatestScopeLoader(
  3,
  loadInstructionScopeSource,
  (loaded: LoadedLDrawModel) => disposeLDrawModel(loaded.model),
);

export function clearInstructionSceneCache(): void {
  instructionSceneLoader.clear();
}

export function cachedInstructionScenes(): [string, LoadedLDrawModel][] {
  return instructionSceneLoader.cachedEntries();
}

export function useLDrawModel(source: LDrawModelSource, retryVersion = 0): LDrawLoadState {
  const [state, setState] = useState<LDrawLoadState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    const isInstructionScope = source.kind === "instruction-scope";
    let active = true;
    let ownedModel: Group | null = null;

    setState((current) =>
      isInstructionScope && (current.kind === "ready" || current.kind === "refreshing")
        ? {
            kind: "refreshing",
            model: current.model,
            sceneIndex: current.sceneIndex,
            sourceKey: current.sourceKey,
            fitKey: current.fitKey,
          }
        : { kind: "loading" },
    );

    async function loadModel() {
      try {
        if (isInstructionScope) instructionSceneLoader.setNamespace(source.modelId);
        const loaded = isInstructionScope
          ? await instructionSceneLoader.request(source.key, source)
          : await loadModelSource(source, controller.signal);
        const model = loaded.model;
        model.rotation.x = Math.PI;

        if (!active) {
          if (!isInstructionScope) disposeLDrawModel(model);
          return;
        }

        ownedModel = isInstructionScope ? null : model;
        setState({
          kind: "ready",
          model,
          sceneIndex: loaded.sceneIndex,
          sourceKey: source.key,
          fitKey: source.kind === "instruction-scope" ? source.scopeId : source.key,
        });
      } catch (error: unknown) {
        if (
          !active ||
          error instanceof ScopeLoadSupersededError ||
          (error instanceof DOMException && error.name === "AbortError")
        ) {
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
      if (source.kind === "instruction-scope") {
        instructionSceneLoader.cancel(source.key);
      }
      if (ownedModel !== null) {
        disposeLDrawModel(ownedModel);
      }
    };
  }, [retryVersion, source]);

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
  host: Group;
  model: Group;
  sceneIndex: InstructionSceneIndex;
  activeOccurrenceId: string;
  selectedStep: number;
  cacheKey: string;
  presentationMode?: InstructionPresentationMode;
}

export function HierarchicalLDrawModel({
  host,
  model,
  sceneIndex,
  activeOccurrenceId,
  selectedStep,
  cacheKey,
  presentationMode = "assembled",
}: HierarchicalLDrawModelProps) {
  const mount = useMemo(() => new ExclusiveInstructionSceneMount(host), [host]);
  const presentation = useMemo(
    () => new InstructionPresentationController(model, sceneIndex),
    [model, sceneIndex],
  );
  useLayoutEffect(() => {
    presentation.apply(activeOccurrenceId, selectedStep, presentationMode);
  }, [activeOccurrenceId, presentation, presentationMode, selectedStep]);

  useEffect(() => () => presentation.dispose(), [presentation]);

  useLayoutEffect(() => {
    mount.activate({ cacheKey, model, sceneIndex });
    return () => mount.deactivate(model);
  }, [cacheKey, model, mount, sceneIndex]);

  return <primitive object={host} />;
}
