import { ApiError } from "../api/client";
import type {
  CoverageStatus,
  ModelBomItem,
  ModelCoverageItem,
  ModelImportIssue,
  ModelImportStatus,
  ModelReferenceResolution,
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

const IMPORT_ISSUE_LABELS: Record<string, string> = {
  unresolved_reference: "Unresolved reference",
  unsupported_custom_part: "Unsupported custom part",
  generated_section_without_parts: "Generated section without parts",
  undetermined_color: "Undetermined colour",
  unknown_color: "Unknown colour",
  edge_color_not_physical: "Edge colour excluded",
  malformed_type1_reference: "Malformed reference",
  recursive_submodel_cycle: "Recursive submodel cycle",
  custom_part_auto_mapped: "Auto-mapped custom part",
  reference_manually_mapped: "Manually mapped reference",
  reference_ignored: "Ignored reference",
};

export function importIssueLabel(code: string): string {
  return IMPORT_ISSUE_LABELS[code] ?? code.replaceAll("_", " ");
}

/**
 * Issue codes a manual reference resolution can address: they identify a
 * concrete referenced file that can be mapped to an official part (with an
 * optional colour override) or excluded from the BOM.
 */
const RESOLVABLE_ISSUE_CODES = new Set([
  "unresolved_reference",
  "unsupported_custom_part",
  "generated_section_without_parts",
  "undetermined_color",
]);

export function isResolvableIssue(issue: ModelImportIssue): boolean {
  return issue.referencedFilename !== null && RESOLVABLE_ISSUE_CODES.has(issue.code);
}

export function sortImportIssues(issues: ModelImportIssue[]): ModelImportIssue[] {
  const rank = (issue: ModelImportIssue) => (issue.severity === "warning" ? 0 : 1);
  return [...issues].sort((a, b) => rank(a) - rank(b));
}

export function resolutionLabel(resolution: ModelReferenceResolution): string {
  if (resolution.action === "ignore") return "Excluded from the BOM";
  const target = `Mapped to ${resolution.partId ?? "?"}`;
  return resolution.colorCode === null ? target : `${target} in colour ${resolution.colorCode}`;
}

/** Starting catalog-search query for mapping a reference: the filename stem
 * without LDCad set-wrapper prefixes or bent-variant suffixes. */
export function suggestedMapQuery(reference: string): string {
  const basename = reference.split("/").pop() ?? reference;
  return basename
    .replace(/\.(dat|ldr)$/i, "")
    .replace(/^\d{3,7}\s*-\s*/, "")
    .replace(/[_-](bended|bent)$/i, "")
    .trim();
}
