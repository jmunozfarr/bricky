import { Color, Group, LineSegments, Material, Mesh, Object3D, Points } from "three";

import { InstructionSceneIndex, SceneIndexEntry } from "./instructionSceneIndex";

export type InstructionPresentationMode = "focus" | "assembled" | "inspect";

/**
 * Ghost presentation: already-built parts stay clearly recognizable (mostly
 * original color, moderate transparency) while receding behind the current
 * step. Values are validated against both themes' viewer backgrounds.
 */
export const GHOST_OPACITY = 0.45;
export const GHOST_TINT = "#8d7f83";
export const GHOST_TINT_STRENGTH = 0.3;
/** Oxblood accent applied to the edge lines of parts added in the current step. */
export const CURRENT_STEP_EDGE_COLOR = "#a62d43";

type Renderable = Mesh | LineSegments | Points;

type VariantKind = "ghost" | "current";

function isRenderable(object: Object3D): object is Renderable {
  return object instanceof Mesh || object instanceof LineSegments || object instanceof Points;
}

function isGroup(object: Object3D): object is Group {
  return object instanceof Group;
}

function materialsOf(object: Renderable): Material[] {
  return Array.isArray(object.material) ? object.material : [object.material];
}

function assignMaterials(object: Renderable, materials: Material[]): void {
  if (Array.isArray(object.material)) {
    object.material = materials;
    return;
  }
  const [first] = materials;
  if (first !== undefined) object.material = first;
}

/**
 * Applies step visibility, ghosting, and current-step accents to an
 * instruction scene. Applies are incremental: each call diffs the desired
 * presentation against the previously applied one and only touches groups
 * whose state changed, so scrubbing through steps stays cheap on large
 * scenes.
 */
export class InstructionPresentationController {
  private readonly originals = new Map<Renderable, Material[]>();
  private readonly variants = new Map<string, Material>();
  private appliedVariants = new Map<Group, VariantKind>();
  private hiddenGroups = new Set<Group>();
  private normalized = false;

  constructor(
    private readonly model: Group,
    private readonly index: InstructionSceneIndex,
  ) {
    model.traverse((object) => {
      if (isRenderable(object)) this.originals.set(object, materialsOf(object));
    });
  }

  apply(activeOccurrenceId: string, currentStep: number, mode: InstructionPresentationMode): void {
    // Scenes can arrive from the shared cache with visibility left over from a
    // previous mount, so the first apply normalizes every group once.
    if (!this.normalized) {
      this.model.traverse((object) => {
        if (isGroup(object)) object.visible = true;
      });
      this.normalized = true;
    }

    // Only indexed entries carry hierarchical step semantics. Unindexed
    // groups (part geometry inside node wrappers, nested submodel internals)
    // inherit their indexed ancestor's visibility; their three.js
    // `userData.buildingStep` is a flattened cross-submodel counter that must
    // never be compared against the active task's local step (doing so hid
    // attached subassembly geometry — see docs/BUILDER_LOGIC_BUGS.md).
    const desiredVariants = new Map<Group, VariantKind>();
    const desiredHidden = new Set<Group>();
    if (mode !== "inspect") {
      for (const entry of this.index.entries) {
        const step = entryLocalStep(entry, activeOccurrenceId);
        if (step === null) continue;
        classify(entry.group, step, currentStep, mode, desiredVariants, desiredHidden);
      }
    }

    for (const group of this.hiddenGroups) {
      if (!desiredHidden.has(group)) group.visible = true;
    }
    for (const group of desiredHidden) group.visible = false;
    this.hiddenGroups = desiredHidden;

    const restored: Group[] = [];
    for (const [group, kind] of this.appliedVariants) {
      if (desiredVariants.get(group) !== kind) {
        this.restoreGroup(group);
        restored.push(group);
      }
    }
    const forced = this.forcedReapplies(restored, desiredVariants);
    for (const [group, kind] of desiredVariants) {
      if (forced.has(group) || this.appliedVariants.get(group) !== kind) {
        this.applyVariant(group, kind);
      }
    }
    this.appliedVariants = desiredVariants;
  }

  dispose(): void {
    this.restore();
    this.appliedVariants = new Map();
    this.hiddenGroups = new Set();
    for (const material of this.variants.values()) material.dispose();
    this.variants.clear();
  }

  /**
   * Variant groups are usually disjoint, but when a restored group nests with
   * a still-desired one (either direction) the overlapping subtree must be
   * repainted in canonical order to match a from-scratch apply.
   */
  private forcedReapplies(restored: Group[], desired: Map<Group, VariantKind>): Set<Group> {
    const forced = new Set<Group>();
    for (const group of restored) {
      for (let parent = group.parent; parent !== null; parent = parent.parent) {
        if (isGroup(parent) && desired.has(parent)) {
          forced.add(parent);
          break;
        }
      }
      group.traverse((object) => {
        if (object !== group && isGroup(object) && desired.has(object)) forced.add(object);
      });
    }
    for (const ancestor of [...forced]) {
      ancestor.traverse((object) => {
        if (object !== ancestor && isGroup(object) && desired.has(object)) forced.add(object);
      });
    }
    return forced;
  }

  private restore(): void {
    for (const [object, materials] of this.originals) assignMaterials(object, materials);
  }

  private restoreGroup(group: Group): void {
    group.traverse((object) => {
      if (!isRenderable(object)) return;
      const originals = this.originals.get(object);
      if (originals !== undefined) assignMaterials(object, originals);
    });
  }

  private applyVariant(group: Group, kind: VariantKind): void {
    group.traverse((object) => {
      if (!isRenderable(object)) return;
      if (kind === "current" && !(object instanceof LineSegments)) return;
      const originals = this.originals.get(object);
      if (originals === undefined) return;
      assignMaterials(
        object,
        originals.map((material) => this.variant(material, kind)),
      );
    });
  }

  private variant(material: Material, kind: VariantKind): Material {
    const key = `${material.uuid}:${kind}`;
    const cached = this.variants.get(key);
    if (cached) return cached;
    const clone = material.clone();
    if (kind === "ghost") {
      clone.transparent = true;
      clone.opacity = GHOST_OPACITY;
      clone.depthWrite = false;
      const colored = clone as Material & { color?: Color };
      colored.color?.lerp(new Color(GHOST_TINT), GHOST_TINT_STRENGTH);
    } else {
      const colored = clone as Material & { color?: Color };
      colored.color?.set(CURRENT_STEP_EDGE_COLOR);
      clone.transparent = false;
      clone.opacity = 1;
    }
    clone.needsUpdate = true;
    this.variants.set(key, clone);
    return clone;
  }
}

function entryLocalStep(entry: SceneIndexEntry, activeOccurrenceId: string): number | null {
  if (entry.kind === "part" && entry.occurrenceId === activeOccurrenceId) {
    return entry.localStep ?? 1;
  }
  if (entry.kind === "occurrence" && entry.parentOccurrenceId === activeOccurrenceId) {
    return entry.attachmentStep ?? 1;
  }
  return null;
}

function classify(
  group: Group,
  step: number,
  currentStep: number,
  mode: Exclude<InstructionPresentationMode, "inspect">,
  variants: Map<Group, VariantKind>,
  hidden: Set<Group>,
): void {
  if (step > currentStep) {
    hidden.add(group);
    return;
  }
  if (step === currentStep) variants.set(group, "current");
  else if (mode === "focus") variants.set(group, "ghost");
}
