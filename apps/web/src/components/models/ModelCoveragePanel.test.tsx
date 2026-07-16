// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ModelCoverage } from "../../api/models";
import { ToastProvider } from "../ui/ToastProvider";
import { ModelCoveragePanel } from "./ModelCoveragePanel";

const { getModelCoverage, downloadMissingParts } = vi.hoisted(() => ({
  getModelCoverage: vi.fn(),
  downloadMissingParts: vi.fn(),
}));

vi.mock("../../api/models", async (loadOriginal) => ({
  ...(await loadOriginal<typeof import("../../api/models")>()),
  getModelCoverage,
  downloadMissingParts,
}));

const incompleteCoverage: ModelCoverage = {
  modelId: "model-1",
  summary: {
    pieceCoveragePercentage: 50,
    fullyBuildable: false,
    totalRequiredQuantity: 4,
    totalAvailableQuantity: 2,
    totalMissingQuantity: 2,
    uniqueItemCount: 1,
    completeItemCount: 0,
    partialItemCount: 1,
    missingItemCount: 0,
  },
  items: [
    {
      partId: "3001",
      partName: "Brick 2 x 4",
      category: "Brick",
      colorCode: 4,
      colorName: "Red",
      colorHex: "#C91A09",
      requiredQuantity: 4,
      ownedQuantity: 2,
      availableQuantity: 2,
      missingQuantity: 2,
      coveragePercentage: 50,
      status: "partial",
      catalogAvailable: true,
      renderAssetUrl: null,
    },
  ],
};

const completeCoverage: ModelCoverage = {
  ...incompleteCoverage,
  summary: { ...incompleteCoverage.summary, totalMissingQuantity: 0, fullyBuildable: true },
};

function renderPanel() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ToastProvider>
        <ModelCoveragePanel modelId="model-1" />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("model coverage panel export actions", () => {
  beforeEach(() => {
    getModelCoverage.mockResolvedValue(incompleteCoverage);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("disables both export buttons while coverage is fully buildable", async () => {
    getModelCoverage.mockResolvedValue(completeCoverage);
    renderPanel();

    const csvButton = await screen.findByRole("button", { name: "Export missing parts (CSV)" });
    const xmlButton = screen.getByRole("button", { name: "Export missing parts (BrickLink XML)" });
    expect(csvButton).toHaveProperty("disabled", true);
    expect(xmlButton).toHaveProperty("disabled", true);
  });

  it("downloads the CSV export and shows a success toast", async () => {
    downloadMissingParts.mockResolvedValue({ skippedCount: null, totalCount: null });
    renderPanel();

    const csvButton = await screen.findByRole("button", { name: "Export missing parts (CSV)" });
    fireEvent.click(csvButton);

    await waitFor(() => expect(downloadMissingParts).toHaveBeenCalledWith("model-1", "csv"));
    expect(await screen.findByText("Missing-parts export downloaded.")).toBeTruthy();
  });

  it("shows a skipped-count notice for the BrickLink export when rows were dropped", async () => {
    downloadMissingParts.mockResolvedValue({ skippedCount: 1, totalCount: 3 });
    renderPanel();

    const xmlButton = await screen.findByRole("button", {
      name: "Export missing parts (BrickLink XML)",
    });
    fireEvent.click(xmlButton);

    await waitFor(() =>
      expect(downloadMissingParts).toHaveBeenCalledWith("model-1", "bricklink-xml"),
    );
    expect(await screen.findByText(/1 of 3 missing parts have no BrickLink match/)).toBeTruthy();
  });

  it("surfaces export failures as an error toast without crashing", async () => {
    downloadMissingParts.mockRejectedValue(new Error("network down"));
    renderPanel();

    const csvButton = await screen.findByRole("button", { name: "Export missing parts (CSV)" });
    fireEvent.click(csvButton);

    expect(await screen.findByText("network down")).toBeTruthy();
  });
});
