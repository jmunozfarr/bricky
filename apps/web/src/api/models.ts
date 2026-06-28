import { fetchJson, fetchNoContent } from "./client";

export type ModelImportStatus = "ready" | "ready_with_warnings" | "failed";

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
