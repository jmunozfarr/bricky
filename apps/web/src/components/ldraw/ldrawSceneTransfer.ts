import {
  BufferAttribute,
  BufferGeometry,
  Group,
  LineBasicMaterial,
  LineSegments,
  Material,
  Matrix4,
  Mesh,
  MeshStandardMaterial,
  Object3D,
} from "three";
import { LDrawLoader } from "three/addons/loaders/LDrawLoader.js";
import { LDrawConditionalLineMaterial } from "three/addons/materials/LDrawConditionalLineMaterial.js";

/**
 * Structured-clone-safe snapshot of an LDrawLoader scene graph, so a Web
 * Worker can parse the (main-thread-blocking) source text and hand the
 * result over with transferable geometry buffers. The rebuild must be
 * indistinguishable from a main-thread parse for everything the viewer
 * relies on: group names and hierarchy (instruction scene index), userData
 * (building steps), material arrays and geometry groups (presentation
 * variants), and conditional-line segments (their custom attributes and
 * `isConditionalLine` marker).
 */

type TransferredArray =
  Float32Array | Uint32Array | Uint16Array | Uint8Array | Int32Array | Int16Array | Int8Array;

interface TransferredAttribute {
  array: TransferredArray;
  itemSize: number;
  normalized: boolean;
}

interface TransferredGeometry {
  attributes: Record<string, TransferredAttribute>;
  index: TransferredAttribute | null;
  groups: { start: number; count: number; materialIndex: number }[];
}

export interface TransferredMaterial {
  code: string | null;
  name: string;
  color: number;
  opacity: number;
  transparent: boolean;
  depthWrite: boolean;
}

export type TransferredObjectKind =
  "group" | "mesh" | "line-segments" | "conditional-line-segments";

export interface TransferredObject {
  kind: TransferredObjectKind;
  name: string;
  matrix: number[];
  visible: boolean;
  userData: Record<string, unknown>;
  children: TransferredObject[];
  geometry: TransferredGeometry | null;
  materials: TransferredMaterial[] | null;
  materialIsArray: boolean;
}

export interface SerializedLDrawScene {
  root: TransferredObject;
  buffers: ArrayBuffer[];
}

interface ConditionalLineCandidate {
  isConditionalLine?: boolean;
}

function objectKind(object: Object3D): TransferredObjectKind {
  if (object instanceof LineSegments) {
    return (object as ConditionalLineCandidate).isConditionalLine === true
      ? "conditional-line-segments"
      : "line-segments";
  }
  if (object instanceof Mesh) return "mesh";
  return "group";
}

function sanitizeUserData(userData: Record<string, unknown>): Record<string, unknown> {
  try {
    return JSON.parse(JSON.stringify(userData)) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function serializeMaterialSlot(material: Material): TransferredMaterial {
  const withColor = material as Material & { color?: { getHex(): number } };
  const code = (material.userData as Record<string, unknown>).code;
  return {
    code: typeof code === "string" ? code : null,
    name: material.name,
    color: typeof withColor.color?.getHex === "function" ? withColor.color.getHex() : 0xffffff,
    opacity: material.opacity,
    transparent: material.transparent,
    depthWrite: material.depthWrite,
  };
}

function serializeAttribute(
  attribute: BufferAttribute,
  buffers: Set<ArrayBuffer>,
): TransferredAttribute {
  const array = attribute.array as TransferredArray;
  if (array.buffer instanceof ArrayBuffer) {
    buffers.add(array.buffer);
  }
  return { array, itemSize: attribute.itemSize, normalized: attribute.normalized };
}

function serializeGeometry(
  geometry: BufferGeometry,
  buffers: Set<ArrayBuffer>,
): TransferredGeometry {
  const attributes: Record<string, TransferredAttribute> = {};
  for (const [name, attribute] of Object.entries(geometry.attributes)) {
    if (attribute instanceof BufferAttribute) {
      attributes[name] = serializeAttribute(attribute, buffers);
    }
  }
  return {
    attributes,
    index: geometry.index === null ? null : serializeAttribute(geometry.index, buffers),
    groups: geometry.groups.map((group) => ({
      start: group.start,
      count: group.count,
      materialIndex: group.materialIndex ?? 0,
    })),
  };
}

function serializeObject(object: Object3D, buffers: Set<ArrayBuffer>): TransferredObject {
  const kind = objectKind(object);
  const renderable = kind === "group" ? null : (object as Mesh | LineSegments);
  object.updateMatrix();
  return {
    kind,
    name: object.name,
    matrix: object.matrix.toArray(),
    visible: object.visible,
    userData: sanitizeUserData(object.userData as Record<string, unknown>),
    children: object.children.map((child) => serializeObject(child, buffers)),
    geometry: renderable === null ? null : serializeGeometry(renderable.geometry, buffers),
    materials:
      renderable === null
        ? null
        : (Array.isArray(renderable.material) ? renderable.material : [renderable.material]).map(
            serializeMaterialSlot,
          ),
    materialIsArray: renderable === null ? false : Array.isArray(renderable.material),
  };
}

export function serializeLDrawScene(root: Object3D): SerializedLDrawScene {
  const buffers = new Set<ArrayBuffer>();
  return { root: serializeObject(root, buffers), buffers: [...buffers] };
}

export interface LDrawMaterialResolver {
  main(code: string): Material | null;
  edge(code: string): Material | null;
  conditional(code: string): Material | null;
}

interface LoaderMaterialCaches {
  edgeMaterialCache: WeakMap<Material, Material>;
  conditionalEdgeMaterialCache: WeakMap<Material, Material>;
}

/** Resolves palette materials exactly like LDrawLoader does during a parse. */
export function createLoaderMaterialResolver(loader: LDrawLoader): LDrawMaterialResolver {
  const caches = loader as unknown as LoaderMaterialCaches;
  const main = (code: string): Material | null => loader.getMaterial(code);
  const edge = (code: string): Material | null => {
    const mainMaterial = main(code);
    return mainMaterial === null ? null : (caches.edgeMaterialCache.get(mainMaterial) ?? null);
  };
  return {
    main,
    edge,
    conditional: (code) => {
      const edgeMaterial = edge(code);
      return edgeMaterial === null
        ? null
        : (caches.conditionalEdgeMaterialCache.get(edgeMaterial) ?? null);
    },
  };
}

function fallbackMaterial(kind: TransferredObjectKind, slot: TransferredMaterial): Material {
  const common = {
    color: slot.color,
    opacity: slot.opacity,
    transparent: slot.transparent,
    depthWrite: slot.depthWrite,
  };
  let material: Material;
  if (kind === "mesh") {
    material = new MeshStandardMaterial({
      ...common,
      roughness: 0.3,
      metalness: 0,
      polygonOffset: true,
      polygonOffsetFactor: 1,
    });
  } else if (kind === "conditional-line-segments") {
    material = new LDrawConditionalLineMaterial({ ...common, fog: true });
  } else {
    material = new LineBasicMaterial(common);
  }
  material.name = slot.name;
  return material;
}

function resolveMaterialSlot(
  kind: TransferredObjectKind,
  slot: TransferredMaterial,
  resolver: LDrawMaterialResolver,
): Material {
  if (slot.code !== null) {
    const resolved =
      kind === "mesh"
        ? resolver.main(slot.code)
        : kind === "conditional-line-segments"
          ? resolver.conditional(slot.code)
          : resolver.edge(slot.code);
    if (resolved !== null) return resolved;
  }
  return fallbackMaterial(kind, slot);
}

function rebuildGeometry(transferred: TransferredGeometry): BufferGeometry {
  const geometry = new BufferGeometry();
  for (const [name, attribute] of Object.entries(transferred.attributes)) {
    geometry.setAttribute(
      name,
      new BufferAttribute(attribute.array, attribute.itemSize, attribute.normalized),
    );
  }
  if (transferred.index !== null) {
    geometry.setIndex(new BufferAttribute(transferred.index.array, transferred.index.itemSize));
  }
  for (const group of transferred.groups) {
    geometry.addGroup(group.start, group.count, group.materialIndex);
  }
  return geometry;
}

function rebuildObject(transferred: TransferredObject, resolver: LDrawMaterialResolver): Object3D {
  let object: Object3D;
  if (
    transferred.kind === "group" ||
    transferred.geometry === null ||
    transferred.materials === null
  ) {
    object = new Group();
  } else {
    const geometry = rebuildGeometry(transferred.geometry);
    const materials = transferred.materials.map((slot) =>
      resolveMaterialSlot(transferred.kind, slot, resolver),
    );
    const material = transferred.materialIsArray
      ? materials
      : (materials[0] ??
        fallbackMaterial(transferred.kind, {
          code: null,
          name: "",
          color: 0xffffff,
          opacity: 1,
          transparent: false,
          depthWrite: true,
        }));
    if (transferred.kind === "mesh") {
      object = new Mesh(geometry, material);
    } else {
      object = new LineSegments(geometry, material);
      if (transferred.kind === "conditional-line-segments") {
        (object as ConditionalLineCandidate).isConditionalLine = true;
      }
    }
  }
  object.name = transferred.name;
  object.visible = transferred.visible;
  object.userData = transferred.userData;
  const matrix = new Matrix4().fromArray(transferred.matrix);
  matrix.decompose(object.position, object.quaternion, object.scale);
  for (const child of transferred.children) {
    object.add(rebuildObject(child, resolver));
  }
  return object;
}

export function rebuildLDrawScene(
  transferred: TransferredObject,
  resolver: LDrawMaterialResolver,
): Group {
  const root = rebuildObject(transferred, resolver);
  if (root instanceof Group) {
    return root as Group;
  }
  const wrapper = new Group();
  wrapper.add(root);
  return wrapper;
}
