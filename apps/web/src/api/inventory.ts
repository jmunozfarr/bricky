import { fetchJson, fetchNoContent } from "./client";

export interface InventorySummary {
  totalQuantity: number;
  uniqueItems: number;
  uniqueParts: number;
}

export interface InventoryItem {
  partId: string;
  partName: string;
  category: string;
  colorCode: number;
  colorName: string;
  colorHex: string;
  alpha: number;
  quantity: number;
  renderAssetUrl: string | null;
  updatedAt: string;
  catalogAvailable: boolean;
}

export interface InventoryPage {
  items: InventoryItem[];
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}

export interface InventoryQuery {
  query: string;
  category: string;
  colorCode: number | null;
  page: number;
  pageSize?: number;
}

export function serializeInventoryQuery(input: InventoryQuery): string {
  const params = new URLSearchParams();
  if (input.query.trim()) params.set("query", input.query.trim());
  if (input.category) params.set("category", input.category);
  if (input.colorCode !== null) params.set("colorCode", String(input.colorCode));
  params.set("page", String(Math.max(1, Math.trunc(input.page))));
  if (input.pageSize !== undefined) params.set("pageSize", String(input.pageSize));
  return params.toString();
}

export function getInventorySummary(signal?: AbortSignal): Promise<InventorySummary> {
  return fetchJson<InventorySummary>("/api/inventory/summary", signal);
}

export function searchInventory(
  input: InventoryQuery,
  signal?: AbortSignal,
): Promise<InventoryPage> {
  return fetchJson<InventoryPage>(`/api/inventory/items?${serializeInventoryQuery(input)}`, signal);
}

export function getInventoryVariants(
  partId: string,
  signal?: AbortSignal,
): Promise<InventoryItem[]> {
  return fetchJson<InventoryItem[]>(`/api/inventory/items/${encodeURIComponent(partId)}`, signal);
}

export function setInventoryQuantity(
  partId: string,
  colorCode: number,
  quantity: number,
): Promise<InventoryItem> {
  return fetchJson<InventoryItem>(
    `/api/inventory/items/${encodeURIComponent(partId)}/${colorCode}`,
    undefined,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quantity }),
    },
  );
}

export function deleteInventoryItem(partId: string, colorCode: number): Promise<void> {
  return fetchNoContent(`/api/inventory/items/${encodeURIComponent(partId)}/${colorCode}`, {
    method: "DELETE",
  });
}

export type InventoryImportStrategy = "add" | "replace";
export type InventoryImportChange = "create" | "update" | "unchanged";
export type InventoryImportUnknownReason = "part" | "color" | "unmapped";
export type InventoryImportFormat = "native" | "rebrickable" | "bricklink" | "set";

export interface InventoryImportBucketSummary {
  rowCount: number;
  createCount: number;
  updateCount: number;
  unchangedCount: number;
  quantityDelta: number;
  missingPartCount: number;
  missingColorCount: number;
  missingMappingCount: number;
}

export interface InventoryImportPreviewRow {
  partId: string;
  sourcePartId: string;
  canonicalizedFrom: string | null;
  colorCode: number;
  quantity: number;
  currentQuantity: number;
  resultingQuantity: number;
  change: InventoryImportChange;
  unknownReason: InventoryImportUnknownReason | null;
  partName: string | null;
  colorName: string | null;
  colorHex: string | null;
  alpha: number | null;
  renderAssetUrl: string | null;
}

export interface InventoryImportRowIssue {
  lineNumber: number;
  code: string;
  message: string;
}

export interface InventoryImportPreview {
  fileName: string;
  format: InventoryImportFormat;
  strategy: InventoryImportStrategy;
  totalDataRows: number;
  plannedRowCount: number;
  duplicateRowCount: number;
  aliasCanonicalizedCount: number;
  ignoredColumns: string[];
  invalidRowCount: number;
  spareRowCount: number;
  mappingAvailable: boolean;
  known: InventoryImportBucketSummary;
  unknown: InventoryImportBucketSummary;
  rows: InventoryImportPreviewRow[];
  rowsTruncated: boolean;
  issues: InventoryImportRowIssue[];
  issuesTruncated: boolean;
  /** Only present for format === "set". */
  setNum: string | null;
  setName: string | null;
  officialPartCount: number | null;
  expandedQuantity: number | null;
}

export interface InventoryImportResult {
  format: InventoryImportFormat;
  strategy: InventoryImportStrategy;
  includeUnknown: boolean;
  appliedRowCount: number;
  createdCount: number;
  updatedCount: number;
  unchangedCount: number;
  skippedUnknownRowCount: number;
  invalidRowCount: number;
  quantityDelta: number;
  setNum: string | null;
  setName: string | null;
}

export function previewInventoryImport(
  file: File,
  strategy: InventoryImportStrategy,
  signal?: AbortSignal,
): Promise<InventoryImportPreview> {
  const body = new FormData();
  body.set("file", file);
  body.set("strategy", strategy);
  return fetchJson<InventoryImportPreview>("/api/inventory/import/preview", signal, {
    method: "POST",
    body,
  });
}

export function applyInventoryImport(
  file: File,
  strategy: InventoryImportStrategy,
  includeUnknown: boolean,
  format?: InventoryImportFormat,
): Promise<InventoryImportResult> {
  const body = new FormData();
  body.set("file", file);
  body.set("strategy", strategy);
  body.set("includeUnknown", includeUnknown ? "true" : "false");
  if (format !== undefined) body.set("format", format);
  return fetchJson<InventoryImportResult>("/api/inventory/import/apply", undefined, {
    method: "POST",
    body,
  });
}

export function previewSetImport(
  setNum: string,
  strategy: InventoryImportStrategy,
  signal?: AbortSignal,
): Promise<InventoryImportPreview> {
  return fetchJson<InventoryImportPreview>("/api/inventory/import/set/preview", signal, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ setNum, strategy }),
  });
}

export function applySetImport(
  setNum: string,
  strategy: InventoryImportStrategy,
  includeUnknown: boolean,
): Promise<InventoryImportResult> {
  return fetchJson<InventoryImportResult>("/api/inventory/import/set/apply", undefined, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ setNum, strategy, includeUnknown }),
  });
}
