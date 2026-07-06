import { describe, expect, it, vi } from "vitest";

import { LatestScopeLoader, ScopeLoadSupersededError } from "./boundedSceneLoader";

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

describe("bounded instruction scene loader", () => {
  it("coalesces rapid navigation to the newest pending parse", async () => {
    const loads: { key: string; result: Deferred<string> }[] = [];
    let active = 0;
    let maximumActive = 0;
    const disposed: string[] = [];
    const loader = new LatestScopeLoader<string, string>(
      3,
      async (key) => {
        active += 1;
        maximumActive = Math.max(maximumActive, active);
        const result = deferred<string>();
        loads.push({ key, result });
        const value = await result.promise;
        active -= 1;
        return value;
      },
      (value) => disposed.push(value),
    );
    loader.setNamespace("model");

    const first = loader.request("a", "a");
    const middle = loader.request("b", "b");
    const latest = loader.request("c", "c");
    const middleResult = expect(middle).rejects.toBeInstanceOf(ScopeLoadSupersededError);

    expect(loads.map((item) => item.key)).toEqual(["a"]);
    loads[0]!.result.resolve("scene-a");
    await expect(first).rejects.toBeInstanceOf(ScopeLoadSupersededError);
    await middleResult;
    await vi.waitFor(() => expect(loads.map((item) => item.key)).toEqual(["a", "c"]));
    loads[1]!.result.resolve("scene-c");

    await expect(latest).resolves.toBe("scene-c");
    expect(maximumActive).toBe(1);
    expect(disposed).toEqual(["scene-a"]);
  });

  it("settles a cancel-then-rerequest of the same key instead of sticking (A5)", async () => {
    const loads: { key: string; result: Deferred<string> }[] = [];
    const disposed: string[] = [];
    const loader = new LatestScopeLoader<string, string>(
      3,
      async (key) => {
        const result = deferred<string>();
        loads.push({ key, result });
        return result.promise;
      },
      (value) => disposed.push(value),
    );
    loader.setNamespace("model");

    // Unmount/remount (StrictMode shape): the first requester cancels, then
    // a fresh requester asks for the same key while the old parse is still
    // in flight. The new request must not join the stale task.
    const first = loader.request("a", "a");
    loader.cancel("a");
    const second = loader.request("a", "a");
    const firstResult = expect(first).rejects.toBeInstanceOf(ScopeLoadSupersededError);

    // The uncancellable stale parse eventually settles; its result is
    // disposed and the fresh request re-parses and resolves.
    loads[0]!.result.resolve("scene-a-stale");
    await firstResult;
    await vi.waitFor(() => expect(loads).toHaveLength(2));
    loads[1]!.result.resolve("scene-a-fresh");

    await expect(second).resolves.toBe("scene-a-fresh");
    expect(disposed).toEqual(["scene-a-stale"]);
  });

  it("reuses successful scenes and evicts least-recently-used entries", async () => {
    const load = vi.fn((key: string) => Promise.resolve(`scene-${key}`));
    const dispose = vi.fn<(value: string) => void>();
    const loader = new LatestScopeLoader(2, load, dispose);
    loader.setNamespace("model-one");

    await loader.request("a", "a");
    await loader.request("b", "b");
    await loader.request("a", "a");
    await loader.request("c", "c");

    expect(load).toHaveBeenCalledTimes(3);
    expect(dispose).toHaveBeenCalledWith("scene-b");
    await loader.request("a", "a");
    expect(load).toHaveBeenCalledTimes(3);

    loader.setNamespace("model-two");
    expect(dispose).toHaveBeenCalledWith("scene-a");
    expect(dispose).toHaveBeenCalledWith("scene-c");
  });
});
