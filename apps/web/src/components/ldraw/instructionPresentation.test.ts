import {
  BufferGeometry,
  Color,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
} from "three";
import { describe, expect, it, vi } from "vitest";

import {
  CURRENT_STEP_EDGE_COLOR,
  GHOST_OPACITY,
  GHOST_TINT,
  InstructionPresentationController,
} from "./instructionPresentation";
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
    const ghost = (first.group.children[0] as Mesh).material as MeshBasicMaterial;
    expect(ghost.opacity).toBe(GHOST_OPACITY);
    expect(ghost.opacity).toBeGreaterThanOrEqual(0.4);
    // The ghost must stay recognizable: closer to the part's own color than to the tint.
    const original = new Color("#336699");
    const tint = new Color(GHOST_TINT);
    const distanceToOriginal =
      (ghost.color.r - original.r) ** 2 +
      (ghost.color.g - original.g) ** 2 +
      (ghost.color.b - original.b) ** 2;
    const distanceToTint =
      (ghost.color.r - tint.r) ** 2 + (ghost.color.g - tint.g) ** 2 + (ghost.color.b - tint.b) ** 2;
    expect(distanceToOriginal).toBeLessThan(distanceToTint);
    expect((second.group.children[0] as Mesh).material).toBe(second.fill);
    expect((second.group.children[1] as LineSegments).material).not.toBe(second.edge);
    const currentEdge = (second.group.children[1] as LineSegments).material as LineBasicMaterial;
    expect(currentEdge.color.getHexString()).toBe(new Color(CURRENT_STEP_EDGE_COLOR).getHexString());
    expect(third.group.visible).toBe(false);

    presentation.apply("occ-000001", 2, "inspect");
    expect((first.group.children[0] as Mesh).material).toBe(first.fill);
    expect((second.group.children[1] as LineSegments).material).toBe(second.edge);
    expect(third.group.visible).toBe(true);
    presentation.dispose();
  });

  it("scrubs steps in both directions with consistent presentation", () => {
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

    for (const step of [1, 2, 3, 2, 1, 3]) presentation.apply("occ-000001", step, "focus");

    // Final state (step 3) must match a from-scratch apply at step 3.
    const firstFill = (first.group.children[0] as Mesh).material as MeshBasicMaterial;
    expect(firstFill).not.toBe(first.fill);
    expect(firstFill.opacity).toBe(GHOST_OPACITY);
    const secondFill = (second.group.children[0] as Mesh).material as MeshBasicMaterial;
    expect(secondFill.opacity).toBe(GHOST_OPACITY);
    expect((third.group.children[0] as Mesh).material).toBe(third.fill);
    const thirdEdge = (third.group.children[1] as LineSegments).material as LineBasicMaterial;
    expect(thirdEdge.color.getHexString()).toBe(new Color(CURRENT_STEP_EDGE_COLOR).getHexString());
    expect(first.group.visible).toBe(true);
    expect(second.group.visible).toBe(true);
    expect(third.group.visible).toBe(true);

    presentation.apply("occ-000001", 1, "focus");
    expect((first.group.children[0] as Mesh).material).toBe(first.fill);
    expect(second.group.visible).toBe(false);
    expect(third.group.visible).toBe(false);
    presentation.dispose();
  });

  it("performs no scene work when the applied state has not changed", () => {
    const model = new Group();
    const first = partEntry(1);
    const second = partEntry(2);
    model.add(first.group, second.group);
    const index: InstructionSceneIndex = {
      rootOccurrenceId: "occ-000001",
      entries: [first.entry, second.entry],
      objectCount: 6,
    };
    const presentation = new InstructionPresentationController(model, index);
    presentation.apply("occ-000001", 2, "focus");

    const traversals = [model, first.group, second.group].map((group) =>
      vi.spyOn(group, "traverse"),
    );
    presentation.apply("occ-000001", 2, "focus");
    for (const spy of traversals) expect(spy).not.toHaveBeenCalled();

    // Moving one step only repaints the two groups whose state changed.
    presentation.apply("occ-000001", 1, "focus");
    expect(traversals[0]).not.toHaveBeenCalled();
    expect((first.group.children[1] as LineSegments).material).not.toBe(first.edge);
    expect(second.group.visible).toBe(false);
    presentation.dispose();
  });

  it("applies fallback building-step groups without retraversing the scene", () => {
    const model = new Group();
    const indexed = partEntry(1);
    const fallbackFill = new MeshBasicMaterial({ color: "#996633" });
    const fallback = new Group();
    fallback.userData.buildingStep = 1; // zero-based: local step 2
    fallback.add(new Mesh(new BufferGeometry(), fallbackFill));
    model.add(indexed.group, fallback);
    const index: InstructionSceneIndex = {
      rootOccurrenceId: "occ-000001",
      entries: [indexed.entry],
      objectCount: 4,
    };
    const presentation = new InstructionPresentationController(model, index);

    presentation.apply("occ-000001", 1, "focus");
    expect(fallback.visible).toBe(false);

    presentation.apply("occ-000001", 2, "focus");
    expect(fallback.visible).toBe(true);
    const indexedFill = (indexed.group.children[0] as Mesh).material as MeshBasicMaterial;
    expect(indexedFill.opacity).toBe(GHOST_OPACITY);
    expect((fallback.children[0] as Mesh).material).toBe(fallbackFill);
    presentation.dispose();
    expect((indexed.group.children[0] as Mesh).material).toBe(indexed.fill);
  });
});
