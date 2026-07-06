import { BufferAttribute, BufferGeometry, Group, Material, Matrix4, Mesh, Object3D } from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

/**
 * Inspect mode shows the fully assembled scene with every part visible and
 * original materials — a completely static frame. Rendering it through the
 * per-part graph costs one draw call per mesh (thousands on big models),
 * which is what makes rotating full builds laggy on real GPUs. This module
 * builds a merged twin of the scene's meshes — transforms baked into
 * geometry, one mesh per distinct material — and swaps it in while
 * inspecting.
 *
 * Only meshes are merged: edge and conditional lines stay per-part, where
 * they render correctly at rest and are already hidden during interaction
 * by AdaptiveViewerLines. That halves the baked-copy memory and keeps this
 * module's ownership clean — it writes `visible` only on Mesh objects and
 * its own container, while the presentation controller owns Groups and
 * AdaptiveViewerLines owns LineSegments.
 *
 * The merged container is a plain Object3D on purpose: the presentation
 * controller's visibility normalization only touches Groups, so it never
 * fights over it.
 */

export const INSPECT_MERGED_VIEW_NAME = "__bricky_inspect_merged";

interface MergeBucket {
  material: Material;
  geometries: BufferGeometry[];
}

function bucketKey(material: Material, geometry: BufferGeometry): string {
  return `${material.uuid}:${Object.keys(geometry.attributes).sort().join(",")}`;
}

function sliceAttribute(attribute: BufferAttribute, start: number, count: number): BufferAttribute {
  const itemSize = attribute.itemSize;
  const array = attribute.array as Float32Array;
  const copy = new Float32Array(array.subarray(start * itemSize, (start + count) * itemSize));
  return new BufferAttribute(copy, itemSize, attribute.normalized);
}

function sliceGeometry(geometry: BufferGeometry, start: number, count: number): BufferGeometry {
  const slice = new BufferGeometry();
  for (const [name, attribute] of Object.entries(geometry.attributes)) {
    if (attribute instanceof BufferAttribute) {
      slice.setAttribute(name, sliceAttribute(attribute, start, count));
    }
  }
  return slice;
}

function collectMesh(mesh: Mesh, matrix: Matrix4, buckets: Map<string, MergeBucket>): void {
  const source = mesh.geometry.index === null ? mesh.geometry : mesh.geometry.toNonIndexed();
  const position = source.getAttribute("position");
  const slots = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
  const fallbackSlot = slots[0];
  if (
    !(position instanceof BufferAttribute) ||
    position.count === 0 ||
    fallbackSlot === undefined
  ) {
    return;
  }
  const ranges =
    source.groups.length > 0 && slots.length > 1
      ? source.groups.map((group) => ({
          start: group.start,
          count: group.count,
          material: slots[group.materialIndex ?? 0] ?? fallbackSlot,
        }))
      : [{ start: 0, count: position.count, material: fallbackSlot }];

  for (const range of ranges) {
    if (range.count === 0) continue;
    const slice = sliceGeometry(source, range.start, range.count);
    slice.applyMatrix4(matrix);
    const key = bucketKey(range.material, slice);
    let bucket = buckets.get(key);
    if (bucket === undefined) {
      bucket = { material: range.material, geometries: [] };
      buckets.set(key, bucket);
    }
    bucket.geometries.push(slice);
  }
}

function collectSubtree(
  object: Object3D,
  parentMatrix: Matrix4,
  buckets: Map<string, MergeBucket>,
): void {
  if (object.name === INSPECT_MERGED_VIEW_NAME) return;
  object.updateMatrix();
  const matrix = new Matrix4().multiplyMatrices(parentMatrix, object.matrix);
  if (object instanceof Mesh) {
    collectMesh(object as Mesh, matrix, buckets);
  }
  for (const child of object.children) {
    collectSubtree(child, matrix, buckets);
  }
}

export function createInspectMergedView(model: Group): Object3D {
  const startedAt = performance.now();
  const buckets = new Map<string, MergeBucket>();
  for (const child of model.children) {
    collectSubtree(child, new Matrix4(), buckets);
  }
  const container = new Object3D();
  container.name = INSPECT_MERGED_VIEW_NAME;
  container.visible = false;
  let vertexCount = 0;
  for (const bucket of buckets.values()) {
    const merged = mergeGeometries(bucket.geometries, false);
    bucket.geometries.forEach((geometry) => geometry.dispose());
    vertexCount += merged.getAttribute("position").count;
    container.add(new Mesh(merged, bucket.material));
  }
  console.debug(
    `[bricky] inspect merged view: ${container.children.length} meshes, ` +
      `${vertexCount} vertices, built in ${Math.round(performance.now() - startedAt)} ms`,
  );
  return container;
}

function findMergedView(model: Group): Object3D | null {
  return model.children.find((child) => child.name === INSPECT_MERGED_VIEW_NAME) ?? null;
}

function setPartMeshesVisible(model: Group, merged: Object3D | null, visible: boolean): void {
  model.traverse((object) => {
    if (object instanceof Mesh && (merged === null || !isDescendantOf(object, merged))) {
      object.visible = visible;
    }
  });
}

function isDescendantOf(object: Object3D, ancestor: Object3D): boolean {
  let current: Object3D | null = object;
  while (current !== null) {
    if (current === ancestor) return true;
    current = current.parent;
  }
  return false;
}

/**
 * Restores per-part rendering. Call before the presentation controller
 * applies step visibility so the controller starts from a clean slate.
 */
export function restoreInspectMergedView(model: Group): void {
  const merged = findMergedView(model);
  if (merged !== null) merged.visible = false;
  setPartMeshesVisible(model, merged, true);
}

/**
 * Swaps in the merged twin (building it on first use). Call after the
 * presentation controller has run so nothing re-shows the per-part meshes.
 */
export function activateInspectMergedView(model: Group): void {
  let merged = findMergedView(model);
  if (merged === null) {
    merged = createInspectMergedView(model);
    model.add(merged);
  }
  merged.visible = true;
  setPartMeshesVisible(model, merged, false);
}
