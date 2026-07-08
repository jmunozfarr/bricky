// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BuildManifest, ModelDetail } from "../api/models";
import VisualBuilderPage from "./VisualBuilderPage";

const { getModel, getInstructionPlayback, getBuildManifest } = vi.hoisted(() => ({
  getModel: vi.fn(),
  getInstructionPlayback: vi.fn(),
  getBuildManifest: vi.fn(),
}));

vi.mock("../api/models", async (loadOriginal) => ({
  ...(await loadOriginal<typeof import("../api/models")>()),
  getModel,
  getInstructionPlayback,
  getBuildManifest,
}));

vi.mock("@react-three/fiber", () => ({
  Canvas: () => <div data-testid="canvas" />,
}));
vi.mock("../components/ldraw/LDrawModel", () => ({
  useLDrawModel: () => ({ kind: "loading" }),
  HierarchicalLDrawModel: () => null,
}));
vi.mock("../components/ldraw/ViewerCamera", () => ({ ViewerCamera: () => null }));
vi.mock("../components/ldraw/WebGlLifecycle", () => ({ WebGlLifecycle: () => null }));

const model = {
  modelId: "model-1",
  name: "Test car",
  sourceUrl: "/source",
  totalPartQuantity: 2,
  bom: [
    {
      partId: "3001",
      partName: "Brick 2 x 4",
      category: "Brick",
      colorCode: 4,
      colorName: "Red",
      colorHex: "#c91a09",
      quantity: 2,
      catalogAvailable: true,
      renderAssetUrl: null,
    },
  ],
} as unknown as ModelDetail;

const manifest: BuildManifest = {
  modelId: "model-1",
  modelName: "Test car",
  occurrenceId: "occ-000001",
  parentOccurrenceId: null,
  sourceSubmodelName: "car.ldr",
  attachmentStep: null,
  breadcrumbs: [{ occurrenceId: "occ-000001", sourceSubmodelName: "car.ldr" }],
  repeatedDefinitionCount: 1,
  repeatedDefinitionIndex: 1,
  scene: {
    url: "/scene",
    cacheKey: "scene-key",
    renderStrategy: "subtree",
    delivery: "packed",
    complexity: {
      expandedInstructionNodeCount: 2,
      expandedOccurrenceCount: 1,
      directGeometryCommandCount: 0,
      estimatedDerivedSourceBytes: 100,
    },
  },
  steps: [
    {
      step: 1,
      directGeometryCommandCount: 0,
      attachments: [],
      parts: [
        {
          sourcePartId: "3001",
          partId: "3001",
          aliasApplied: false,
          instructionNodeIds: ["node-1"],
          partName: "Brick 2 x 4",
          colorCode: 4,
          colorName: "Red",
          colorHex: "#c91a09",
          quantityThisStep: 1,
          ownedQuantity: 0,
          modelRequiredQuantity: 1,
          modelMissingQuantity: 1,
          catalogAvailable: true,
        },
      ],
    },
    { step: 2, directGeometryCommandCount: 0, attachments: [], parts: [] },
  ],
};

describe("visual builder workspace", () => {
  beforeEach(() => {
    getModel.mockResolvedValue(model);
    getInstructionPlayback.mockResolvedValue({
      available: true,
      rootOccurrenceId: "occ-000001",
      fallbackReason: null,
    });
    getBuildManifest.mockResolvedValue(manifest);
  });

  afterEach(() => {
    cleanup();
    // Builder progress persists to localStorage by design; without a reset,
    // one test's saved step leaks into the next test's initial render.
    window.localStorage.clear();
  });

  it("presents exact current-step parts and switches modes without refetching", async () => {
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryRouter initialEntries={["/models/model-1/build"]}>
          <Routes>
            <Route path="/models/:modelId/build" element={<VisualBuilderPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // The workspace opens on the assembled overview: no steps anywhere.
    expect(await screen.findByText(/assembled model is shown in full colour/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Next" })).toBeNull();

    // The full parts list renders its rows only once expanded.
    const summary = screen.getByText(/All parts · 2 pieces · 1 kinds/);
    expect(screen.queryByText(/2× Brick 2 x 4/)).toBeNull();
    // jsdom does not activate <details> from summary clicks; drive the
    // toggle event the way the browser would after opening.
    const details = summary.closest("details");
    if (details === null) throw new Error("missing details element");
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(screen.getByText(/2× Brick 2 x 4/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    expect(await screen.findByText("1× Brick 2 x 4", undefined, { timeout: 4_000 })).toBeTruthy();
    expect(screen.getByText("Own 0; model needs 1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "As built" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("heading", { name: "Step 2" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Inspect" }));
    expect(screen.getByText(/assembled model is shown in full colour/i)).toBeTruthy();
    await waitFor(() => expect(getBuildManifest).toHaveBeenCalledTimes(1));
  });

  it("explains child-omitting local rendering in build mode", async () => {
    getBuildManifest.mockResolvedValue({
      ...manifest,
      scene: { ...manifest.scene, renderStrategy: "local" },
    });
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryRouter initialEntries={["/models/model-1/build"]}>
          <Routes>
            <Route path="/models/:modelId/build" element={<VisualBuilderPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Build" }));
    await screen.findByText("1× Brick 2 x 4", undefined, { timeout: 4_000 });
    expect(screen.getByText(/subassemblies are built as separate tasks/i)).toBeTruthy();
  });

  it("jumps directly to a typed step number and clamps out-of-range input", async () => {
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryRouter initialEntries={["/models/model-1/build"]}>
          <Routes>
            <Route path="/models/:modelId/build" element={<VisualBuilderPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Build" }));
    await screen.findByText("1× Brick 2 x 4", undefined, { timeout: 4_000 });

    const stepInput = screen.getByRole("spinbutton");
    fireEvent.change(stepInput, { target: { value: "2" } });
    expect(screen.getByRole("heading", { name: "Step 2" })).toBeTruthy();

    const slider = screen.getByRole("slider", { name: "Scrub through building steps" });
    fireEvent.change(slider, { target: { value: "1" } });
    expect(screen.getByRole("heading", { name: "Step 1" })).toBeTruthy();

    // Out-of-range values are clamped to the last step when committed.
    fireEvent.change(stepInput, { target: { value: "9" } });
    fireEvent.keyDown(stepInput, { key: "Enter" });
    expect(screen.getByRole("heading", { name: "Step 2" })).toBeTruthy();

    // Clearing the field never produces an invalid step.
    fireEvent.change(stepInput, { target: { value: "" } });
    fireEvent.blur(stepInput);
    expect(screen.getByRole("heading", { name: "Step 2" })).toBeTruthy();
  });
});
