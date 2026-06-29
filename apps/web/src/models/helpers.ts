import { ApiError } from "../api/client";
import type {
  CoverageStatus,
  ModelBomItem,
  ModelCoverageItem,
  ModelImportStatus,
} from "../api/models";

export const MODEL_UPLOAD_LIMIT_BYTES = 25 * 1024 * 1024;

export function validateModelUpload(file: Pick<File, "name" | "size"> | null): string | null {
  if (file === null) return "Choose an LDR or MPD file.";
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (extension !== "ldr" && extension !== "mpd") {
    return "Only .ldr and .mpd files are supported.";
  }
  if (file.size === 0) return "The selected file is empty.";
  if (file.size > MODEL_UPLOAD_LIMIT_BYTES) return "The selected file exceeds 25 MiB.";
  return null;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function modelStatusLabel(status: ModelImportStatus): string {
  if (status === "ready") return "Ready";
  if (status === "ready_with_warnings") return "Ready with warnings";
  return "Failed";
}

export function modelUploadError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return `${error.message}. Open the existing model instead.`;
    if (error.status === 413) return "The model exceeds the server upload-size limit.";
    if (error.status === 422) return error.message;
  }
  return error instanceof Error ? error.message : "Model upload failed.";
}

export function filterModelBom(items: ModelBomItem[], query: string): ModelBomItem[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return items;
  return items.filter(
    (item) =>
      item.partId.toLowerCase().includes(normalized) ||
      item.partName.toLowerCase().includes(normalized) ||
      item.colorName.toLowerCase().includes(normalized),
  );
}

export function formatCoveragePercentage(value: number): string {
  const bounded = coverageProgressValue(value);
  return `${Number(bounded.toFixed(2))}%`;
}

export function coverageProgressValue(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

export function coverageStatusLabel(status: CoverageStatus): string {
  if (status === "complete") return "Complete";
  if (status === "partial") return "Partially covered";
  return "Missing";
}

export function filterCoverageItems(
  items: ModelCoverageItem[],
  query: string,
  status: CoverageStatus | "all",
  missingOnly: boolean,
): ModelCoverageItem[] {
  const normalized = query.trim().toLowerCase();
  return items.filter((item) => {
    if (missingOnly && item.missingQuantity === 0) return false;
    if (status !== "all" && item.status !== status) return false;
    return (
      !normalized ||
      item.partId.toLowerCase().includes(normalized) ||
      item.partName.toLowerCase().includes(normalized)
    );
  });
}

export function coverageEmptyMessage(missingOnly: boolean, hasFilters: boolean): string {
  if (missingOnly && !hasFilters) {
    return "You have all the pieces required for this model.";
  }
  return "No model parts match these filters.";
}
