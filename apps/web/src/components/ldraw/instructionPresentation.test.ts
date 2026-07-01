import {
  BufferGeometry,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
} from "three";
import { describe, expect, it } from "vitest";

import { InstructionPresentationController } from "./instructionPresentation";
import { InstructionSceneIndex, SceneIndexEntry } from "./instructionSceneIndex";

function partEntry(step: number) {
  const group = new Group();
  const fill = new MeshBasicMaterial({ color: "#336699" });
  const edge = new LineBasicMaterial({ color: "#111111" });
  group.add(new Mesh(new BufferGeometry(), fill));
  group.add(new LineSegments(new BufferGeometry(), edge));
  const entry: SceneIndexEntry = {
    kind: "part",
    occurrenceId: "occ-000001",
    parentOccurrenceId: "occ-000001",
    localStep: step,
    attachmentStep: null,
    definitionName: "main.ldr",
    instructionNodeId: `node-${step}`,
    traversalPosition: step,
    group,
  };
  return { group, fill, edge, entry };
}

describe("instruction scene presentation", () => {
  it("ghosts previous parts, accents current edges, and hides future parts", () => {
    const model = new Group();
    const first = partEntry(1);
    const second = partEntry(2);
    const third = partEntry(3);
    model.add(first.group, second.group, third.group);
    const index: InstructionSceneIndex = {
      rootOccurrenceId: "occ-000001",
      entries: [first.entry, second.entry, third.entry],
      objectCount: 9,
    };
    const presentation = new InstructionPresentationController(model, index);

    presentation.apply("occ-000001", 2, "focus");

    expect((first.group.children[0] as Mesh).material).not.toBe(first.fill);
    expect(((first.group.children[0] as Mesh).material as MeshBasicMaterial).opacity).toBe(0.22);
    expect((second.group.children[0] as Mesh).material).toBe(second.fill);
    expect((second.group.children[1] as LineSegments).material).not.toBe(second.edge);
    expect(third.group.visible).toBe(false);

    presentation.apply("occ-000001", 2, "inspect");
    expect((first.group.children[0] as Mesh).material).toBe(first.fill);
    expect((second.group.children[1] as LineSegments).material).toBe(second.edge);
    expect(third.group.visible).toBe(true);
    presentation.dispose();
  });
});
