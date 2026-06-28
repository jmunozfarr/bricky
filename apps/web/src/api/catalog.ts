import { fetchJson } from "./client";

export interface CatalogStatus {
  libraryInstalled: boolean;
  indexed: boolean;
  stale: boolean;
  partCount: number;
  colorCount: number;
  indexedAt: string | null;
}

export interface PartCard {
  partId: string;
  name: string;
  category: string;
  author: string | null;
  renderAssetUrl: string;
}

export interface PartDetail extends PartCard {
  orgClassification: string | null;
  license: string | null;
  keywords: string[];
  isShortcut: boolean;
}

export interface PartsPage {
  items: PartCard[];
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}

export interface Category {
  name: string;
  count: number;
}

export interface LDrawColor {
  code: number;
  name: string;
  valueHex: string;
  edgeHex: string | null;
  alpha: number;
  luminance: number | null;
  finish: string | null;
}

export interface PartsQuery {
  query: string;
  category: string;
  page: number;
  pageSize?: number;
}

export function serializePartsQuery(input: PartsQuery): string {
  const params = new URLSearchParams();
  if (input.query.trim()) {
    params.set("query", input.query.trim());
  }
  if (input.category) {
    params.set("category", input.category);
  }
  params.set("page", String(Math.max(1, Math.trunc(input.page))));
  if (input.pageSize !== undefined) {
    params.set("pageSize", String(input.pageSize));
  }
  return params.toString();
}

export function previousPage(page: number): number {
  return Math.max(1, page - 1);
}

export function nextPage(page: number, totalPages: number): number {
  return Math.min(Math.max(1, totalPages), page + 1);
}

export function getCatalogStatus(signal?: AbortSignal): Promise<CatalogStatus> {
  return fetchJson<CatalogStatus>("/api/catalog/status", signal);
}

export function searchParts(input: PartsQuery, signal?: AbortSignal): Promise<PartsPage> {
  return fetchJson<PartsPage>(`/api/parts?${serializePartsQuery(input)}`, signal);
}

export function getCategories(signal?: AbortSignal): Promise<Category[]> {
  return fetchJson<Category[]>("/api/parts/categories", signal);
}

export function getPart(partId: string, signal?: AbortSignal): Promise<PartDetail> {
  return fetchJson<PartDetail>(`/api/parts/${encodeURIComponent(partId)}`, signal);
}

export function getColors(signal?: AbortSignal): Promise<LDrawColor[]> {
  return fetchJson<LDrawColor[]>("/api/colors", signal);
}
