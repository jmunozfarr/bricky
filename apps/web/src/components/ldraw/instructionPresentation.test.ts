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

function occurrenceEntry(occurrenceId: string, attachmentStep: number) {
  const group = new Group();
  const fill = new MeshBasicMaterial({ color: "#996633" });
  const edge = new LineBasicMaterial({ color: "#111111" });
  group.add(new Mesh(new BufferGeometry(), fill));
  group.add(new LineSegments(new BufferGeometry(), edge));
  const entry: SceneIndexEntry = {
    kind: "occurrence",
    occurrenceId,
    parentOccurrenceId: "occ-000001",
    localStep: null,
    attachmentStep,
    definitionName: "wing.ldr",
    instructionNodeId: null,
    traversalPosition: attachmentStep,
    group,
  };
  return { group, fill, edge, entry };
}

describe("instruction scene presentation", () => {
  it("presents repeated placements of one definition independently (A7)", () => {
    const model = new Group();
    // Two occurrences of the same submodel definition, attached at
    // different parent steps — they must never share presentation state.
    const early = occurrenceEntry("occ-000002", 1);
    const late = occurrenceEntry("occ-000003", 2);
    model.add(early.group, late.group);
    const index: InstructionSceneIndex = {
      rootOccurrenceId: "occ-000001",
      entries: [early.entry, late.entry],
      objectCount: 6,
    };
    const presentation = new InstructionPresentationController(model, index);

    presentation.apply("occ-000001", 1, "focus");
    expect(early.group.visible).toBe(true);
    expect(late.group.visible).toBe(false);
    // The step-1 placement is current: accent edges, original fill.
    expect((early.group.children[1] as LineSegments).material).not.toBe(early.edge);
    expect((early.group.children[0] as Mesh).material).toBe(early.fill);

    presentation.apply("occ-000001", 2, "focus");
    expect(late.group.visible).toBe(true);
    // The step-1 placement ghosts while its twin definition is current.
    const ghost = (early.group.children[0] as Mesh).material as MeshBasicMaterial;
    expect(ghost).not.toBe(early.fill);
    expect(ghost.opacity).toBe(GHOST_OPACITY);
    expect((late.group.children[0] as Mesh).material).toBe(late.fill);
    expect((late.group.children[1] as LineSegments).material).not.toBe(late.edge);
  });

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
    expect(currentEdge.color.getHexString()).toBe(
      new Color(CURRENT_STEP_EDGE_COLOR).getHexString(),
    );
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

  it("never gates unindexed geometry by its flattened building step (Bugatti bug)", () => {
    // The three.js loader stamps a cross-submodel cumulative buildingStep on
    // the geometry groups inside node wrappers. Comparing that number against
    // the active task's local step hid attached subassembly internals — the
    // groups must simply inherit their indexed ancestor's visibility.
    const model = new Group();
    const indexed = partEntry(1);
    const inner = new Group();
    inner.userData.buildingStep = 24; // flattened counter far beyond local steps
    inner.add(new Mesh(new BufferGeometry(), new MeshBasicMaterial({ color: "#996633" })));
    indexed.group.add(inner);
    model.add(indexed.group);
    const index: InstructionSceneIndex = {
      rootOccurrenceId: "occ-000001",
      entries: [indexed.entry],
      objectCount: 5,
    };
    const presentation = new InstructionPresentationController(model, index);

    presentation.apply("occ-000001", 1, "focus");
    expect(indexed.group.visible).toBe(true);
    expect(inner.visible).toBe(true);
    presentation.dispose();
  });

  it("shows an attached child complete, including its own deep internals", () => {
    const model = new Group();
    // Child subassembly attached at parent step 2. Its internals: a part of
    // the child at the child's local step 3, and a grandchild occurrence —
    // both nested inside the child wrapper and both beyond the parent's
    // step numbers.
    const child = occurrenceEntry("occ-000002", 2);
    const childPartFill = new MeshBasicMaterial({ color: "#663399" });
    const childPart = new Group();
    childPart.add(new Mesh(new BufferGeometry(), childPartFill));
    const childPartEntry: SceneIndexEntry = {
      kind: "part",
      occurrenceId: "occ-000002",
      parentOccurrenceId: "occ-000002",
      localStep: 3,
      attachmentStep: null,
      definitionName: "wing.ldr",
      instructionNodeId: "node-900",
      traversalPosition: 10,
      group: childPart,
    };
    const grandchild = new Group();
    grandchild.add(new Mesh(new BufferGeometry(), new MeshBasicMaterial({ color: "#339966" })));
    const grandchildEntry: SceneIndexEntry = {
      kind: "occurrence",
      occurrenceId: "occ-000003",
      parentOccurrenceId: "occ-000002",
      localStep: null,
      attachmentStep: 1,
      definitionName: "axle.ldr",
      instructionNodeId: null,
      traversalPosition: 11,
      group: grandchild,
    };
    child.group.add(childPart, grandchild);
    model.add(child.group);
    const index: InstructionSceneIndex = {
      rootOccurrenceId: "occ-000001",
      entries: [child.entry, childPartEntry, grandchildEntry],
      objectCount: 9,
    };
    const presentation = new InstructionPresentationController(model, index);

    // Before the attachment step the whole child subtree is hidden.
    presentation.apply("occ-000001", 1, "focus");
    expect(child.group.visible).toBe(false);

    // From the attachment step onward the child renders fully assembled:
    // its own parts and grandchildren are not gated by the parent timeline.
    presentation.apply("occ-000001", 2, "focus");
    expect(child.group.visible).toBe(true);
    expect(childPart.visible).toBe(true);
    expect(grandchild.visible).toBe(true);

    presentation.apply("occ-000001", 3, "focus");
    expect(child.group.visible).toBe(true);
    expect(childPart.visible).toBe(true);
    expect(grandchild.visible).toBe(true);
    presentation.dispose();
  });
});
