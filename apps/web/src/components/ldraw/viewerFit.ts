import { Box3, BufferGeometry, LineSegments, Mesh, Object3D, Points } from "three";

/**
 * Bounds of the *visible* geometry only. `Box3.setFromObject` includes
 * invisible children, so fitting with it framed the entire model even when
 * step visibility showed just the first few parts — early steps rendered as
 * a tiny cluster in a huge viewport (audit suspect A1).
 */
export function visibleGeometryBounds(root: Object3D): Box3 {
  const bounds = new Box3();
  const scratch = new Box3();
  root.updateWorldMatrix(true, true);

  const collect = (object: Object3D): void => {
    if (!object.visible) return;
    if (object instanceof Mesh || object instanceof LineSegments || object instanceof Points) {
      const geometry: BufferGeometry = (object as Mesh).geometry;
      if (geometry.boundingBox === null) geometry.computeBoundingBox();
      if (geometry.boundingBox !== null && !geometry.boundingBox.isEmpty()) {
        scratch.copy(geometry.boundingBox).applyMatrix4(object.matrixWorld);
        bounds.union(scratch);
      }
    }
    for (const child of object.children) collect(child);
  };

  collect(root);
  return bounds;
}
