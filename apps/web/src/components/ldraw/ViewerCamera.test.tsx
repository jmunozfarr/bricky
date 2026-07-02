// @vitest-environment jsdom

import { act, render } from "@testing-library/react";
import { PerspectiveCamera } from "three";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ViewerCamera } from "./ViewerCamera";

interface FakeStoreState {
  camera: PerspectiveCamera;
  gl: { domElement: HTMLCanvasElement };
  invalidate: () => void;
  performance: { current: number; min: number; regress: () => void };
}

const harness = vi.hoisted(() => {
  const constructed: FakeOrbitControls[] = [];

  class FakeOrbitControls {
    enableDamping = true;
    screenSpacePanning = false;
    disposed = false;
    private readonly listeners = new Map<string, () => void>();

    constructor(
      public readonly camera: unknown,
      public readonly domElement: unknown,
    ) {
      constructed.push(this);
    }

    addEventListener(type: string, listener: () => void): void {
      this.listeners.set(type, listener);
    }

    removeEventListener(type: string): void {
      this.listeners.delete(type);
    }

    dispose(): void {
      this.disposed = true;
    }

    emitChange(): void {
      this.listeners.get("change")?.();
    }
  }

  return { constructed, FakeOrbitControls };
});

const store = vi.hoisted(() => ({ state: null as unknown as FakeStoreState }));

vi.mock("three/addons/controls/OrbitControls.js", () => ({
  OrbitControls: harness.FakeOrbitControls,
}));

vi.mock("@react-three/fiber", () => ({
  useThree: <T,>(selector?: (state: FakeStoreState) => T) =>
    selector ? selector(store.state) : store.state,
}));

function createStoreState(): FakeStoreState {
  const state: FakeStoreState = {
    camera: new PerspectiveCamera(),
    gl: { domElement: document.createElement("canvas") },
    invalidate: vi.fn(),
    performance: {
      current: 1,
      min: 0.75,
      // Mirrors @react-three/fiber: regress replaces the performance object
      // (keeping the same regress function reference) whenever quality drops.
      regress: () => {
        if (store.state.performance.current !== store.state.performance.min) {
          store.state = {
            ...store.state,
            performance: { ...store.state.performance, current: store.state.performance.min },
          };
        }
      },
    },
  };
  return state;
}

describe("ViewerCamera orbit controls lifecycle", () => {
  afterEach(() => {
    harness.constructed.length = 0;
  });

  it("keeps the same controls instance across a regress-driven store update", () => {
    store.state = createStoreState();
    const command = { id: 0, kind: "fit", preset: "isometric" } as const;
    const { rerender } = render(<ViewerCamera model={null} fitVersion="demo" command={command} />);

    expect(harness.constructed).toHaveLength(1);
    const controls = harness.constructed[0]!;

    // First change event of a drag gesture: regress() swaps the performance
    // object in the store, and the component re-renders.
    act(() => controls.emitChange());
    rerender(<ViewerCamera model={null} fitVersion="demo" command={{ ...command }} />);

    expect(harness.constructed).toHaveLength(1);
    expect(controls.disposed).toBe(false);

    // The gesture keeps working: further change events still invalidate.
    act(() => controls.emitChange());
    expect(store.state.invalidate).toHaveBeenCalledTimes(2);
  });
});
