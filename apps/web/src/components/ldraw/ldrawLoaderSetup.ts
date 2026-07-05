import { LDrawLoader } from "three/addons/loaders/LDrawLoader.js";
import { LDrawConditionalLineMaterial } from "three/addons/materials/LDrawConditionalLineMaterial.js";

export function createLDrawLoader(): LDrawLoader {
  const loader = new LDrawLoader();
  loader.setConditionalLineMaterial(LDrawConditionalLineMaterial);
  return loader;
}

/**
 * Prepares a loader for official-library sources: parts resolve against the
 * library path, the LDConfig palette is preloaded, and unresolved color-16
 * geometry falls back to red so missing color context is visible instead of
 * silently grey. Shared by the main thread and the parse worker so both
 * resolve the exact same material palette.
 */
export async function prepareOfficialLoader(
  loader: LDrawLoader,
  materialsUrl: string,
  partsLibraryPath: string,
): Promise<void> {
  loader.setPartsLibraryPath(partsLibraryPath);
  await loader.preloadMaterials(materialsUrl);
  const redMaterial = loader.getMaterial("4");
  if (redMaterial !== null) {
    const materialData = redMaterial.userData as Record<string, unknown>;
    materialData.code = "16";
    loader.addMaterial(redMaterial);
  }
}
