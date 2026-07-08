import { Canvas } from "@react-three/fiber";
import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Group } from "three";

import { BuildManifest, BuildStep, ModelDetail } from "../api/models";
import { AdaptiveViewerDpr } from "../components/ldraw/AdaptiveViewerDpr";
import { AdaptiveViewerLines } from "../components/ldraw/AdaptiveViewerLines";
import { ViewerLoadingIndicator } from "../components/ldraw/ViewerLoadingIndicator";
import {
  displaySubmodelName,
  repeatedDefinitionLabel,
} from "../components/ldraw/hierarchicalPlayback";
import {
  HierarchicalLDrawModel,
  LDrawModelSource,
  useLDrawModel,
} from "../components/ldraw/LDrawModel";
import { InstructionPresentationMode } from "../components/ldraw/instructionPresentation";
import { ViewerCamera } from "../components/ldraw/ViewerCamera";
import {
  CameraCommand,
  CameraCommandInput,
  isEditableShortcutTarget,
  ViewerToolbar,
} from "../components/ldraw/ViewerToolbar";
import { WebGlLifecycle } from "../components/ldraw/WebGlLifecycle";
import { maximumViewerDpr } from "../components/ldraw/viewerQuality";
import { loadStepMemory, saveStepMemory } from "../builder/stepMemory";
import { errorMessage } from "../queries/async";
import { useBuildManifest, useInstructionPlayback, useModelDetail } from "../queries/hooks";

type BootstrapState =
  | { kind: "loading" }
  | { kind: "ready"; model: ModelDetail; rootOccurrenceId: string }
  | { kind: "error"; message: string };

type ManifestState =
  { kind: "loading" } | { kind: "ready"; data: BuildManifest } | { kind: "error"; message: string };

type WorkspaceMode = "build" | "inspect";

export default function VisualBuilderPage() {
  const { modelId = "" } = useParams();
  const [activeOccurrenceId, setActiveOccurrenceId] = useState<string | null>(null);
  const [selectedStep, setSelectedStep] = useState(1);
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>("build");
  const [focusCurrentStep, setFocusCurrentStep] = useState(true);
  // Builder progress survives page reloads: seeded from localStorage per
  // model and written through on every step change.
  const rememberedSteps = useRef<Map<string, number> | null>(null);
  rememberedSteps.current ??= loadStepMemory(modelId);

  function rememberStep(occurrenceId: string, step: number) {
    const steps = rememberedSteps.current ?? new Map<string, number>();
    steps.set(occurrenceId, step);
    saveStepMemory(modelId, steps);
  }

  const detailQuery = useModelDetail(modelId);
  const playbackQuery = useInstructionPlayback(modelId);
  const playback = playbackQuery.data;
  const rootOccurrenceId = playback?.available ? playback.rootOccurrenceId : null;
  const bootstrap: BootstrapState =
    detailQuery.isError || playbackQuery.isError
      ? {
          kind: "error",
          message: errorMessage(
            detailQuery.error ?? playbackQuery.error,
            "Unable to prepare the visual builder.",
          ),
        }
      : playback !== undefined && (!playback.available || playback.rootOccurrenceId === null)
        ? {
            kind: "error",
            message: playback.fallbackReason ?? "Guided building is unavailable for this model.",
          }
        : detailQuery.data !== undefined && rootOccurrenceId !== null
          ? { kind: "ready", model: detailQuery.data, rootOccurrenceId }
          : { kind: "loading" };

  useEffect(() => {
    if (rootOccurrenceId !== null) {
      setActiveOccurrenceId((current) => current ?? rootOccurrenceId);
    }
  }, [rootOccurrenceId]);

  const manifestQuery = useBuildManifest(modelId, activeOccurrenceId);
  const manifest: ManifestState = manifestQuery.isError
    ? {
        kind: "error",
        message: errorMessage(manifestQuery.error, "Unable to load this build task."),
      }
    : manifestQuery.data !== undefined
      ? { kind: "ready", data: manifestQuery.data }
      : { kind: "loading" };

  // Restore the remembered step whenever a (re)fetched manifest lands; the
  // map is updated on every user step change, so refetches are no-ops.
  const manifestData = manifestQuery.data;
  useEffect(() => {
    if (manifestData === undefined) return;
    setSelectedStep(
      Math.min(
        rememberedSteps.current?.get(manifestData.occurrenceId) ?? 1,
        Math.max(1, manifestData.steps.length),
      ),
    );
  }, [manifestData]);

  function chooseStep(step: number) {
    if (manifest.kind !== "ready" || Number.isNaN(step)) return;
    const selected = Math.min(Math.max(Math.trunc(step), 1), manifest.data.steps.length);
    rememberStep(manifest.data.occurrenceId, selected);
    setSelectedStep(selected);
  }

  function openOccurrence(occurrenceId: string) {
    if (manifest.kind === "ready") {
      rememberStep(manifest.data.occurrenceId, selectedStep);
    }
    setActiveOccurrenceId(occurrenceId);
  }

  if (bootstrap.kind === "loading") {
    return (
      <div className="page-message" role="status">
        Preparing visual builder…
      </div>
    );
  }
  if (bootstrap.kind === "error") {
    return (
      <div className="error" role="alert">
        <strong>Visual builder unavailable.</strong>
        <span>{bootstrap.message}</span>
      </div>
    );
  }

  const activeManifest = manifest.kind === "ready" ? manifest.data : null;
  const currentStep = activeManifest?.steps[selectedStep - 1] ?? null;

  return (
    <div className="visual-builder-page">
      <header className="builder-page-header">
        <div>
          <Link to={`/models/${modelId}`}>Back to model details</Link>
          <p className="eyebrow">Visual builder</p>
          <h2>{bootstrap.model.name}</h2>
        </div>
        <div className="builder-mode-switch" role="group" aria-label="Builder workspace mode">
          <button
            type="button"
            aria-pressed={workspaceMode === "build"}
            onClick={() => setWorkspaceMode("build")}
          >
            Build
          </button>
          <button
            type="button"
            aria-pressed={workspaceMode === "inspect"}
            onClick={() => setWorkspaceMode("inspect")}
          >
            Inspect
          </button>
        </div>
      </header>

      {manifest.kind === "loading" && (
        <div className="page-message" role="status">
          Loading build task…
        </div>
      )}
      {manifest.kind === "error" && (
        <div className="error" role="alert">
          {manifest.message}
        </div>
      )}
      {activeManifest && currentStep && (
        <BuilderWorkspace
          manifest={activeManifest}
          currentStep={currentStep}
          selectedStep={selectedStep}
          workspaceMode={workspaceMode}
          focusCurrentStep={focusCurrentStep}
          rootOccurrenceId={bootstrap.rootOccurrenceId}
          onStepChange={chooseStep}
          onOccurrenceChange={openOccurrence}
          onFocusChange={setFocusCurrentStep}
        />
      )}
    </div>
  );
}

function BuilderWorkspace({
  manifest,
  currentStep,
  selectedStep,
  workspaceMode,
  focusCurrentStep,
  rootOccurrenceId,
  onStepChange,
  onOccurrenceChange,
  onFocusChange,
}: {
  manifest: BuildManifest;
  currentStep: BuildStep;
  selectedStep: number;
  workspaceMode: WorkspaceMode;
  focusCurrentStep: boolean;
  rootOccurrenceId: string;
  onStepChange: (step: number) => void;
  onOccurrenceChange: (occurrenceId: string) => void;
  onFocusChange: (focused: boolean) => void;
}) {
  const workspaceRef = useRef<HTMLElement>(null);
  const [cameraCommand, setCameraCommand] = useState<CameraCommand>({
    id: 0,
    kind: "fit",
    preset: "isometric",
  });
  const parentOccurrenceId = manifest.parentOccurrenceId;

  function issueCameraCommand(command: CameraCommandInput) {
    setCameraCommand((current) => ({ ...command, id: current.id + 1 }));
  }

  function handleShortcut(event: KeyboardEvent<HTMLElement>) {
    if (isEditableShortcutTarget(event.target)) return;
    const key = event.key.toLowerCase();
    if (key === "arrowleft") onStepChange(selectedStep - 1);
    else if (key === "arrowright") onStepChange(selectedStep + 1);
    else if (key === "home") onStepChange(1);
    else if (key === "end") onStepChange(manifest.steps.length);
    else if (key === "r" || key === "1") issueCameraCommand({ kind: "fit", preset: "isometric" });
    else if (key === "2") issueCameraCommand({ kind: "fit", preset: "front" });
    else if (key === "3") issueCameraCommand({ kind: "fit", preset: "right" });
    else if (key === "4") issueCameraCommand({ kind: "fit", preset: "top" });
    else return;
    event.preventDefault();
  }

  const presentationMode: InstructionPresentationMode =
    workspaceMode === "inspect" ? "inspect" : focusCurrentStep ? "focus" : "assembled";

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Shortcuts bubble up from the focusable viewport below; the section itself never takes focus.
    <section
      ref={workspaceRef}
      className="builder-workspace"
      onKeyDown={handleShortcut}
      aria-label="Visual building workspace"
    >
      <nav className="builder-breadcrumbs" aria-label="Build task breadcrumb">
        {manifest.breadcrumbs.map((item, index) => (
          <span key={item.occurrenceId}>
            {index > 0 && <span aria-hidden="true">›</span>}
            {item.occurrenceId === manifest.occurrenceId ? (
              <strong aria-current="page">{displaySubmodelName(item.sourceSubmodelName)}</strong>
            ) : (
              <button type="button" onClick={() => onOccurrenceChange(item.occurrenceId)}>
                {displaySubmodelName(item.sourceSubmodelName)}
              </button>
            )}
          </span>
        ))}
      </nav>

      <div className="builder-main-grid">
        <div className="builder-view-column">
          <ViewerToolbar containerRef={workspaceRef} onCameraCommand={issueCameraCommand} />
          <BuilderViewport
            manifest={manifest}
            selectedStep={selectedStep}
            presentationMode={presentationMode}
            cameraCommand={cameraCommand}
          />
          <div className="builder-step-transport">
            <button
              type="button"
              disabled={selectedStep === 1}
              onClick={() => onStepChange(selectedStep - 1)}
            >
              Previous
            </button>
            <div className="builder-step-selector">
              <label className="builder-step-number">
                <span>Step</span>
                <StepNumberInput
                  selectedStep={selectedStep}
                  stepCount={manifest.steps.length}
                  onStepChange={onStepChange}
                />
                <span>of {manifest.steps.length}</span>
              </label>
              <input
                type="range"
                min={1}
                max={manifest.steps.length}
                value={selectedStep}
                aria-label="Scrub through building steps"
                onChange={(event) => onStepChange(event.currentTarget.valueAsNumber)}
              />
            </div>
            <button
              type="button"
              disabled={selectedStep === manifest.steps.length}
              onClick={() => onStepChange(selectedStep + 1)}
            >
              Next
            </button>
          </div>
        </div>

        <aside className="builder-step-panel" aria-labelledby="builder-step-title">
          <div className="builder-step-heading">
            <div>
              <p className="eyebrow">Current task</p>
              <h3 id="builder-step-title">Step {selectedStep}</h3>
            </div>
            {workspaceMode === "build" && (
              <div
                className="builder-presentation-switch"
                role="group"
                aria-label="Build presentation"
              >
                <button
                  type="button"
                  aria-pressed={focusCurrentStep}
                  onClick={() => onFocusChange(true)}
                >
                  Step focus
                </button>
                <button
                  type="button"
                  aria-pressed={!focusCurrentStep}
                  onClick={() => onFocusChange(false)}
                >
                  As built
                </button>
              </div>
            )}
          </div>

          {workspaceMode === "inspect" ? (
            <div className="builder-inspect-summary">
              <strong>Inspecting {displaySubmodelName(manifest.sourceSubmodelName)}</strong>
              <p>
                The complete safe scope is shown in full colour. Camera controls do not change the
                authored build steps.
              </p>
              {manifest.scene.renderStrategy === "local" && (
                <p>Open subassembly tasks to inspect their geometry separately.</p>
              )}
            </div>
          ) : (
            <>
              {manifest.scene.renderStrategy === "local" && (
                <p className="builder-scope-note">
                  This assembly exceeds the complete-rendering safety limit, so the 3D view shows
                  only the parts placed at this level. Subassemblies are built as separate tasks and
                  are not drawn here.
                </p>
              )}
              <p className="builder-inventory-note">
                Inventory is model-wide; pieces are not reserved or consumed by earlier steps.
              </p>
              <StepPartList step={currentStep} />
              {currentStep.attachments.length > 0 && (
                <section className="builder-task-list" aria-labelledby="subassembly-tasks-title">
                  <h4 id="subassembly-tasks-title">Subassemblies to attach</h4>
                  {currentStep.attachments.map((attachment) => (
                    <article key={attachment.occurrenceId}>
                      <div>
                        <strong>{displaySubmodelName(attachment.sourceSubmodelName)}</strong>
                        {repeatedDefinitionLabel(attachment) && (
                          <span>{repeatedDefinitionLabel(attachment)}</span>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => onOccurrenceChange(attachment.occurrenceId)}
                      >
                        Open build task
                      </button>
                    </article>
                  ))}
                </section>
              )}
              {currentStep.parts.length === 0 &&
                currentStep.attachments.length === 0 &&
                currentStep.directGeometryCommandCount === 0 && (
                  <p className="empty-state">No physical parts are added at this step.</p>
                )}
            </>
          )}

          {parentOccurrenceId && (
            <button
              className="button-link builder-return"
              type="button"
              onClick={() => onOccurrenceChange(parentOccurrenceId)}
            >
              Return to parent task
            </button>
          )}
          {manifest.occurrenceId !== rootOccurrenceId && (
            <button
              className="button-link"
              type="button"
              onClick={() => onOccurrenceChange(rootOccurrenceId)}
            >
              Return to model
            </button>
          )}
        </aside>
      </div>
    </section>
  );
}

function StepNumberInput({
  selectedStep,
  stepCount,
  onStepChange,
}: {
  selectedStep: number;
  stepCount: number;
  onStepChange: (step: number) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);

  function commit(value: string) {
    setDraft(null);
    if (value.trim() === "") return;
    const parsed = Number(value);
    if (Number.isFinite(parsed)) onStepChange(parsed);
  }

  return (
    <input
      type="number"
      min={1}
      max={stepCount}
      inputMode="numeric"
      value={draft ?? String(selectedStep)}
      onChange={(event) => {
        const value = event.currentTarget.value;
        const parsed = Number(value);
        if (Number.isInteger(parsed) && parsed >= 1 && parsed <= stepCount) {
          setDraft(null);
          onStepChange(parsed);
        } else {
          setDraft(value);
        }
      }}
      onBlur={(event) => commit(event.currentTarget.value)}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commit(event.currentTarget.value);
        }
      }}
    />
  );
}

function StepPartList({ step }: { step: BuildStep }) {
  if (step.parts.length === 0) return null;
  return (
    <section className="builder-parts" aria-labelledby="step-parts-title">
      <div className="builder-panel-title">
        <h4 id="step-parts-title">Parts added now</h4>
        <span>{step.parts.reduce((total, part) => total + part.quantityThisStep, 0)} pieces</span>
      </div>
      <ul>
        {step.parts.map((part) => (
          <li key={`${part.partId}-${part.colorCode ?? "inherited"}`}>
            <span
              className="color-swatch"
              style={{ backgroundColor: part.colorHex ?? "transparent" }}
              aria-hidden="true"
            />
            <div>
              <strong>
                {part.quantityThisStep}× {part.partName}
              </strong>
              <span>
                {part.partId} · {part.colorName}
              </span>
              <small>
                Own {part.ownedQuantity}; model needs {part.modelRequiredQuantity}
              </small>
            </div>
            <div className="builder-part-status">
              {part.modelMissingQuantity > 0 ? (
                <span className="coverage-status coverage-status--missing">
                  {part.modelMissingQuantity} missing
                </span>
              ) : (
                <span className="coverage-status coverage-status--complete">Covered</span>
              )}
              {part.catalogAvailable && (
                <Link to={`/catalog?part=${encodeURIComponent(part.partId)}`}>Inspect</Link>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function BuilderViewport({
  manifest,
  selectedStep,
  presentationMode,
  cameraCommand,
}: {
  manifest: BuildManifest;
  selectedStep: number;
  presentationMode: InstructionPresentationMode;
  cameraCommand: CameraCommand;
}) {
  const source = useMemo<LDrawModelSource>(
    () => ({
      kind: "instruction-scope",
      key: `builder-${manifest.scene.cacheKey}`,
      modelId: manifest.modelId,
      scopeId: manifest.occurrenceId,
      url: manifest.scene.url,
      materialsUrl: "/api/ldraw/LDConfig.ldr",
      partsLibraryPath: "/api/ldraw/",
    }),
    [manifest],
  );
  const [retryVersion, setRetryVersion] = useState(0);
  const [contextLost, setContextLost] = useState(false);
  const [canvasVersion, setCanvasVersion] = useState(0);
  const loadState = useLDrawModel(source, retryVersion);
  const sceneHost = useMemo(() => {
    const host = new Group();
    host.name = "__bricky_builder_scene";
    return host;
  }, []);
  const loaded = loadState.kind === "ready" || loadState.kind === "refreshing" ? loadState : null;

  return (
    <div
      className="builder-viewport"
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- The viewport hosts the 3D canvas and receives focus for the documented keyboard camera/step controls.
      tabIndex={0}
      aria-label={`Interactive build view of ${manifest.modelName}`}
    >
      <Canvas
        key={canvasVersion}
        camera={{ fov: 40, near: 0.1, far: 10_000 }}
        dpr={[1, maximumViewerDpr(window.innerWidth, window.devicePixelRatio)]}
        frameloop="demand"
        performance={{ min: 0.5, debounce: 300 }}
        role="img"
        aria-label={`Three-dimensional build view of ${manifest.sourceSubmodelName}`}
      >
        <WebGlLifecycle
          onContextLost={() => setContextLost(true)}
          onContextRestored={() => {
            setContextLost(false);
            setCanvasVersion((value) => value + 1);
          }}
        />
        <AdaptiveViewerDpr />
        <AdaptiveViewerLines />
        <ambientLight intensity={1.4} />
        <directionalLight position={[100, 150, 100]} intensity={2.2} />
        <directionalLight position={[-80, 60, -100]} intensity={1.1} />
        {loaded?.sceneIndex && (
          <HierarchicalLDrawModel
            host={sceneHost}
            model={loaded.model}
            sceneIndex={loaded.sceneIndex}
            activeOccurrenceId={manifest.occurrenceId}
            selectedStep={selectedStep}
            cacheKey={loaded.sourceKey}
            presentationMode={presentationMode}
          />
        )}
        <ViewerCamera
          model={loaded?.sceneIndex ? sceneHost : null}
          fitVersion={manifest.occurrenceId}
          command={cameraCommand}
        />
      </Canvas>
      {loadState.kind === "loading" && (
        <ViewerLoadingIndicator
          title="Preparing 3D scene…"
          detail="Loading parts and building geometry."
        />
      )}
      {loadState.kind === "refreshing" && (
        <div className="viewer-progress-badge" role="status">
          Updating assembly…
        </div>
      )}
      {loadState.kind === "error" && (
        <div className="viewer-message viewer-message--error" role="alert">
          <strong>Unable to prepare this assembly.</strong>
          <span>{loadState.message}</span>
          <button type="button" onClick={() => setRetryVersion((value) => value + 1)}>
            Try again
          </button>
        </div>
      )}
      {contextLost && (
        <div className="viewer-message viewer-message--error" role="alert">
          <strong>The 3D graphics context was interrupted.</strong>
          <span>The viewer will recover when WebGL is restored.</span>
        </div>
      )}
    </div>
  );
}
