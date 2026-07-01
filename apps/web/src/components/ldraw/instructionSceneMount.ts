import { Group } from "three";

import type { InstructionSceneIndex } from "./instructionSceneIndex";

export interface MountedInstructionScene {
  cacheKey: string;
  model: Group;
  sceneIndex: InstructionSceneIndex;
}

export interface InstructionSceneDiagnostic {
  cacheKey: string;
  uuid: string;
  name: string;
  parent: string | null;
  childCount: number;
  indexedNodeIds: string[];
  mounted: boolean;
}

export function instructionSceneDiagnostic(
  scene: MountedInstructionScene,
): InstructionSceneDiagnostic {
  return {
    cacheKey: scene.cacheKey,
    uuid: scene.model.uuid,
    name: scene.model.name,
    parent:
      scene.model.parent === null
        ? null
        : scene.model.parent.name || scene.model.parent.uuid,
    childCount: scene.model.children.length,
    indexedNodeIds: scene.sceneIndex.entries.flatMap((entry) =>
      entry.instructionNodeId === null ? [] : [entry.instructionNodeId],
    ),
    mounted: scene.model.parent !== null,
  };
}

/** Makes cache ownership independent from membership in the visible Three.js tree. */
export class ExclusiveInstructionSceneMount {
  private active: MountedInstructionScene | null = null;

  constructor(private readonly host: Group) {}

  activate(scene: MountedInstructionScene): void {
    if (this.active?.model !== scene.model) {
      this.active?.model.removeFromParent();
    }
    for (const child of [...this.host.children]) {
      if (child !== scene.model) child.removeFromParent();
    }
    if (scene.model.parent !== this.host) {
      scene.model.removeFromParent();
      this.host.add(scene.model);
    }
    this.active = scene;
  }

  deactivate(model: Group): void {
    if (this.active?.model !== model) return;
    model.removeFromParent();
    this.active = null;
  }

  current(): MountedInstructionScene | null {
    return this.active;
  }
}
