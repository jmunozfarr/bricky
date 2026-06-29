import { Canvas } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  getInstructionOccurrence,
  InstructionPlaybackOccurrence,
} from "../../api/models";
import {
  displaySubmodelName,
  repeatedDefinitionLabel,
} from "./hierarchicalPlayback";
import {
  HierarchicalLDrawModel,
  LDrawModelSource,
  useLDrawModel,
} from "./LDrawModel";
import { ViewerCamera } from "./ViewerCamera";

interface OccurrenceRequestState {
  data: InstructionPlaybackOccurrence | null;
  loading: boolean;
  error: string | null;
}

interface HierarchicalLDrawViewerProps {
  modelId: string;
  rootOccurrenceId: string;
  title: string;
}

export function HierarchicalLDrawViewer({
  modelId,
  rootOccurrenceId,
  title,
}: HierarchicalLDrawViewerProps) {
  const [activeOccurrenceId, setActiveOccurrenceId] = useState(rootOccurrenceId);
  const [selectedStep, setSelectedStep] = useState(1);
  const [childOffset, setChildOffset] = useState(0);
  const [request, setRequest] = useState<OccurrenceRequestState>({
    data: null,
    loading: true,
    error: null,
  });
  const [resetVersion, setResetVersion] = useState(0);
  const requestCache = useRef(new Map<string, InstructionPlaybackOccurrence>());
  const stepByOccurrence = useRef(new Map<string, number>([[rootOccurrenceId, 1]]));

  useEffect(() => {
    const cacheKey = `${activeOccurrenceId}:${selectedStep}:${childOffset}`;
    const cached = requestCache.current.get(cacheKey);
    if (cached) {
      setRequest({ data: cached, loading: false, error: null });
      return;
    }
    const controller = new AbortController();
    setRequest((current) => ({ ...current, loading: true, error: null }));
    void getInstructionOccurrence(
      modelId,
      activeOccurrenceId,
      selectedStep,
      childOffset,
      controller.signal,
    )
      .then((data) => {
        requestCache.current.set(cacheKey, data);
        setRequest({ data, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setRequest((current) => ({
          ...current,
          loading: false,
          error:
            error instanceof Error
              ? error.message
              : "Unable to load the instruction occurrence.",
        }));
      });
    return () => controller.abort();
  }, [activeOccurrenceId, childOffset, modelId, selectedStep]);

  const occurrence =
    request.data?.occurrenceId === activeOccurrenceId ? request.data : null;
  const sceneSource = useMemo<LDrawModelSource | null>(
    () =>
      occurrence
        ? {
            kind: "instruction-scope",
            key: `instruction-${modelId}-${occurrence.occurrenceId}`,
            url: occurrence.sceneSourceUrl,
            materialsUrl: "/api/ldraw/LDConfig.ldr",
            partsLibraryPath: "/api/ldraw/",
          }
        : null,
    [modelId, occurrence?.occurrenceId, occurrence?.sceneSourceUrl],
  );

  function enterOccurrence(occurrenceId: string) {
    stepByOccurrence.current.set(activeOccurrenceId, selectedStep);
    setActiveOccurrenceId(occurrenceId);
    setSelectedStep(stepByOccurrence.current.get(occurrenceId) ?? 1);
    setChildOffset(0);
  }

  function selectStep(step: number) {
    const count = occurrence?.localStepCount ?? 1;
    const selected = Math.min(Math.max(Math.trunc(step), 1), count);
    stepByOccurrence.current.set(activeOccurrenceId, selected);
    setSelectedStep(selected);
    setChildOffset(0);
  }

  return (
    <section className="viewer-section hierarchical-viewer" aria-labelledby="hierarchical-viewer-title">
      <div className="viewer-heading">
        <div>
          <p className="eyebrow">Hierarchical instructions</p>
          <h2 id="hierarchical-viewer-title">
            {occurrence ? displaySubmodelName(occurrence.sourceSubmodelName) : title}
          </h2>
        </div>
        <p>Drag to rotate · Scroll to zoom</p>
      </div>

      {occurrence && (
        <nav aria-label="Subassembly breadcrumb" className="instruction-breadcrumbs">
          <ol>
            {occurrence.breadcrumbs.map((item, index) => (
              <li key={item.occurrenceId}>
                {index < occurrence.breadcrumbs.length - 1 ? (
                  <button type="button" onClick={() => enterOccurrence(item.occurrenceId)}>
                    {displaySubmodelName(item.sourceSubmodelName)}
                  </button>
                ) : (
                  <span aria-current="page">{displaySubmodelName(item.sourceSubmodelName)}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}

      {sceneSource ? (
        <HierarchicalScene
          source={sceneSource}
          activeOccurrenceId={activeOccurrenceId}
          selectedStep={selectedStep}
          resetVersion={resetVersion}
          title={occurrence ? displaySubmodelName(occurrence.sourceSubmodelName) : title}
        />
      ) : (
        <div className="viewer-frame"><div className="viewer-message" role="status">Loading instruction scope…</div></div>
      )}

      {request.error && (
        <div className="error" role="alert">
          <strong>Instruction scope request failed.</strong><span>{request.error}</span>
        </div>
      )}
      {occurrence && (
        <div className="hierarchical-controls">
          <div className="step-actions" aria-label="Local instruction step navigation">
            <button
              type="button"
              disabled={occurrence.previousStep === null || request.loading}
              onClick={() => occurrence.previousStep !== null && selectStep(occurrence.previousStep)}
              aria-label="Show previous local step"
            >
              Previous
            </button>
            <output className="step-indicator" aria-live="polite">
              Local step {selectedStep} of {occurrence.localStepCount}
            </output>
            <button
              type="button"
              disabled={occurrence.nextStep === null || request.loading}
              onClick={() => occurrence.nextStep !== null && selectStep(occurrence.nextStep)}
              aria-label="Show next local step"
            >
              Next
            </button>
          </div>
          <label className="local-step-selector">
            <span>Go to local step</span>
            <input
              type="number"
              min={1}
              max={occurrence.localStepCount}
              value={selectedStep}
              onChange={(event) => selectStep(Number(event.currentTarget.value))}
            />
          </label>
          <div className="hierarchical-scope-actions">
            <button
              type="button"
              disabled={occurrence.parentOccurrenceId === null}
              onClick={() => occurrence.parentOccurrenceId && enterOccurrence(occurrence.parentOccurrenceId)}
              aria-label="Return to parent subassembly"
            >
              Return to parent
            </button>
            <button
              type="button"
              disabled={occurrence.occurrenceId === rootOccurrenceId}
              onClick={() => enterOccurrence(rootOccurrenceId)}
            >
              Return to root
            </button>
            <button type="button" onClick={() => setResetVersion((version) => version + 1)}>
              Reset camera
            </button>
          </div>

          <div className="playback-status" role="status">
            {request.loading || occurrence.currentStep !== selectedStep ? (
              <span>Updating step information…</span>
            ) : occurrence.empty ? (
              <strong>This subassembly has no instruction nodes.</strong>
            ) : occurrence.complete ? (
              <strong>Subassembly complete.</strong>
            ) : (
              <span>
                {occurrence.stepSummary.localPartCount} local part references and{" "}
                {occurrence.stepSummary.childAttachmentCount} child attachments at this step.
              </span>
            )}
            {occurrence.repeatedDefinitionCount > 1 && (
              <span>
                This is occurrence {occurrence.repeatedDefinitionIndex} of{" "}
                {occurrence.repeatedDefinitionCount} for this submodel definition.
              </span>
            )}
          </div>

          {!request.loading &&
            occurrence.currentStep === selectedStep &&
            occurrence.children.length > 0 && (
            <section className="child-subassemblies" aria-labelledby="child-subassemblies-title">
              <h3 id="child-subassemblies-title">Subassemblies attached at this step</h3>
              <ul>
                {occurrence.children.map((child) => (
                  <li key={child.occurrenceId}>
                    <div>
                      <strong>Build subassembly: {displaySubmodelName(child.sourceSubmodelName)}</strong>
                      {repeatedDefinitionLabel(child) && <span>{repeatedDefinitionLabel(child)}</span>}
                    </div>
                    <button
                      type="button"
                      onClick={() => enterOccurrence(child.occurrenceId)}
                      aria-label={`Enter subassembly ${displaySubmodelName(child.sourceSubmodelName)}`}
                    >
                      Enter subassembly
                    </button>
                  </li>
                ))}
              </ul>
              {occurrence.childTotal > occurrence.childLimit && (
                <div className="child-pagination" aria-label="Subassembly occurrence pages">
                  <button
                    type="button"
                    disabled={occurrence.childOffset === 0}
                    onClick={() => setChildOffset(Math.max(0, occurrence.childOffset - occurrence.childLimit))}
                  >
                    Previous occurrences
                  </button>
                  <span>
                    {occurrence.childOffset + 1}–
                    {Math.min(occurrence.childOffset + occurrence.children.length, occurrence.childTotal)} of{" "}
                    {occurrence.childTotal}
                  </span>
                  <button
                    type="button"
                    disabled={occurrence.childOffset + occurrence.children.length >= occurrence.childTotal}
                    onClick={() => setChildOffset(occurrence.childOffset + occurrence.childLimit)}
                  >
                    Next occurrences
                  </button>
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </section>
  );
}

function HierarchicalScene({
  source,
  activeOccurrenceId,
  selectedStep,
  resetVersion,
  title,
}: {
  source: LDrawModelSource;
  activeOccurrenceId: string;
  selectedStep: number;
  resetVersion: number;
  title: string;
}) {
  const loadState = useLDrawModel(source);
  const model = loadState.kind === "ready" ? loadState.model : null;
  const sceneIndex = loadState.kind === "ready" ? loadState.sceneIndex : null;

  return (
    <div className="viewer-frame">
      <Canvas
        camera={{ fov: 40, near: 0.1, far: 10_000 }}
        dpr={[1, 2]}
        role="img"
        aria-label={`Hierarchical three-dimensional view of ${title}`}
        fallback={<div className="viewer-message">WebGL is unavailable.</div>}
      >
        <color attach="background" args={["#e6e7e8"]} />
        <ambientLight intensity={1.4} />
        <directionalLight position={[100, 150, 100]} intensity={2.2} />
        <directionalLight position={[-80, 60, -100]} intensity={1.1} />
        {model && sceneIndex && (
          <>
            <HierarchicalLDrawModel
              model={model}
              sceneIndex={sceneIndex}
              activeOccurrenceId={activeOccurrenceId}
              selectedStep={selectedStep}
            />
            <ViewerCamera model={model} resetVersion={resetVersion} />
          </>
        )}
      </Canvas>
      {loadState.kind === "loading" && <div className="viewer-message" role="status">Loading subassembly geometry…</div>}
      {loadState.kind === "error" && (
        <div className="viewer-message viewer-message--error" role="alert">
          <strong>Unable to map the instruction scene.</strong><span>{loadState.message}</span>
        </div>
      )}
      {sceneIndex && (
        <span className="scene-diagnostic" aria-label={`${sceneIndex.objectCount} Three.js objects`}>
          {sceneIndex.objectCount.toLocaleString()} scene objects
        </span>
      )}
    </div>
  );
}
