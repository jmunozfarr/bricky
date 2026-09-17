// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CatalogStatus } from "../api/catalog";
import type { CoverageSummary, ModelSummary, ModelsPage as ModelsPageData } from "../api/models";
import { ToastProvider } from "../components/ui/ToastProvider";
import ModelsPage from "./ModelsPage";

const { listModels, getCatalogStatus } = vi.hoisted(() => ({
  listModels: vi.fn(),
  getCatalogStatus: vi.fn(),
}));

vi.mock("../api/models", async (loadOriginal) => ({
  ...(await loadOriginal<typeof import("../api/models")>()),
  listModels,
}));

vi.mock("../api/catalog", async (loadOriginal) => ({
  ...(await loadOriginal<typeof import("../api/catalog")>()),
  getCatalogStatus,
}));

const indexedCatalog: CatalogStatus = {
  libraryInstalled: true,
  indexed: true,
  stale: false,
  partCount: 5,
  colorCount: 7,
  indexedAt: "2026-07-16T00:00:00Z",
};

const knownRequirements: CoverageSummary = {
  totalRequiredQuantity: 5,
  totalAvailableQuantity: 2,
  totalMissingQuantity: 3,
  uniqueItemCount: 2,
  completeItemCount: 0,
  partialItemCount: 1,
  missingItemCount: 1,
  pieceCoveragePercentage: 40,
  fullyBuildable: false,
  requirementsComplete: true,
};

function model(overrides: Partial<ModelSummary>): ModelSummary {
  return {
    modelId: "model-1",
    name: "Core loop car",
    originalFilename: "core-loop.mpd",
    sourceFormat: "mpd",
    importStatus: "ready",
    declaredStepCount: 2,
    totalPartQuantity: 5,
    uniquePartColorCount: 2,
    unresolvedReferenceCount: 0,
    createdAt: "2026-07-16T00:00:00Z",
    coverage: knownRequirements,
    ...overrides,
  };
}

function page(items: ModelSummary[]): ModelsPageData {
  return { items, page: 1, pageSize: 24, totalItems: items.length, totalPages: 1 };
}

function renderPage() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ToastProvider>
        <MemoryRouter initialEntries={["/models"]}>
          <ModelsPage />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("models page readiness verdict", () => {
  beforeEach(() => {
    getCatalogStatus.mockResolvedValue(indexedCatalog);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("reports full buildability when the requirements are known and met", async () => {
    listModels.mockResolvedValue(
      page([
        model({
          coverage: {
            ...knownRequirements,
            totalAvailableQuantity: 5,
            totalMissingQuantity: 0,
            pieceCoveragePercentage: 100,
            fullyBuildable: true,
          },
        }),
      ]),
    );
    renderPage();

    expect(await screen.findByText("100% covered")).toBeTruthy();
    expect(screen.getByText("Fully buildable")).toBeTruthy();
  });

  it("reports the missing count when the requirements are known and short", async () => {
    listModels.mockResolvedValue(page([model({})]));
    renderPage();

    expect(await screen.findByText("40% covered")).toBeTruthy();
    expect(screen.getByText("3 pieces missing")).toBeTruthy();
    expect(screen.queryByText("Fully buildable")).toBeNull();
  });

  it("withholds both the verdict and the percentage when nothing resolved", async () => {
    // The unindexed-catalog case: an empty BOM alongside unresolved references,
    // where 100% of nothing was previously published as "Fully buildable".
    listModels.mockResolvedValue(
      page([
        model({
          totalPartQuantity: 0,
          uniquePartColorCount: 0,
          unresolvedReferenceCount: 2,
          importStatus: "ready_with_warnings",
          coverage: {
            totalRequiredQuantity: 0,
            totalAvailableQuantity: 0,
            totalMissingQuantity: 0,
            uniqueItemCount: 0,
            completeItemCount: 0,
            partialItemCount: 0,
            missingItemCount: 0,
            pieceCoveragePercentage: 100,
            fullyBuildable: false,
            requirementsComplete: false,
          },
        }),
      ]),
    );
    renderPage();

    expect(await screen.findByText("Coverage unavailable")).toBeTruthy();
    expect(screen.getByText("Requirements unknown")).toBeTruthy();
    expect(
      screen.getByText("No part references resolved, so this model's required pieces are unknown."),
    ).toBeTruthy();
    expect(screen.queryByText("Fully buildable")).toBeNull();
    expect(screen.queryByText(/100% covered/)).toBeNull();
    // "0 pieces missing" over an unknown requirement set is the same falsehood.
    expect(screen.queryByText(/pieces missing/)).toBeNull();
  });

  it("qualifies the percentage when only part of the model resolved", async () => {
    listModels.mockResolvedValue(
      page([
        model({
          unresolvedReferenceCount: 1,
          coverage: { ...knownRequirements, requirementsComplete: false },
        }),
      ]),
    );
    renderPage();

    expect(await screen.findByText("40% of resolved parts covered")).toBeTruthy();
    expect(screen.getByText("Requirements unknown")).toBeTruthy();
    expect(screen.queryByText("40% covered")).toBeNull();
  });
});

describe("models page catalog availability", () => {
  beforeEach(() => {
    listModels.mockResolvedValue(page([model({})]));
    // `clearAllMocks` keeps implementations, so each test states its own.
    getCatalogStatus.mockResolvedValue(indexedCatalog);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("names the rebuild command when the catalog is not indexed", async () => {
    getCatalogStatus.mockResolvedValue({ ...indexedCatalog, indexed: false, partCount: 0 });
    renderPage();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The parts catalog is not indexed.");
    expect(alert.textContent).toContain(
      "docker compose exec api python -m app.cli.ldraw_catalog rebuild",
    );
  });

  it("names the install command when the official library is absent", async () => {
    getCatalogStatus.mockResolvedValue({
      ...indexedCatalog,
      libraryInstalled: false,
      indexed: false,
      partCount: 0,
    });
    renderPage();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The official LDraw library is not installed.");
    expect(alert.textContent).toContain(
      "docker compose run --rm api python -m app.cli.ldraw_library install",
    );
  });

  it("stays quiet once the catalog is indexed", async () => {
    renderPage();

    expect(await screen.findByText("40% covered")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
