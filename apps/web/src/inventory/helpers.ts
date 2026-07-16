import { ApiError } from "../api/client";
import type { InventoryImportFormat, InventoryImportResult } from "../api/inventory";

export const MAX_INVENTORY_QUANTITY = 999_999;
export const INVENTORY_CSV_LIMIT_BYTES = 1024 * 1024;
const IMPORT_FILE_EXTENSIONS = new Set(["csv", "xml"]);

export function parseQuantityInput(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const quantity = Number(value);
  return Number.isSafeInteger(quantity) && quantity >= 1 && quantity <= MAX_INVENTORY_QUANTITY
    ? quantity
    : null;
}

export function incrementQuantity(quantity: number): number {
  return Math.min(MAX_INVENTORY_QUANTITY, quantity + 1);
}

export function decrementQuantity(quantity: number): number | null {
  return quantity <= 1 ? null : quantity - 1;
}

export function inventoryEmptyMessage(hasFilters: boolean): string {
  return hasFilters
    ? "No inventory items match these filters."
    : "Your personal inventory is empty.";
}

export function validateInventoryImportFile(
  file: Pick<File, "name" | "size"> | null,
): string | null {
  if (file === null) return "Choose a CSV or XML file.";
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (extension === undefined || !IMPORT_FILE_EXTENSIONS.has(extension)) {
    return "Only .csv or .xml files are supported.";
  }
  if (file.size === 0) return "The selected file is empty.";
  if (file.size > INVENTORY_CSV_LIMIT_BYTES) return "The selected file exceeds 1 MiB.";
  return null;
}

export function importFormatLabel(format: InventoryImportFormat): string {
  switch (format) {
    case "native":
      return "Native CSV";
    case "rebrickable":
      return "Rebrickable CSV";
    case "bricklink":
      return "BrickLink XML";
  }
}

export function importErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 413) return "The CSV exceeds the server upload-size limit.";
    if (error.status === 422) return error.message;
  }
  return error instanceof Error ? error.message : "Inventory import failed.";
}

function countRows(count: number): string {
  return `${count} row${count === 1 ? "" : "s"}`;
}

export function importToastMessage(result: InventoryImportResult): string {
  const buckets = [`${result.createdCount} new`, `${result.updatedCount} updated`];
  if (result.unchangedCount > 0) buckets.push(`${result.unchangedCount} unchanged`);
  const summary = `Imported ${countRows(result.appliedRowCount)} (${buckets.join(", ")}).`;
  const notes: string[] = [];
  if (result.skippedUnknownRowCount > 0) {
    notes.push(`Skipped ${countRows(result.skippedUnknownRowCount)} not in the catalog.`);
  }
  if (result.invalidRowCount > 0) {
    notes.push(`Ignored ${countRows(result.invalidRowCount)} with errors.`);
  }
  return [summary, ...notes].join(" ");
}

export function colorSwatchValue(colorHex: string, alpha: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(colorHex);
  const hex = match?.[1] ?? "808080";
  const red = Number.parseInt(hex.slice(0, 2), 16);
  const green = Number.parseInt(hex.slice(2, 4), 16);
  const blue = Number.parseInt(hex.slice(4, 6), 16);
  const opacity = Math.max(0, Math.min(255, alpha)) / 255;
  return `rgba(${red}, ${green}, ${blue}, ${opacity.toFixed(3)})`;
}
