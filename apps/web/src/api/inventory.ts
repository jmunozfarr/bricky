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
  return fetchJson<InventoryPage>(
    `/api/inventory/items?${serializeInventoryQuery(input)}`,
    signal,
  );
}

export function getInventoryVariants(
  partId: string,
  signal?: AbortSignal,
): Promise<InventoryItem[]> {
  return fetchJson<InventoryItem[]>(
    `/api/inventory/items/${encodeURIComponent(partId)}`,
    signal,
  );
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
  return fetchNoContent(
    `/api/inventory/items/${encodeURIComponent(partId)}/${colorCode}`,
    { method: "DELETE" },
  );
}
