import {
  BufferAttribute,
  BufferGeometry,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshStandardMaterial,
} from "three";
import { describe, expect, it } from "vitest";

import {
  activateInspectMergedView,
  createInspectMergedView,
  INSPECT_MERGED_VIEW_NAME,
  restoreInspectMergedView,
} from "./inspectMergedView";

const grey = new MeshStandardMaterial();
const red = new MeshStandardMaterial();
const edge = new LineBasicMaterial();

function triangle(): BufferGeometry {
  const geometry = new BufferGeometry();
  geometry.setAttribute(
    "position",
    new BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]), 3),
  );
  geometry.setAttribute("normal", new BufferAttribute(new Float32Array(9).fill(0), 3));
  return geometry;
}

interface Scene {
  model: Group;
  meshes: Mesh[];
  lines: LineSegments;
}

function buildScene(): Scene {
  const model = new Group();
  const partA = new Group();
  partA.position.set(10, 0, 0);
  const meshA = new Mesh(triangle(), grey);
  partA.add(meshA);

  const partB = new Group();
  partB.position.set(0, 20, 0);
  const meshB = new Mesh(triangle(), grey);
  const meshC = new Mesh(triangle(), red);
  partB.add(meshB, meshC);

  const edgeGeometry = new BufferGeometry();
  edgeGeometry.setAttribute(
    "position",
    new BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0]), 3),
  );
  const lines = new LineSegments(edgeGeometry, edge);
  partA.add(lines);

  model.add(partA, partB);
  return { model, meshes: [meshA, meshB, meshC], lines };
}

describe("inspect merged view", () => {
  it("merges meshes into one object per material and leaves lines alone", () => {
    const merged = createInspectMergedView(buildScene().model);

    expect(merged.children).toHaveLength(2);
    expect(merged.children.every((child) => child instanceof Mesh)).toBe(true);
    const greyMesh = merged.children.find((child) => (child as Mesh).material === grey) as Mesh;
    // two grey triangles merged: 6 vertices
    expect(greyMesh.geometry.getAttribute("position").count).toBe(6);
  });

  it("bakes part transforms into merged positions", () => {
    const merged = createInspectMergedView(buildScene().model);
    const greyMesh = merged.children.find((child) => (child as Mesh).material === grey) as Mesh;
    const positions = greyMesh.geometry.getAttribute("position");
    const xs = [...Array(positions.count).keys()].map((i) => positions.getX(i));
    const ys = [...Array(positions.count).keys()].map((i) => positions.getY(i));
    // one triangle offset by x+10 (partA), one by y+20 (partB)
    expect(xs.filter((x) => x >= 10)).toHaveLength(3);
    expect(ys.filter((y) => y >= 20)).toHaveLength(3);
  });

  it("hides only part meshes while active and restores them afterwards", () => {
    const { model, meshes, lines } = buildScene();
    const [partA, partB] = model.children;

    activateInspectMergedView(model);
    const merged = model.children.find((child) => child.name === INSPECT_MERGED_VIEW_NAME)!;
    expect(merged.visible).toBe(true);
    expect(meshes.every((mesh) => !mesh.visible)).toBe(true);
    // Groups and line segments belong to other owners and stay visible.
    expect(partA!.visible).toBe(true);
    expect(partB!.visible).toBe(true);
    expect(lines.visible).toBe(true);
    // The merged view's own meshes must not hide themselves.
    expect(merged.children.every((child) => child.visible)).toBe(true);

    activateInspectMergedView(model);
    expect(model.children.filter((child) => child.name === INSPECT_MERGED_VIEW_NAME)).toHaveLength(
      1,
    );

    restoreInspectMergedView(model);
    expect(merged.visible).toBe(false);
    expect(meshes.every((mesh) => mesh.visible)).toBe(true);

    // Rebuilding after restore must not include the merged view's own
    // geometry (no self-accumulation).
    const again = createInspectMergedView(model);
    const greyMesh = again.children.find((child) => (child as Mesh).material === grey) as Mesh;
    expect(greyMesh.geometry.getAttribute("position").count).toBe(6);
  });
});
