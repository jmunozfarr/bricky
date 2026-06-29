import { useEffect, useState } from "react";

import { getInstructionPlayback, InstructionPlaybackSummary } from "../../api/models";
import { HierarchicalLDrawViewer } from "./HierarchicalLDrawViewer";
import { ImportedViewerMode, selectInitialViewerMode } from "./hierarchicalPlayback";
import { importedModelSource, LDrawAttribution, LDrawViewer } from "./LDrawViewer";

export default function ImportedModelViewer({ modelId, sourceUrl, title }: { modelId: string; sourceUrl: string; title: string }) {
  const [summary, setSummary] = useState<InstructionPlaybackSummary | null>(null);
  const [mode, setMode] = useState<ImportedViewerMode | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setSummary(null);
    setSummaryError(null);
    setMode(null);
    void getInstructionPlayback(modelId, controller.signal)
      .then((result) => {
        setSummary(result);
        setMode(selectInitialViewerMode(result).mode);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setSummaryError(
          error instanceof Error ? error.message : "Instruction playback check failed.",
        );
        setMode("flattened");
      });
    return () => controller.abort();
  }, [modelId]);

  const fallbackReason = summary
    ? selectInitialViewerMode(summary).fallbackReason
    : summaryError;
  return (
    <>
      <section className="viewer-mode-panel" aria-labelledby="viewer-mode-title">
        <div>
          <p className="eyebrow">Imported model playback</p>
          <h2 id="viewer-mode-title">Viewer mode</h2>
        </div>
        <div className="segmented-control" aria-label="Imported model viewer mode">
          <button
            type="button"
            aria-pressed={mode === "hierarchical"}
            disabled={!summary?.available}
            onClick={() => setMode("hierarchical")}
          >
            Hierarchical
          </button>
          <button
            type="button"
            aria-pressed={mode === "flattened"}
            onClick={() => setMode("flattened")}
          >
            Flattened
          </button>
        </div>
        {mode === null && <p role="status">Checking hierarchical playback…</p>}
        {fallbackReason && <p className="metadata-warning" role="status">Flattened fallback: {fallbackReason}</p>}
      </section>
      {mode === "hierarchical" && summary?.rootOccurrenceId ? (
        <HierarchicalLDrawViewer
          modelId={modelId}
          rootOccurrenceId={summary.rootOccurrenceId}
          title={title}
        />
      ) : mode === "flattened" ? (
        <LDrawViewer
          source={importedModelSource(modelId, sourceUrl)}
          eyebrow="Flattened source steps"
          title={title}
        />
      ) : null}
      <LDrawAttribution />
    </>
  );
}
