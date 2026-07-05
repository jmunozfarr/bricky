// @vitest-environment jsdom

import { cleanup, render } from "@testing-library/react";
import { BufferGeometry, Group, LineBasicMaterial, LineSegments, Mesh } from "three";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdaptiveViewerLines, setLineSegmentsVisible } from "./AdaptiveViewerLines";

interface FakeStoreState {
  scene: Group;
  invalidate: () => void;
  performance: { current: number };
}

const store = vi.hoisted(() => ({ state: null as unknown as FakeStoreState }));

vi.mock("@react-three/fiber", () => ({
  useThree: <T,>(selector?: (state: FakeStoreState) => T) =>
    selector ? selector(store.state) : store.state,
}));

function createScene(): { scene: Group; lines: LineSegments[]; mesh: Mesh } {
  const scene = new Group();
  const part = new Group();
  const mesh = new Mesh(new BufferGeometry());
  const lines = [
    new LineSegments(new BufferGeometry(), new LineBasicMaterial()),
    new LineSegments(new BufferGeometry(), new LineBasicMaterial()),
  ];
  part.add(mesh, lines[0]!);
  scene.add(part, lines[1]!);
  return { scene, lines, mesh };
}

describe("AdaptiveViewerLines", () => {
  afterEach(cleanup);

  it("hides line segments while regressed and restores them at full quality", () => {
    const { scene, lines, mesh } = createScene();
    store.state = {
      scene,
      invalidate: vi.fn(),
      performance: { current: 1 },
    };

    const { rerender } = render(<AdaptiveViewerLines />);
    expect(lines.every((line) => line.visible)).toBe(true);

    store.state = { ...store.state, performance: { current: 0.5 } };
    rerender(<AdaptiveViewerLines />);
    expect(lines.every((line) => !line.visible)).toBe(true);
    expect(mesh.visible).toBe(true);
    expect(store.state.invalidate).toHaveBeenCalled();

    store.state = { ...store.state, performance: { current: 1 } };
    rerender(<AdaptiveViewerLines />);
    expect(lines.every((line) => line.visible)).toBe(true);
  });

  it("restores hidden lines when unmounted mid-interaction", () => {
    const { scene, lines } = createScene();
    store.state = {
      scene,
      invalidate: vi.fn(),
      performance: { current: 0.5 },
    };

    const { unmount } = render(<AdaptiveViewerLines />);
    expect(lines.every((line) => !line.visible)).toBe(true);

    unmount();
    expect(lines.every((line) => line.visible)).toBe(true);
  });

  it("reports how many segments it changed and leaves other flags alone", () => {
    const { scene, lines } = createScene();
    lines[0]!.visible = false;

    expect(setLineSegmentsVisible(scene, false)).toBe(1);
    expect(setLineSegmentsVisible(scene, false)).toBe(0);
    expect(setLineSegmentsVisible(scene, true)).toBe(2);
  });
});
