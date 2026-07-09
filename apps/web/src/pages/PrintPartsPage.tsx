import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import {
  BuildManifest,
  getBuildManifest,
  getInstructionGraph,
  getModel,
  ModelDetail,
} from "../api/models";
import { displaySubmodelName } from "../components/ldraw/hierarchicalPlayback";
import { PartThumbnail } from "../components/parts/PartThumbnail";
import { Alert } from "../components/ui/primitives";
import { errorMessage } from "../queries/async";

interface PrintTask {
  manifest: BuildManifest;
  timesBuilt: number;
}

interface PrintBundle {
  model: ModelDetail;
  tasks: PrintTask[];
}

/**
 * One printed section per distinct submodel definition, in traversal order:
 * repeated placements follow the same instructions, so they print once with
 * a build-count badge instead of once per occurrence.
 */
async function loadPrintBundle(modelId: string, signal?: AbortSignal): Promise<PrintBundle> {
  const [model, graph] = await Promise.all([
    getModel(modelId, signal),
    getInstructionGraph(modelId, signal),
  ]);
  const definitions = new Map<string, { occurrenceId: string; timesBuilt: number }>();
  for (const occurrence of graph.occurrences) {
    const existing = definitions.get(occurrence.sourceSubmodelName);
    if (existing === undefined) {
      definitions.set(occurrence.sourceSubmodelName, {
        occurrenceId: occurrence.occurrenceId,
        timesBuilt: 1,
      });
    } else {
      existing.timesBuilt += 1;
    }
  }
  const tasks: PrintTask[] = [];
  for (const target of definitions.values()) {
    tasks.push({
      manifest: await getBuildManifest(modelId, target.occurrenceId, signal),
      timesBuilt: target.timesBuilt,
    });
  }
  return { model, tasks };
}

export default function PrintPartsPage() {
  const { modelId = "" } = useParams();
  const bundle = useQuery({
    queryKey: ["print-parts", modelId],
    queryFn: ({ signal }) => loadPrintBundle(modelId, signal),
  });

  if (bundle.isError) {
    return (
      <Alert title="Unable to prepare the parts list.">
        {errorMessage(bundle.error, "The instruction data could not be loaded.")}
      </Alert>
    );
  }
  if (bundle.data === undefined) {
    return (
      <div className="page-message" role="status">
        Preparing the printable parts list…
      </div>
    );
  }

  const { model, tasks } = bundle.data;
  return (
    <div className="print-page">
      <header className="print-heading">
        <div>
          <p className="eyebrow">Printable per-step parts list</p>
          <h2>{model.name}</h2>
          <p>
            {model.totalPartQuantity.toLocaleString()} pieces · {tasks.length.toLocaleString()}{" "}
            build tasks
          </p>
        </div>
        <div className="print-actions">
          <Link className="button-link" to="/models">
            Back to models
          </Link>
          <button type="button" onClick={() => window.print()}>
            Print
          </button>
        </div>
      </header>

      {tasks.map(({ manifest, timesBuilt }) => (
        <section className="page-panel print-task" key={manifest.occurrenceId}>
          <div className="print-task-heading">
            <h3>{displaySubmodelName(manifest.sourceSubmodelName)}</h3>
            <span>
              {manifest.steps.length} steps
              {timesBuilt > 1 ? ` · built ${timesBuilt} times` : ""}
            </span>
          </div>
          {manifest.steps.map((step) => (
            <div className="print-step" key={step.step}>
              <h4>Step {step.step}</h4>
              {step.parts.length === 0 && step.attachments.length === 0 && (
                <p className="print-step-empty">No physical parts are added at this step.</p>
              )}
              {step.attachments.length > 0 && (
                <p className="print-step-attachments">
                  Attach completed subassembl{step.attachments.length > 1 ? "ies" : "y"}:{" "}
                  {step.attachments
                    .map((attachment) => displaySubmodelName(attachment.sourceSubmodelName))
                    .join(", ")}
                </p>
              )}
              {step.parts.length > 0 && (
                <ul className="print-step-parts">
                  {step.parts.map((part) => (
                    <li key={`${part.partId}-${part.colorCode ?? "inherited"}`}>
                      <PartThumbnail partId={part.partId} />
                      <strong>{part.quantityThisStep}×</strong>
                      <span>
                        {part.partName}
                        <small>
                          <span
                            className="color-swatch"
                            style={{ backgroundColor: part.colorHex ?? "transparent" }}
                            aria-hidden="true"
                          />
                          {part.partId} · {part.colorName}
                        </small>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
