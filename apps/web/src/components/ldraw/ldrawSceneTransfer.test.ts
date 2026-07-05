import {
  BufferAttribute,
  BufferGeometry,
  Group,
  LineBasicMaterial,
  LineSegments,
  Material,
  Mesh,
  MeshStandardMaterial,
} from "three";
import { describe, expect, it } from "vitest";

import {
  LDrawMaterialResolver,
  rebuildLDrawScene,
  serializeLDrawScene,
} from "./ldrawSceneTransfer";

interface ConditionalLineCandidate {
  isConditionalLine?: boolean;
}

function paletteResolver(): {
  resolver: LDrawMaterialResolver;
  main: MeshStandardMaterial;
  edge: LineBasicMaterial;
  conditional: LineBasicMaterial;
} {
  const main = new MeshStandardMaterial();
  const edge = new LineBasicMaterial();
  const conditional = new LineBasicMaterial();
  const forCode = (material: Material) => (code: string) => (code === "71" ? material : null);
  return {
    resolver: { main: forCode(main), edge: forCode(edge), conditional: forCode(conditional) },
    main,
    edge,
    conditional,
  };
}

function codedMaterial<T extends Material>(material: T, code: string): T {
  (material.userData as Record<string, unknown>).code = code;
  return material;
}

function buildSourceScene(): Group {
  const root = new Group();
  root.name = "__bricky_occ_000001.ldr";
  root.userData = { numBuildingSteps: 2, fileName: "__bricky_occ_000001.ldr" };

  const part = new Group();
  part.name = "__bricky_node_000001.ldr";
  part.userData = { buildingStep: 1, colorCode: "71" };
  part.position.set(10, -24, 5);
  part.scale.set(1, 1, -1);

  const meshGeometry = new BufferGeometry();
  meshGeometry.setAttribute(
    "position",
    new BufferAttribute(
      new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0, 2, 0, 0, 3, 0, 0, 2, 1, 0]),
      3,
    ),
  );
  meshGeometry.setAttribute("normal", new BufferAttribute(new Float32Array(18).fill(1), 3));
  meshGeometry.addGroup(0, 3, 0);
  meshGeometry.addGroup(3, 3, 1);
  const mesh = new Mesh(meshGeometry, [
    codedMaterial(new MeshStandardMaterial({ color: 0x969696 }), "71"),
    codedMaterial(
      new MeshStandardMaterial({ color: 0xb40000, transparent: true, opacity: 0.5 }),
      "999",
    ),
  ]);

  const edgeGeometry = new BufferGeometry();
  edgeGeometry.setAttribute(
    "position",
    new BufferAttribute(new Float32Array([0, 0, 0, 1, 1, 1]), 3),
  );
  const edges = new LineSegments(
    edgeGeometry,
    codedMaterial(new LineBasicMaterial({ color: 0x333333 }), "71"),
  );

  const conditionalGeometry = new BufferGeometry();
  conditionalGeometry.setAttribute(
    "position",
    new BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0]), 3),
  );
  conditionalGeometry.setAttribute(
    "control0",
    new BufferAttribute(new Float32Array([0, 1, 0, 0, 1, 0]), 3),
  );
  conditionalGeometry.setAttribute(
    "control1",
    new BufferAttribute(new Float32Array([0, -1, 0, 0, -1, 0]), 3),
  );
  conditionalGeometry.setAttribute(
    "direction",
    new BufferAttribute(new Float32Array([1, 0, 0, 1, 0, 0]), 3),
  );
  const conditional = new LineSegments(
    conditionalGeometry,
    codedMaterial(new LineBasicMaterial({ color: 0x333333 }), "71"),
  );
  (conditional as ConditionalLineCandidate).isConditionalLine = true;

  part.add(mesh, edges, conditional);
  root.add(part);
  return root;
}

describe("LDraw scene transfer round trip", () => {
  it("preserves hierarchy, names, userData, transforms, and geometry", () => {
    const source = buildSourceScene();
    const { root, buffers } = serializeLDrawScene(source);
    // postMessage structured-clones the payload; simulate it so accidental
    // functions or class instances in the snapshot would throw here too.
    const cloned = structuredClone(root);
    const { resolver } = paletteResolver();
    const rebuilt = rebuildLDrawScene(cloned, resolver);

    expect(buffers.length).toBeGreaterThanOrEqual(6);
    expect(rebuilt.name).toBe("__bricky_occ_000001.ldr");
    expect(rebuilt.userData).toEqual({
      numBuildingSteps: 2,
      fileName: "__bricky_occ_000001.ldr",
    });

    const part = rebuilt.children[0] as Group;
    expect(part.name).toBe("__bricky_node_000001.ldr");
    expect(part.userData).toEqual({ buildingStep: 1, colorCode: "71" });
    // Mirrored transforms may decompose into a different but equivalent
    // position/quaternion/scale triple; the composed matrix is the invariant.
    part.updateMatrix();
    const sourcePart = source.children[0] as Group;
    sourcePart.updateMatrix();
    for (const [index, element] of part.matrix.elements.entries()) {
      expect(element).toBeCloseTo(sourcePart.matrix.elements[index]!, 6);
    }
    expect(part.children).toHaveLength(3);

    const mesh = part.children[0] as Mesh;
    const sourceMesh = (source.children[0] as Group).children[0] as Mesh;
    expect(mesh).toBeInstanceOf(Mesh);
    expect(mesh.geometry.getAttribute("position").array).toEqual(
      sourceMesh.geometry.getAttribute("position").array,
    );
    expect(mesh.geometry.groups).toHaveLength(2);
    expect(mesh.geometry.groups[1]).toMatchObject({ start: 3, count: 3, materialIndex: 1 });
  });

  it("resolves palette codes to shared instances by object variant", () => {
    const source = buildSourceScene();
    const { root } = serializeLDrawScene(source);
    const { resolver, main, edge, conditional } = paletteResolver();
    const part = rebuildLDrawScene(structuredClone(root), resolver).children[0] as Group;

    const mesh = part.children[0] as Mesh;
    const edges = part.children[1] as LineSegments;
    const conditionalLines = part.children[2] as LineSegments;

    expect(Array.isArray(mesh.material)).toBe(true);
    expect((mesh.material as Material[])[0]).toBe(main);
    expect(edges.material).toBe(edge);
    expect(conditionalLines.material).toBe(conditional);
    expect((conditionalLines as ConditionalLineCandidate).isConditionalLine).toBe(true);
  });

  it("falls back to serialized properties for non-palette codes", () => {
    const source = buildSourceScene();
    const { root } = serializeLDrawScene(source);
    const { resolver } = paletteResolver();
    const part = rebuildLDrawScene(structuredClone(root), resolver).children[0] as Group;
    const mesh = part.children[0] as Mesh;

    const fallback = (mesh.material as MeshStandardMaterial[])[1]!;
    expect(fallback.color.getHex()).toBe(0xb40000);
    expect(fallback.transparent).toBe(true);
    expect(fallback.opacity).toBe(0.5);
  });
});
