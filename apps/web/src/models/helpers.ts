import { ApiError } from "../api/client";
import type { ModelBomItem, ModelImportStatus } from "../api/models";

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
