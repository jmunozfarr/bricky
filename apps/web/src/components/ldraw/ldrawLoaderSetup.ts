import { LDrawLoader } from "three/addons/loaders/LDrawLoader.js";
import { LDrawConditionalLineMaterial } from "three/addons/materials/LDrawConditionalLineMaterial.js";

export function createLDrawLoader(): LDrawLoader {
  const loader = new LDrawLoader();
  loader.setConditionalLineMaterial(LDrawConditionalLineMaterial);
  return loader;
}

/**
 * Prepares a loader for official-library sources: parts resolve against the
 * library path and the LDConfig palette is preloaded. Shared by the main
 * thread and the parse worker so both resolve the exact same palette. Every
 * palette material must keep its own LDConfig code in userData: the worker
 * hands scenes over by that code (ldrawSceneTransfer), so a material
 * relabelled to another code is re-resolved to that code's colour on the
 * main thread.
 */
export async function prepareOfficialLoader(
  loader: LDrawLoader,
  materialsUrl: string,
  partsLibraryPath: string,
): Promise<void> {
  loader.setPartsLibraryPath(partsLibraryPath);
  await loader.preloadMaterials(materialsUrl);
}
