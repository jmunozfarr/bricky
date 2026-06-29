import {
  InstructionPlaybackOccurrence,
  InstructionPlaybackSummary,
  PlaybackBreadcrumb,
  PlaybackChild,
} from "../../api/models";

export type ImportedViewerMode = "hierarchical" | "flattened";

export interface ViewerModeSelection {
  mode: ImportedViewerMode;
  fallbackReason: string | null;
}

export interface PlaybackVisibilityEntry {
  kind: "occurrence" | "part";
  occurrenceId: string;
  parentOccurrenceId: string | null;
  localStep: number | null;
  attachmentStep: number | null;
}

export function selectInitialViewerMode(
  summary: InstructionPlaybackSummary,
): ViewerModeSelection {
  return summary.available && summary.rootOccurrenceId !== null
    ? { mode: "hierarchical", fallbackReason: null }
    : {
        mode: "flattened",
        fallbackReason:
          summary.fallbackReason ?? "A valid instruction graph is unavailable.",
      };
}

export function clampLocalStep(step: number, stepCount: number): number {
  const safeCount = Math.max(1, Math.trunc(stepCount));
  return Math.min(Math.max(Math.trunc(step), 1), safeCount);
}

export function localStepBoundaries(currentStep: number, stepCount: number) {
  const current = clampLocalStep(currentStep, stepCount);
  return {
    previous: current > 1 ? current - 1 : null,
    next: current < Math.max(1, Math.trunc(stepCount)) ? current + 1 : null,
    complete: current === Math.max(1, Math.trunc(stepCount)),
  };
}

export function isChildAttached(
  attachmentStep: number,
  currentParentStep: number,
): boolean {
  return attachmentStep <= currentParentStep;
}

export function isPlaybackEntryVisible(
  entry: PlaybackVisibilityEntry,
  activeOccurrenceId: string,
  currentStep: number,
): boolean {
  if (entry.kind === "part" && entry.occurrenceId === activeOccurrenceId) {
    return entry.localStep !== null && entry.localStep <= currentStep;
  }
  if (
    entry.kind === "occurrence" &&
    entry.parentOccurrenceId === activeOccurrenceId
  ) {
    return (
      entry.attachmentStep !== null &&
      isChildAttached(entry.attachmentStep, currentStep)
    );
  }
  return true;
}

export function breadcrumbLabels(
  breadcrumbs: PlaybackBreadcrumb[],
): string[] {
  return breadcrumbs.map((item) => displaySubmodelName(item.sourceSubmodelName));
}

export function parentOccurrenceId(
  occurrence: InstructionPlaybackOccurrence,
): string | null {
  return occurrence.parentOccurrenceId;
}

export function rootOccurrenceId(
  occurrence: InstructionPlaybackOccurrence,
): string {
  return occurrence.breadcrumbs[0]?.occurrenceId ?? occurrence.occurrenceId;
}

export function displaySubmodelName(sourceName: string): string {
  const basename = sourceName.replaceAll("\\", "/").split("/").at(-1) ?? sourceName;
  return basename.replace(/\.(?:ldr|mpd)$/i, "").replaceAll(/[-_]+/g, " ");
}

export function repeatedDefinitionLabel(
  item: Pick<PlaybackChild, "repeatedDefinitionCount" | "repeatedDefinitionIndex">,
): string | null {
  return item.repeatedDefinitionCount > 1
    ? `Occurrence ${item.repeatedDefinitionIndex} of ${item.repeatedDefinitionCount}`
    : null;
}
