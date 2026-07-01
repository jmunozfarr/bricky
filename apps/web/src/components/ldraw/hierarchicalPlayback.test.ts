import { describe, expect, it } from "vitest";

import {
  breadcrumbLabels,
  clampLocalStep,
  isChildAttached,
  isPlaybackEntryVisible,
  localStepBoundaries,
  localRenderNotice,
  occurrenceRequestKey,
  parentOccurrenceId,
  repeatedDefinitionLabel,
  rootOccurrenceId,
  selectInitialViewerMode,
} from "./hierarchicalPlayback";
import { InstructionPlaybackOccurrence } from "../../api/models";

const occurrence: InstructionPlaybackOccurrence = {
  modelId: "model",
  occurrenceId: "occ-000003",
  parentOccurrenceId: "occ-000002",
  sourceSubmodelName: "wheel-hub.ldr",
  attachmentStep: 2,
  depth: 2,
  traversalOrder: 3,
  breadcrumbs: [
    { occurrenceId: "occ-000001", sourceSubmodelName: "main.ldr" },
    { occurrenceId: "occ-000002", sourceSubmodelName: "front_axle.ldr" },
    { occurrenceId: "occ-000003", sourceSubmodelName: "wheel-hub.ldr" },
  ],
  localStepCount: 3,
  currentStep: 1,
  previousStep: null,
  nextStep: 2,
  complete: false,
  empty: false,
  repeatedDefinitionCount: 2,
  repeatedDefinitionIndex: 1,
  stepSummary: {
    step: 1,
    localPartCount: 1,
    childAttachmentCount: 0,
    directGeometryCommandCount: 0,
  },
  children: [],
  childTotal: 0,
  childOffset: 0,
  childLimit: 50,
  sceneSourceUrl: "/source",
  renderStrategy: "subtree",
  recommendedRenderStrategy: "subtree",
  renderStrategyReason: "within_scope_complexity_limits",
  complexity: {
    expandedInstructionNodeCount: 3,
    expandedOccurrenceCount: 2,
    directGeometryCommandCount: 0,
    estimatedDerivedSourceBytes: 1024,
  },
};

describe("hierarchical playback helpers", () => {
  it("isolates occurrence request caches by model identity", () => {
    expect(occurrenceRequestKey("model-a", "occ-000001", 2, 0)).not.toBe(
      occurrenceRequestKey("model-b", "occ-000001", 2, 0),
    );
  });
  it("selects hierarchical mode only for a valid summary", () => {
    expect(
      selectInitialViewerMode({
        modelId: "model",
        available: true,
        rootOccurrenceId: "occ-000001",
        fallbackReason: null,
        issues: [],
        recommendedRenderStrategy: "subtree",
        renderStrategyReason: "within_scope_complexity_limits",
        complexity: occurrence.complexity,
        flattenedRenderingAllowed: true,
      }),
    ).toEqual({ mode: "hierarchical", fallbackReason: null });
    expect(
      selectInitialViewerMode({
        modelId: "model",
        available: false,
        rootOccurrenceId: null,
        fallbackReason: "Cycle detected",
        issues: [],
        recommendedRenderStrategy: null,
        renderStrategyReason: "instruction_graph_unavailable",
        complexity: null,
        flattenedRenderingAllowed: true,
      }),
    ).toEqual({ mode: "flattened", fallbackReason: "Cycle detected" });
  });

  it("blocks unsafe flattened fallback and describes local canvas omissions", () => {
    expect(
      selectInitialViewerMode({
        modelId: "model",
        available: true,
        rootOccurrenceId: "occ-000001",
        fallbackReason: null,
        issues: [],
        recommendedRenderStrategy: "local",
        renderStrategyReason: "scope_complexity_limit",
        complexity: occurrence.complexity,
        flattenedRenderingAllowed: false,
      }),
    ).toEqual({ mode: "hierarchical", fallbackReason: null });
    expect(
      selectInitialViewerMode({
        modelId: "model",
        available: false,
        rootOccurrenceId: null,
        fallbackReason: "Scope exceeds safety limits",
        issues: [],
        recommendedRenderStrategy: "local",
        renderStrategyReason: "scope_complexity_limit",
        complexity: occurrence.complexity,
        flattenedRenderingAllowed: false,
      }),
    ).toEqual({ mode: "blocked", fallbackReason: "Scope exceeds safety limits" });
    expect(localRenderNotice("local")).toContain("geometry is omitted");
    expect(localRenderNotice("subtree")).toBeNull();
  });

  it("calculates direct local-step boundaries", () => {
    expect(clampLocalStep(9, 3)).toBe(3);
    expect(localStepBoundaries(1, 3)).toEqual({ previous: null, next: 2, complete: false });
    expect(localStepBoundaries(3, 3)).toEqual({ previous: 2, next: null, complete: true });
  });

  it("uses attachment steps and active local steps as visibility truth", () => {
    expect(isChildAttached(2, 1)).toBe(false);
    expect(isChildAttached(2, 2)).toBe(true);
    expect(
      isPlaybackEntryVisible(
        {
          kind: "part",
          occurrenceId: "occ-000001",
          parentOccurrenceId: "occ-000001",
          localStep: 3,
          attachmentStep: null,
        },
        "occ-000001",
        2,
      ),
    ).toBe(false);
    expect(
      isPlaybackEntryVisible(
        {
          kind: "occurrence",
          occurrenceId: "occ-000002",
          parentOccurrenceId: "occ-000001",
          localStep: null,
          attachmentStep: 2,
        },
        "occ-000001",
        2,
      ),
    ).toBe(true);
  });

  it("builds breadcrumbs and parent/root navigation", () => {
    expect(breadcrumbLabels(occurrence.breadcrumbs)).toEqual(["main", "front axle", "wheel hub"]);
    expect(parentOccurrenceId(occurrence)).toBe("occ-000002");
    expect(rootOccurrenceId(occurrence)).toBe("occ-000001");
  });

  it("labels repeated definitions without merging occurrences", () => {
    expect(
      repeatedDefinitionLabel({ repeatedDefinitionCount: 2, repeatedDefinitionIndex: 1 }),
    ).toBe("Occurrence 1 of 2");
    expect(
      repeatedDefinitionLabel({ repeatedDefinitionCount: 1, repeatedDefinitionIndex: 1 }),
    ).toBeNull();
  });
});
