import { describe, expect, it, vi } from "vitest";
import { Group } from "three";

import { LatestScopeLoader, ScopeLoadSupersededError } from "./boundedSceneLoader";
import type { InstructionSceneIndex } from "./instructionSceneIndex";
import {
  ExclusiveInstructionSceneMount,
  instructionSceneDiagnostic,
  MountedInstructionScene,
} from "./instructionSceneMount";

interface Deferred<Value> {
  promise: Promise<Value>;
  resolve: (value: Value) => void;
}

function deferred<Value>(): Deferred<Value> {
  let resolve!: (value: Value) => void;
  const promise = new Promise<Value>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

function scene(cacheKey: string, nodeIds: string[]): MountedInstructionScene {
  const model = new Group();
  model.name = cacheKey;
  for (const nodeId of nodeIds) {
    const node = new Group();
    node.name = `__bricky_${nodeId.replace("-", "_")}.ldr`;
    model.add(node);
  }
  const sceneIndex: InstructionSceneIndex = {
    rootOccurrenceId: "occ-000001",
    objectCount: model.children.length + 1,
    entries: nodeIds.map((instructionNodeId, index) => ({
      kind: "part",
      occurrenceId: "occ-000001",
      parentOccurrenceId: "occ-000001",
      localStep: index < 2 ? 1 : 2,
      attachmentStep: null,
      definitionName: "main.ldr",
      instructionNodeId,
      traversalPosition: index + 1,
      group: model.children[index] as Group,
    })),
  };
  return { cacheKey, model, sceneIndex };
}

describe("exclusive instruction scene mounting", () => {
  it("detaches step 1 before mounting step 2 and keeps cached scenes inactive", () => {
    const canvas = new Group();
    const host = new Group();
    host.name = "canvas-host";
    canvas.add(host);
    const mount = new ExclusiveInstructionSceneMount(host);
    const step1 = scene("step-1", ["node-000001", "node-000002"]);
    const step2 = scene("step-2", [
      "node-000001",
      "node-000002",
      "node-000003",
      "node-000004",
    ]);

    mount.activate(step1);
    expect(host.children).toEqual([step1.model]);
    mount.activate(step2);

    expect(host.children).toEqual([step2.model]);
    expect(step1.model.parent).toBeNull();
    expect(step2.model.parent).toBe(host);
    expect(canvas.children).toEqual([host]);
    expect(instructionSceneDiagnostic(step1)).toMatchObject({
      cacheKey: "step-1",
      indexedNodeIds: ["node-000001", "node-000002"],
      mounted: false,
    });
    expect(instructionSceneDiagnostic(step2)).toMatchObject({
      cacheKey: "step-2",
      indexedNodeIds: [
        "node-000001",
        "node-000002",
        "node-000003",
        "node-000004",
      ],
      mounted: true,
    });
  });

  it("reactivates cached steps without duplicate roots or node objects", () => {
    const host = new Group();
    const mount = new ExclusiveInstructionSceneMount(host);
    const step1 = scene("step-1", ["node-000001", "node-000002"]);
    const step2 = scene("step-2", [
      "node-000001",
      "node-000002",
      "node-000003",
      "node-000004",
    ]);

    for (const active of [step1, step2, step1, step2]) mount.activate(active);

    expect(host.children).toEqual([step2.model]);
    expect(step1.model.parent).toBeNull();
    const names: string[] = [];
    step2.model.traverse((object) => {
      if (object.name.startsWith("__bricky_node_")) names.push(object.name);
    });
    expect(new Set(names).size).toBe(4);
    expect(names).toHaveLength(4);
  });

  it("never mounts stale results and rapid navigation leaves only the newest scene", async () => {
    const pending = new Map<string, Deferred<MountedInstructionScene>>();
    const disposed: MountedInstructionScene[] = [];
    const loader = new LatestScopeLoader<string, MountedInstructionScene>(
      3,
      async (key) => {
        const result = deferred<MountedInstructionScene>();
        pending.set(key, result);
        return result.promise;
      },
      (value) => {
        value.model.removeFromParent();
        disposed.push(value);
      },
    );
    loader.setNamespace("model");
    const host = new Group();
    const mount = new ExclusiveInstructionSceneMount(host);

    const first = loader.request("step-1", "step-1").then((value) => {
      mount.activate(value);
      return value;
    });
    const second = loader.request("step-2", "step-2");
    const third = loader.request("step-3", "step-3");
    const newest = loader.request("step-2", "step-2").then((value) => {
      mount.activate(value);
      return value;
    });
    void second.catch(() => undefined);
    void third.catch(() => undefined);

    const stale = scene("step-1", ["node-000001", "node-000002"]);
    pending.get("step-1")!.resolve(stale);
    await expect(first).rejects.toBeInstanceOf(ScopeLoadSupersededError);
    await vi.waitFor(() => expect(pending.has("step-2")).toBe(true));
    const final = scene("step-2", [
      "node-000001",
      "node-000002",
      "node-000003",
      "node-000004",
    ]);
    pending.get("step-2")!.resolve(final);
    await expect(newest).resolves.toBe(final);

    expect(stale.model.parent).toBeNull();
    expect(disposed).toEqual([stale]);
    expect(host.children).toEqual([final.model]);
  });

  it("evicts and clears scenes exactly once while detaching any active root", async () => {
    const scenes = new Map<string, MountedInstructionScene>();
    const dispose = vi.fn((value: MountedInstructionScene) => {
      value.model.removeFromParent();
    });
    const loader = new LatestScopeLoader<string, MountedInstructionScene>(
      2,
      async (key) => {
        const value = scene(key, [`node-${key}`]);
        scenes.set(key, value);
        return value;
      },
      dispose,
    );
    const host = new Group();
    const mount = new ExclusiveInstructionSceneMount(host);
    loader.setNamespace("model-one");
    const first = await loader.request("one", "one");
    const second = await loader.request("two", "two");
    mount.activate(second);
    const third = await loader.request("three", "three");
    mount.activate(third);

    expect(dispose).toHaveBeenCalledTimes(1);
    expect(dispose).toHaveBeenCalledWith(first);
    expect(first.model.parent).toBeNull();

    loader.setNamespace("model-two");
    expect(dispose).toHaveBeenCalledTimes(3);
    expect(second.model.parent).toBeNull();
    expect(third.model.parent).toBeNull();
    loader.clear();
    expect(dispose).toHaveBeenCalledTimes(3);
  });
});
