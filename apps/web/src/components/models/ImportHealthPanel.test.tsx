// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModelDetail } from "../../api/models";
import { ToastProvider } from "../ui/ToastProvider";
import { ImportHealthPanel } from "./ImportHealthPanel";

const { reprocessModel, upsertModelResolution, deleteModelResolution, searchParts, getColors } =
  vi.hoisted(() => ({
    reprocessModel: vi.fn(),
    upsertModelResolution: vi.fn(),
    deleteModelResolution: vi.fn(),
    searchParts: vi.fn(),
    getColors: vi.fn(),
  }));

vi.mock("../../api/models", async (loadOriginal) => ({
  ...(await loadOriginal<typeof import("../../api/models")>()),
  reprocessModel,
  upsertModelResolution,
  deleteModelResolution,
}));

vi.mock("../../api/catalog", async (loadOriginal) => ({
  ...(await loadOriginal<typeof import("../../api/catalog")>()),
  searchParts,
  getColors,
}));

const model = {
  modelId: "model-1",
  name: "Excavator",
  issues: [
    {
      severity: "info",
      code: "custom_part_auto_mapped",
      message: "Automatically mapped to official part '42545p01'",
      referencedFilename: "42096 - 42545p01.dat",
      occurrenceCount: 2,
    },
    {
      severity: "warning",
      code: "generated_section_without_parts",
      message: "LDCad-generated section contributes no physical parts",
      referencedFilename: "technicFlexAxle-1.ldr",
      occurrenceCount: 1,
    },
  ],
  resolutions: [],
} as unknown as ModelDetail;

const ignoredModel = {
  ...model,
  issues: [
    {
      severity: "info",
      code: "reference_ignored",
      message: "Excluded from the physical BOM by a manual resolution",
      referencedFilename: "technicflexaxle-1.ldr",
      occurrenceCount: 1,
    },
  ],
  resolutions: [
    {
      sourceReference: "technicflexaxle-1.ldr",
      action: "ignore",
      partId: null,
      colorCode: null,
    },
  ],
} as unknown as ModelDetail;

function renderPanel(detail: ModelDetail) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ToastProvider>
        <ImportHealthPanel model={detail} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("import health panel", () => {
  beforeEach(() => {
    reprocessModel.mockResolvedValue(model);
    upsertModelResolution.mockResolvedValue(ignoredModel);
    deleteModelResolution.mockResolvedValue(model);
    searchParts.mockResolvedValue({
      items: [
        {
          partId: "32201",
          name: "Technic Axle Flexible 11",
          category: "Technic",
          author: null,
          renderAssetUrl: "/api/ldraw/parts/32201.dat",
        },
      ],
      page: 1,
      pageSize: 6,
      totalItems: 1,
      totalPages: 1,
    });
    getColors.mockResolvedValue([
      {
        code: 71,
        name: "Light Bluish Grey",
        valueHex: "#a0a5a9",
        edgeHex: null,
        alpha: 255,
        luminance: null,
        finish: null,
      },
      {
        code: 16,
        name: "Main Colour",
        valueHex: "#ffff80",
        edgeHex: null,
        alpha: 255,
        luminance: null,
        finish: null,
      },
    ]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders nothing when the import is clean", () => {
    const { container } = renderPanel({ ...model, issues: [], resolutions: [] });
    expect(container.querySelector(".import-health")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Import health" })).toBeNull();
  });

  it("lists warnings before notices with occurrence counts and scoped actions", () => {
    renderPanel(model);
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]?.textContent).toContain("Generated section without parts");
    expect(rows[1]?.textContent).toContain("Auto-mapped custom part");
    expect(rows[1]?.textContent).toContain("×2");
    // Only the resolvable warning offers actions; the informational notice
    // and the panel heading contribute no Ignore/Map buttons.
    expect(screen.getAllByRole("button", { name: "Ignore" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Map to part…" })).toHaveLength(1);
  });

  it("ignores a reference through a manual resolution", async () => {
    renderPanel(model);
    fireEvent.click(screen.getByRole("button", { name: "Ignore" }));
    await waitFor(() =>
      expect(upsertModelResolution).toHaveBeenCalledWith("model-1", {
        sourceReference: "technicFlexAxle-1.ldr",
        action: "ignore",
      }),
    );
    expect(
      await screen.findByText("Ignored technicFlexAxle-1.ldr and reprocessed the model."),
    ).toBeTruthy();
  });

  it("surfaces resolution failures as error toasts", async () => {
    upsertModelResolution.mockRejectedValue(new Error("Model source not found"));
    renderPanel(model);
    fireEvent.click(screen.getByRole("button", { name: "Ignore" }));
    expect(await screen.findByText("Model source not found")).toBeTruthy();
  });

  it("maps a reference to a searched part with a colour override", async () => {
    renderPanel(model);
    fireEvent.click(screen.getByRole("button", { name: "Map to part…" }));

    // The dialog seeds the search with the reference stem.
    const search = screen.getByRole("searchbox");
    expect((search as HTMLInputElement).value).toBe("technicFlexAxle-1");

    fireEvent.click(await screen.findByRole("button", { name: /32201/ }));
    // Colour 16 is not a physical colour and never appears as an override.
    expect(screen.queryByRole("option", { name: /\(16\)/ })).toBeNull();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "71" } });
    fireEvent.click(screen.getByRole("button", { name: "Map reference" }));

    await waitFor(() =>
      expect(upsertModelResolution).toHaveBeenCalledWith("model-1", {
        sourceReference: "technicFlexAxle-1.ldr",
        action: "map",
        partId: "32201",
        colorCode: 71,
      }),
    );
    expect(
      await screen.findByText("Mapped technicFlexAxle-1.ldr to 32201 and reprocessed the model."),
    ).toBeTruthy();
  });

  it("lists manual resolutions and removes them", async () => {
    renderPanel(ignoredModel);
    expect(screen.getByText("Manual resolutions")).toBeTruthy();
    expect(screen.getByText("Excluded from the BOM")).toBeTruthy();
    // The remaining issue is informational, so no remediation actions show.
    expect(screen.queryByRole("button", { name: "Ignore" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(deleteModelResolution).toHaveBeenCalledWith("model-1", "technicflexaxle-1.ldr"),
    );
    expect(
      await screen.findByText(
        "Removed the resolution for technicflexaxle-1.ldr and reprocessed the model.",
      ),
    ).toBeTruthy();
  });

  it("reprocesses on demand", async () => {
    renderPanel(model);
    fireEvent.click(screen.getByRole("button", { name: "Reprocess" }));
    await waitFor(() => expect(reprocessModel).toHaveBeenCalledWith("model-1"));
    expect(await screen.findByText("Reprocessed Excavator.")).toBeTruthy();
  });
});
