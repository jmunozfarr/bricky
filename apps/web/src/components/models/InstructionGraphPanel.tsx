import { useState } from "react";

import { InstructionGraph } from "../../api/models";
import { Alert } from "../ui/primitives";
import { useInstructionGraph } from "../../queries/hooks";

type InstructionGraphState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; data: InstructionGraph }
  | { kind: "error"; message: string };

/** Developer diagnostic (?debug=viewer): the raw instruction hierarchy. */
export function InstructionGraphPanel({ modelId }: { modelId: string }) {
  const [opened, setOpened] = useState(false);
  const query = useInstructionGraph(modelId, opened);
  const state: InstructionGraphState = !opened
    ? { kind: "idle" }
    : query.isError
      ? {
          kind: "error",
          message:
            query.error instanceof Error
              ? query.error.message
              : "Unable to load instruction graph.",
        }
      : query.data !== undefined
        ? { kind: "ready", data: query.data }
        : { kind: "loading" };

  const visibleOccurrenceLimit = 500;
  return (
    <details
      className="page-panel instruction-graph-panel"
      onToggle={(event) => {
        if (event.currentTarget.open) setOpened(true);
      }}
    >
      <summary>
        <span>
          <span className="eyebrow">Developer diagnostic</span>Instruction hierarchy
        </span>
      </summary>
      {state.kind === "loading" && <div className="page-message">Parsing instruction graph…</div>}
      {state.kind === "error" && <Alert title={state.message} />}
      {state.kind === "ready" && (
        <div className="instruction-graph-content">
          <dl className="part-metadata">
            <Meta label="Model definitions" value={state.data.modelDefinitionCount} />
            <Meta label="Expanded occurrences" value={state.data.expandedOccurrenceCount} />
            <Meta label="Instruction nodes" value={state.data.instructionNodeCount} />
            <Meta label="Maximum depth" value={state.data.maximumNestingDepth} />
            <Meta label="Truncated" value={state.data.truncated ? "Yes" : "No"} />
          </dl>
          {state.data.issues.length > 0 && (
            <ul className="issue-list">
              {state.data.issues.map((issue, index) => (
                <li key={`${issue.code}-${index}`}>
                  <strong>{issue.code.replaceAll("_", " ")}</strong>
                  <span>{issue.message}</span>
                </li>
              ))}
            </ul>
          )}
          <ol className="instruction-tree">
            {state.data.occurrences.slice(0, visibleOccurrenceLimit).map((occurrence) => (
              <li
                key={occurrence.occurrenceId}
                style={{ marginLeft: `${Math.min(occurrence.depth, 12) * 1.25}rem` }}
              >
                <code>{occurrence.occurrenceId}</code>
                <strong>{occurrence.sourceSubmodelName}</strong>
                <span>
                  depth {occurrence.depth}
                  {occurrence.attachmentStep !== null
                    ? ` · parent step ${occurrence.attachmentStep}`
                    : " · root"}
                  {occurrence.effectiveColor !== null
                    ? ` · color ${occurrence.effectiveColor}`
                    : ""}
                  {` · position ${occurrence.localTransform.translation.join(", ")}`}
                </span>
              </li>
            ))}
          </ol>
          {state.data.expandedOccurrenceCount > visibleOccurrenceLimit && (
            <p className="metadata-warning">
              Showing the first {visibleOccurrenceLimit.toLocaleString()} occurrences in
              deterministic traversal order.
            </p>
          )}
        </div>
      )}
    </details>
  );
}

function Meta({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
