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
    requirementsComplete: true,
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
  summary: {
    ...incompleteCoverage.summary,
    pieceCoveragePercentage: 100,
    totalAvailableQuantity: 4,
    totalMissingQuantity: 0,
    fullyBuildable: true,
  },
};

/** What an unindexed catalog produces: nothing resolved, so nothing is known. */
const unknownCoverage: ModelCoverage = {
  modelId: "model-1",
  summary: {
    pieceCoveragePercentage: 100,
    fullyBuildable: false,
    requirementsComplete: false,
    totalRequiredQuantity: 0,
    totalAvailableQuantity: 0,
    totalMissingQuantity: 0,
    uniqueItemCount: 0,
    completeItemCount: 0,
    partialItemCount: 0,
    missingItemCount: 0,
  },
  items: [],
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

describe("model coverage panel verdict", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("claims buildability only when the requirements are known", async () => {
    getModelCoverage.mockResolvedValue(completeCoverage);
    renderPanel();

    expect(await screen.findByRole("heading", { name: "100% covered" })).toBeTruthy();
    expect(screen.getByText("Fully buildable")).toBeTruthy();
    expect(screen.getByRole("progressbar")).toBeTruthy();
  });

  it("reports the missing count when the requirements are known", async () => {
    getModelCoverage.mockResolvedValue(incompleteCoverage);
    renderPanel();

    expect(await screen.findByRole("heading", { name: "50% covered" })).toBeTruthy();
    expect(screen.getByText("2 pieces missing")).toBeTruthy();
    expect(screen.queryByText("Fully buildable")).toBeNull();
  });

  it("withholds the verdict and the percentage when the requirements are unknown", async () => {
    getModelCoverage.mockResolvedValue(unknownCoverage);
    renderPanel();

    expect(await screen.findByRole("heading", { name: "Coverage unavailable" })).toBeTruthy();
    expect(screen.getByText("Requirements unknown")).toBeTruthy();
    expect(screen.queryByText("Fully buildable")).toBeNull();
    expect(screen.queryByText(/100% covered/)).toBeNull();
    // A bar filled to 100% of an empty requirement set is the same false claim.
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("does not report unknown requirements as a completeness claim on the export buttons", async () => {
    getModelCoverage.mockResolvedValue(unknownCoverage);
    renderPanel();

    const csvButton = await screen.findByRole("button", { name: "Export missing parts (CSV)" });
    const xmlButton = screen.getByRole("button", { name: "Export missing parts (BrickLink XML)" });
    // Nothing is exportable either way, but the reason must not be "complete":
    // both buttons point at the explanation instead of standing bare.
    const note = screen.getByText(/No part references resolved/);
    expect(note.textContent).toContain("There is nothing to export until they resolve.");
    expect(csvButton.getAttribute("aria-describedby")).toBe(note.id);
    expect(xmlButton.getAttribute("aria-describedby")).toBe(note.id);
    expect(screen.queryByText(/You have all the pieces required/)).toBeNull();
  });

  it("keeps the completeness claim out of the missing-only empty state", async () => {
    getModelCoverage.mockResolvedValue(unknownCoverage);
    renderPanel();

    const summary = await screen.findByText(/All parts · 0 pieces · 0 kinds/);
    const details = summary.closest("details");
    if (details === null) throw new Error("missing details element");
    details.open = true;
    fireEvent(details, new Event("toggle"));
    fireEvent.click(screen.getByRole("button", { name: "Missing" }));

    expect(screen.getByText(/Nothing is known to be missing/)).toBeTruthy();
    expect(screen.queryByText(/You have all the pieces required/)).toBeNull();
  });
});

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
