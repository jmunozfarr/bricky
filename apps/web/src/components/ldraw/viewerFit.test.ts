import { BufferAttribute, BufferGeometry, Group, Mesh, MeshBasicMaterial } from "three";
import { describe, expect, it } from "vitest";

import { visibleGeometryBounds } from "./viewerFit";

function unitCubeAt(x: number): Mesh {
  const geometry = new BufferGeometry();
  // Two corners are enough for a bounding box.
  geometry.setAttribute(
    "position",
    new BufferAttribute(new Float32Array([-0.5, -0.5, -0.5, 0.5, 0.5, 0.5]), 3),
  );
  const mesh = new Mesh(geometry, new MeshBasicMaterial());
  mesh.position.set(x, 0, 0);
  return mesh;
}

describe("visibleGeometryBounds", () => {
  it("ignores hidden subtrees so early steps frame only placed parts", () => {
    const model = new Group();
    const placed = new Group();
    placed.add(unitCubeAt(0));
    const future = new Group();
    future.add(unitCubeAt(100));
    future.visible = false;
    model.add(placed, future);

    const bounds = visibleGeometryBounds(model);
    expect(bounds.isEmpty()).toBe(false);
    expect(bounds.max.x).toBeCloseTo(0.5);

    // Making the future step visible expands the frame.
    future.visible = true;
    expect(visibleGeometryBounds(model).max.x).toBeCloseTo(100.5);
  });

  it("ignores individually hidden meshes and applies world transforms", () => {
    const model = new Group();
    const part = new Group();
    part.position.set(10, 0, 0);
    const visibleMesh = unitCubeAt(0);
    const hiddenMesh = unitCubeAt(50);
    hiddenMesh.visible = false;
    part.add(visibleMesh, hiddenMesh);
    model.add(part);

    const bounds = visibleGeometryBounds(model);
    expect(bounds.min.x).toBeCloseTo(9.5);
    expect(bounds.max.x).toBeCloseTo(10.5);
  });

  it("returns an empty box when nothing is visible", () => {
    const model = new Group();
    const part = unitCubeAt(0);
    part.visible = false;
    model.add(part);
    expect(visibleGeometryBounds(model).isEmpty()).toBe(true);
  });
});
