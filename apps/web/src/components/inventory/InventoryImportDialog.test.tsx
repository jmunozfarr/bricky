// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import type { InventoryImportPreview, InventoryImportResult } from "../../api/inventory";
import { ToastProvider } from "../ui/ToastProvider";
import { InventoryImportDialog } from "./InventoryImportDialog";

const { previewInventoryImport, applyInventoryImport } = vi.hoisted(() => ({
  previewInventoryImport: vi.fn(),
  applyInventoryImport: vi.fn(),
}));

vi.mock("../../api/inventory", async (loadOriginal) => ({
  ...(await loadOriginal<typeof import("../../api/inventory")>()),
  previewInventoryImport,
  applyInventoryImport,
}));

const preview: InventoryImportPreview = {
  fileName: "inventory.csv",
  format: "native",
  strategy: "add",
  totalDataRows: 5,
  plannedRowCount: 3,
  duplicateRowCount: 1,
  aliasCanonicalizedCount: 1,
  ignoredColumns: ["Notes"],
  invalidRowCount: 1,
  spareRowCount: 0,
  mappingAvailable: true,
  known: {
    rowCount: 2,
    createCount: 1,
    updateCount: 1,
    unchangedCount: 0,
    quantityDelta: 8,
    missingPartCount: 0,
    missingColorCount: 0,
    missingMappingCount: 0,
  },
  unknown: {
    rowCount: 1,
    createCount: 1,
    updateCount: 0,
    unchangedCount: 0,
    quantityDelta: 2,
    missingPartCount: 1,
    missingColorCount: 0,
    missingMappingCount: 0,
  },
  rows: [
    {
      partId: "mystery",
      sourcePartId: "MYSTERY",
      canonicalizedFrom: null,
      colorCode: 4,
      quantity: 2,
      currentQuantity: 0,
      resultingQuantity: 2,
      change: "create",
      unknownReason: "part",
      partName: null,
      colorName: "Red",
      colorHex: "#C91A09",
      alpha: 255,
      renderAssetUrl: null,
    },
    {
      partId: "3001",
      sourcePartId: "3001",
      canonicalizedFrom: null,
      colorCode: 1,
      quantity: 3,
      currentQuantity: 0,
      resultingQuantity: 3,
      change: "create",
      unknownReason: null,
      partName: "Brick 2 x 4",
      colorName: "Blue",
      colorHex: "#0055BF",
      alpha: 255,
      renderAssetUrl: "/api/ldraw/parts/3001.dat",
    },
    {
      partId: "canonical",
      sourcePartId: "ALIAS",
      canonicalizedFrom: "ALIAS",
      colorCode: 4,
      quantity: 5,
      currentQuantity: 2,
      resultingQuantity: 7,
      change: "update",
      unknownReason: null,
      partName: "Part canonical",
      colorName: "Red",
      colorHex: "#C91A09",
      alpha: 255,
      renderAssetUrl: null,
    },
  ],
  rowsTruncated: false,
  issues: [
    {
      lineNumber: 5,
      code: "bad_quantity",
      message: "Quantity 'abc' must be an integer between 1 and 999999",
    },
  ],
  issuesTruncated: false,
};

const applied: InventoryImportResult = {
  format: "native",
  strategy: "add",
  includeUnknown: true,
  appliedRowCount: 3,
  createdCount: 2,
  updatedCount: 1,
  unchangedCount: 0,
  skippedUnknownRowCount: 0,
  invalidRowCount: 1,
  quantityDelta: 10,
};

const csvFile = new File(["part_id,color_code,quantity\n3001,4,1\n"], "inventory.csv", {
  type: "text/csv",
});

function renderDialog() {
  const onClose = vi.fn();
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ToastProvider>
        <InventoryImportDialog onClose={onClose} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return onClose;
}

async function selectCsv(file: File = csvFile) {
  fireEvent.change(screen.getByLabelText("Import file"), { target: { files: [file] } });
  await screen.findByRole("group", { name: "Merge strategy" });
}

describe("inventory import dialog", () => {
  beforeEach(() => {
    previewInventoryImport.mockResolvedValue(preview);
    applyInventoryImport.mockResolvedValue(applied);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("previews a selected file and renders buckets, badges, and quantities", async () => {
    renderDialog();
    await selectCsv();

    expect(previewInventoryImport).toHaveBeenCalledWith(csvFile, "add");
    expect(screen.getByText(/catalog rows/).textContent).toContain("1 new, 1 updated");
    // Both the bucket fact line and the include-unknown label mention them.
    expect(screen.getAllByText(/rows not in the catalog$/)).toHaveLength(2);
    expect(screen.getByText("1 duplicate rows merged")).toBeTruthy();
    expect(screen.getByText("1 moved part IDs renamed")).toBeTruthy();
    expect(screen.getByText("Ignored columns: Notes")).toBeTruthy();
    expect(screen.getByText("Not in catalog")).toBeTruthy();
    expect(screen.getByText("Renamed from ALIAS")).toBeTruthy();
    expect(screen.getByText("2 → 7")).toBeTruthy();
    expect(screen.getByText(/Line 5:/).textContent).toContain("Quantity 'abc'");
    expect(screen.getByRole("checkbox")).toHaveProperty("checked", true);
  });

  it("rejects a non-CSV file locally without calling the API", () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText("Import file"), {
      target: { files: [new File(["x"], "inventory.txt", { type: "text/plain" })] },
    });

    expect(screen.getByRole("alert").textContent).toContain(".csv");
    expect(previewInventoryImport).not.toHaveBeenCalled();
  });

  it("re-runs the preview with the retained file when the strategy changes", async () => {
    renderDialog();
    await selectCsv();

    fireEvent.click(screen.getByRole("button", { name: "Replace quantities" }));

    await waitFor(() =>
      expect(previewInventoryImport).toHaveBeenLastCalledWith(csvFile, "replace"),
    );
    expect(previewInventoryImport).toHaveBeenCalledTimes(2);
  });

  it("applies with the include-unknown choice, shows a toast, and closes", async () => {
    const onClose = renderDialog();
    await selectCsv();

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Import" }));

    await waitFor(() =>
      expect(applyInventoryImport).toHaveBeenCalledWith(csvFile, "add", false, "native"),
    );
    expect(await screen.findByText(/Imported 3 rows \(2 new, 1 updated\)/)).toBeTruthy();
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps the dialog open and surfaces apply failures as alerts", async () => {
    applyInventoryImport.mockRejectedValue(
      new ApiError(422, "The CSV has no header row", "The CSV has no header row"),
    );
    const onClose = renderDialog();
    await selectCsv();

    fireEvent.click(screen.getByRole("button", { name: "Import" }));

    expect((await screen.findByRole("alert")).textContent).toContain("no header row");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("surfaces preview failures and disables the import action", async () => {
    previewInventoryImport.mockRejectedValue(new ApiError(413, "too big", "too big"));
    renderDialog();
    fireEvent.change(screen.getByLabelText("Import file"), { target: { files: [csvFile] } });

    expect((await screen.findByRole("alert")).textContent).toContain("upload-size");
    expect(screen.getByRole("button", { name: "Import" })).toHaveProperty("disabled", true);
  });

  it("accepts an .xml file locally and shows the detected BrickLink format", async () => {
    previewInventoryImport.mockResolvedValue({
      ...preview,
      format: "bricklink",
    } satisfies InventoryImportPreview);
    renderDialog();
    const xmlFile = new File(["<INVENTORY></INVENTORY>"], "wanted.xml", {
      type: "application/xml",
    });

    await selectCsv(xmlFile);

    expect(previewInventoryImport).toHaveBeenCalledWith(xmlFile, "add");
    expect(screen.getByText("Detected format: BrickLink XML")).toBeTruthy();
  });

  it("shows a spare-row count and an unmapped-row badge for external formats", async () => {
    previewInventoryImport.mockResolvedValue({
      ...preview,
      format: "rebrickable",
      spareRowCount: 3,
      rows: [
        {
          partId: "99999",
          sourcePartId: "99999",
          canonicalizedFrom: null,
          colorCode: 4,
          quantity: 1,
          currentQuantity: 0,
          resultingQuantity: 1,
          change: "create",
          unknownReason: "unmapped",
          partName: null,
          colorName: "Red",
          colorHex: "#C91A09",
          alpha: 255,
          renderAssetUrl: null,
        },
      ],
    } satisfies InventoryImportPreview);
    renderDialog();

    await selectCsv();

    expect(screen.getByText("Detected format: Rebrickable CSV")).toBeTruthy();
    expect(screen.getByText("3 spare rows included")).toBeTruthy();
    expect(screen.getByText("No LDraw mapping")).toBeTruthy();
  });

  it("shows a banner when the mapping table isn't populated", async () => {
    previewInventoryImport.mockResolvedValue({
      ...preview,
      format: "rebrickable",
      mappingAvailable: false,
    } satisfies InventoryImportPreview);
    renderDialog();

    await selectCsv();

    expect(screen.getByRole("alert").textContent).toContain("rebrickable_mapping populate");
  });
});
