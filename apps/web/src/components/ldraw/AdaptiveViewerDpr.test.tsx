// @vitest-environment jsdom

import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdaptiveViewerDpr } from "./AdaptiveViewerDpr";

interface FakeStoreState {
  performance: { current: number };
  viewport: { initialDpr: number };
  setDpr: (dpr: number) => void;
  invalidate: () => void;
}

const store = vi.hoisted(() => ({ state: null as unknown as FakeStoreState }));

vi.mock("@react-three/fiber", () => ({
  useThree: <T,>(selector: (state: FakeStoreState) => T) => selector(store.state),
}));

describe("AdaptiveViewerDpr", () => {
  it("scales the canvas DPR with the store's performance factor", () => {
    store.state = {
      performance: { current: 1 },
      viewport: { initialDpr: 2 },
      setDpr: vi.fn(),
      invalidate: vi.fn(),
    };
    const { rerender } = render(<AdaptiveViewerDpr />);
    expect(store.state.setDpr).toHaveBeenCalledWith(2);

    // Regression kicks in: quality factor drops, DPR follows.
    store.state = { ...store.state, performance: { current: 0.5 } };
    rerender(<AdaptiveViewerDpr />);
    expect(store.state.setDpr).toHaveBeenCalledWith(1);
    expect(store.state.invalidate).toHaveBeenCalledTimes(2);
  });
});
