import { fetchJson, fetchNoContent } from "./client";

export type ModelImportStatus = "ready" | "ready_with_warnings" | "failed";
export type CoverageStatus = "complete" | "partial" | "missing";

export interface CoverageSummary {
  totalRequiredQuantity: number;
  totalAvailableQuantity: number;
  totalMissingQuantity: number;
  uniqueItemCount: number;
  completeItemCount: number;
  partialItemCount: number;
  missingItemCount: number;
  pieceCoveragePercentage: number;
  fullyBuildable: boolean;
}

export interface ModelSummary {
  modelId: string;
  name: string;
  originalFilename: string;
  sourceFormat: "ldr" | "mpd";
  importStatus: ModelImportStatus;
  declaredStepCount: number;
  totalPartQuantity: number;
  uniquePartColorCount: number;
  unresolvedReferenceCount: number;
  createdAt: string;
  coverage: CoverageSummary | null;
}

export interface ModelBomItem {
  partId: string;
  partName: string;
  category: string;
  colorCode: number;
  colorName: string;
  colorHex: string | null;
  quantity: number;
  catalogAvailable: boolean;
  renderAssetUrl: string | null;
}

export interface ModelImportIssue {
  severity: string;
  code: string;
  message: string;
  referencedFilename: string | null;
}

export interface ModelDetail extends ModelSummary {
  sourceSha256: string;
  sourceUrl: string;
  updatedAt: string;
  bom: ModelBomItem[];
  issues: ModelImportIssue[];
}

export interface ModelsPage {
  items: ModelSummary[];
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}

export interface ModelCoverageItem {
  partId: string;
  partName: string;
  category: string;
  colorCode: number;
  colorName: string;
  colorHex: string | null;
  requiredQuantity: number;
  ownedQuantity: number;
  availableQuantity: number;
  missingQuantity: number;
  coveragePercentage: number;
  status: CoverageStatus;
  catalogAvailable: boolean;
  renderAssetUrl: string | null;
}

export interface ModelCoverage {
  modelId: string;
  summary: CoverageSummary;
  items: ModelCoverageItem[];
}

export interface ModelsReadinessSummary {
  totalModels: number;
  fullyBuildableModels: number;
  incompleteModels: number;
  totalMissingQuantity: number;
}

export interface CoverageQuery {
  status?: CoverageStatus;
  query?: string;
}

export interface ModelsQuery {
  query: string;
  status: string;
  page: number;
  pageSize?: number;
}

export function serializeModelsQuery(input: ModelsQuery): string {
  const params = new URLSearchParams();
  if (input.query.trim()) params.set("query", input.query.trim());
  if (input.status) params.set("status", input.status);
  params.set("page", String(Math.max(1, Math.trunc(input.page))));
  if (input.pageSize !== undefined) params.set("pageSize", String(input.pageSize));
  return params.toString();
}

export function listModels(input: ModelsQuery, signal?: AbortSignal): Promise<ModelsPage> {
  return fetchJson<ModelsPage>(`/api/models?${serializeModelsQuery(input)}`, signal);
}

export function serializeCoverageQuery(input: CoverageQuery): string {
  const params = new URLSearchParams();
  if (input.status) params.set("status", input.status);
  if (input.query?.trim()) params.set("query", input.query.trim());
  return params.toString();
}

export function getModelCoverage(
  modelId: string,
  input: CoverageQuery = {},
  signal?: AbortSignal,
): Promise<ModelCoverage> {
  const query = serializeCoverageQuery(input);
  const suffix = query ? `?${query}` : "";
  return fetchJson<ModelCoverage>(
    `/api/models/${encodeURIComponent(modelId)}/coverage${suffix}`,
    signal,
  );
}

export function getModelsReadinessSummary(
  signal?: AbortSignal,
): Promise<ModelsReadinessSummary> {
  return fetchJson<ModelsReadinessSummary>("/api/models/readiness-summary", signal);
}

export function getModel(modelId: string, signal?: AbortSignal): Promise<ModelDetail> {
  return fetchJson<ModelDetail>(`/api/models/${encodeURIComponent(modelId)}`, signal);
}

export function uploadModel(file: File, name: string): Promise<ModelSummary> {
  const body = new FormData();
  body.set("file", file);
  if (name.trim()) body.set("name", name.trim());
  return fetchJson<ModelSummary>("/api/models", undefined, { method: "POST", body });
}

export function deleteModel(modelId: string): Promise<void> {
  return fetchNoContent(`/api/models/${encodeURIComponent(modelId)}`, {
    method: "DELETE",
  });
}
