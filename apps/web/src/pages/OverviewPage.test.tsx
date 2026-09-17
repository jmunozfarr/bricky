// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import OverviewPage from "./OverviewPage";

const INDEXED_CATALOG = {
  libraryInstalled: true,
  indexed: true,
  stale: false,
  partCount: 5,
  colorCount: 7,
  indexedAt: "2026-07-16T00:00:00Z",
};

/** Every overview query goes through `fetch`, so one router covers them all. */
function stubApi(catalog: Record<string, unknown>) {
  const bodies: Record<string, unknown> = {
    "/api/health": { status: "ok", database: "ok" },
    "/api/catalog/status": catalog,
    "/api/inventory/summary": { totalQuantity: 4, uniqueItems: 2 },
    "/api/models/readiness-summary": {
      totalModels: 1,
      fullyBuildableModels: 0,
      incompleteModels: 1,
      totalMissingQuantity: 0,
    },
    "/api/library/status": { installed: true, fileCounts: null, archiveSha256: null },
  };
  vi.stubGlobal("fetch", (input: string) =>
    Promise.resolve(
      new Response(JSON.stringify(bodies[input] ?? {}), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
}

function renderPage() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/"]}>
        <OverviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("overview readiness tile", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("explains a zero buildable count while the catalog is not indexed", async () => {
    stubApi({ ...INDEXED_CATALOG, indexed: false, partCount: 0 });
    renderPage();

    expect(await screen.findByText("0 of 1 models fully buildable")).toBeTruthy();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The parts catalog is not indexed.");
    expect(alert.textContent).toContain(
      "docker compose exec api python -m app.cli.ldraw_catalog rebuild",
    );
  });

  it("leaves the tile unannotated once the catalog is indexed", async () => {
    stubApi(INDEXED_CATALOG);
    renderPage();

    expect(await screen.findByText("0 of 1 models fully buildable")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
