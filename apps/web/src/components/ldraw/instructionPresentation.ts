import {
  Color,
  Group,
  LineSegments,
  Material,
  Mesh,
  Object3D,
  Points,
} from "three";

import { InstructionSceneIndex, SceneIndexEntry } from "./instructionSceneIndex";

export type InstructionPresentationMode = "focus" | "assembled" | "inspect";

type Renderable = Mesh | LineSegments | Points;

function isRenderable(object: Object3D): object is Renderable {
  return object instanceof Mesh || object instanceof LineSegments || object instanceof Points;
}

function materialsOf(object: Renderable): Material[] {
  return Array.isArray(object.material) ? object.material : [object.material];
}

function assignMaterials(object: Renderable, materials: Material[]): void {
  object.material = Array.isArray(object.material) ? materials : materials[0]!;
}

export class InstructionPresentationController {
  private readonly originals = new Map<Renderable, Material[]>();
  private readonly variants = new Map<string, Material>();
  private readonly indexedGroups: Set<Group>;

  constructor(
    private readonly model: Group,
    private readonly index: InstructionSceneIndex,
  ) {
    this.indexedGroups = new Set(index.entries.map((entry) => entry.group));
    model.traverse((object) => {
      if (isRenderable(object)) this.originals.set(object, materialsOf(object));
    });
  }

  apply(
    activeOccurrenceId: string,
    currentStep: number,
    mode: InstructionPresentationMode,
  ): void {
    this.restore();
    this.model.traverse((object) => {
      if (object instanceof Group) object.visible = true;
    });
    if (mode === "inspect") return;

    for (const entry of this.index.entries) {
      this.applyEntry(entry, activeOccurrenceId, currentStep, mode);
    }

    this.model.traverse((object) => {
      if (!(object instanceof Group) || this.indexedGroups.has(object)) return;
      const step = object.userData.buildingStep;
      if (typeof step !== "number" || !Number.isInteger(step)) return;
      const localStep = step + 1;
      object.visible = localStep <= currentStep;
      if (!object.visible) return;
      if (localStep === currentStep) this.applyCurrent(object);
      else if (mode === "focus") this.applyGhost(object);
    });
  }

  dispose(): void {
    this.restore();
    for (const material of this.variants.values()) material.dispose();
    this.variants.clear();
  }

  private applyEntry(
    entry: SceneIndexEntry,
    activeOccurrenceId: string,
    currentStep: number,
    mode: Exclude<InstructionPresentationMode, "inspect">,
  ): void {
    if (entry.kind === "part" && entry.occurrenceId === activeOccurrenceId) {
      const step = entry.localStep ?? 1;
      entry.group.visible = step <= currentStep;
      if (!entry.group.visible) return;
      if (step === currentStep) this.applyCurrent(entry.group);
      else if (mode === "focus") this.applyGhost(entry.group);
      return;
    }
    if (entry.kind === "occurrence" && entry.parentOccurrenceId === activeOccurrenceId) {
      const step = entry.attachmentStep ?? 1;
      entry.group.visible = step <= currentStep;
      if (!entry.group.visible) return;
      if (step === currentStep) this.applyCurrent(entry.group);
      else if (mode === "focus") this.applyGhost(entry.group);
    }
  }

  private restore(): void {
    for (const [object, materials] of this.originals) assignMaterials(object, materials);
  }

  private applyGhost(group: Group): void {
    group.traverse((object) => {
      if (!isRenderable(object)) return;
      assignMaterials(
        object,
        this.originals.get(object)!.map((material) => this.variant(material, "ghost")),
      );
    });
  }

  private applyCurrent(group: Group): void {
    group.traverse((object) => {
      if (!(object instanceof LineSegments)) return;
      assignMaterials(
        object,
        this.originals.get(object)!.map((material) => this.variant(material, "current")),
      );
    });
  }

  private variant(material: Material, kind: "ghost" | "current"): Material {
    const key = `${material.uuid}:${kind}`;
    const cached = this.variants.get(key);
    if (cached) return cached;
    const clone = material.clone();
    if (kind === "ghost") {
      clone.transparent = true;
      clone.opacity = 0.22;
      clone.depthWrite = false;
      const colored = clone as Material & { color?: Color };
      colored.color?.lerp(new Color("#8d7f83"), 0.72);
    } else {
      const colored = clone as Material & { color?: Color };
      colored.color?.set("#a62d43");
      clone.transparent = false;
      clone.opacity = 1;
    }
    clone.needsUpdate = true;
    this.variants.set(key, clone);
    return clone;
  }
}
