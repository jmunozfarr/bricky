// @vitest-environment jsdom

import { render } from "@testing-library/react";
import { BufferGeometry, Group, Mesh, MeshBasicMaterial } from "three";
import { describe, expect, it, vi } from "vitest";

import { HierarchicalLDrawModel } from "./LDrawModel";
import { INSPECT_MERGED_VIEW_NAME } from "./inspectMergedView";
import { InstructionSceneIndex, SceneIndexEntry } from "./instructionSceneIndex";

const store = vi.hoisted(() => ({ state: { invalidate: () => undefined } }));

vi.mock("@react-three/fiber", () => ({
  useThree: <T,>(selector: (state: { invalidate: () => void }) => T) => selector(store.state),
}));

function partEntry(step: number): { group: Group; entry: SceneIndexEntry } {
  const group = new Group();
  group.add(new Mesh(new BufferGeometry(), new MeshBasicMaterial({ color: "#336699" })));
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
  return { group, entry };
}

describe("HierarchicalLDrawModel frame scheduling", () => {
  it("schedules a frame for every step change on the demand frameloop", () => {
    const invalidate = vi.fn();
    store.state = { invalidate };
    const host = new Group();
    const model = new Group();
    const first = partEntry(1);
    const second = partEntry(2);
    model.add(first.group, second.group);
    const sceneIndex: InstructionSceneIndex = {
      rootOccurrenceId: "occ-000001",
      entries: [first.entry, second.entry],
      objectCount: 6,
    };

    const props = {
      host,
      model,
      sceneIndex,
      activeOccurrenceId: "occ-000001",
      cacheKey: "scene",
      presentationMode: "focus",
    } as const;
    const { rerender } = render(<HierarchicalLDrawModel {...props} selectedStep={1} />);
    expect(second.group.visible).toBe(false);
    const framesAfterMount = invalidate.mock.calls.length;
    expect(framesAfterMount).toBeGreaterThan(0);

    // Advancing a step mutates the scene outside the reconciler; without an
    // explicit invalidate the demand frameloop would never repaint it.
    rerender(<HierarchicalLDrawModel {...props} selectedStep={2} />);
    expect(second.group.visible).toBe(true);
    expect(invalidate.mock.calls.length).toBeGreaterThan(framesAfterMount);
  });

  it("swaps to the merged twin in inspect mode and back for step playback", () => {
    store.state = { invalidate: vi.fn() };
    const host = new Group();
    const model = new Group();
    const first = partEntry(1);
    const second = partEntry(2);
    model.add(first.group, second.group);
    const sceneIndex: InstructionSceneIndex = {
      rootOccurrenceId: "occ-000001",
      entries: [first.entry, second.entry],
      objectCount: 6,
    };

    const props = {
      host,
      model,
      sceneIndex,
      activeOccurrenceId: "occ-000001",
      cacheKey: "scene",
      selectedStep: 1,
    } as const;
    const { rerender } = render(<HierarchicalLDrawModel {...props} presentationMode="inspect" />);

    const merged = model.children.find((child) => child.name === INSPECT_MERGED_VIEW_NAME);
    const firstMesh = first.group.children[0]!;
    const secondMesh = second.group.children[0]!;
    expect(merged).toBeDefined();
    expect(merged!.visible).toBe(true);
    expect(firstMesh.visible).toBe(false);
    expect(secondMesh.visible).toBe(false);

    // Leaving inspect must restore per-part rendering with correct step
    // visibility: meshes shown again, future-step groups re-hidden.
    rerender(<HierarchicalLDrawModel {...props} presentationMode="focus" />);
    expect(merged!.visible).toBe(false);
    expect(firstMesh.visible).toBe(true);
    expect(secondMesh.visible).toBe(true);
    expect(first.group.visible).toBe(true);
    expect(second.group.visible).toBe(false);
  });
});
