import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";

import { AdaptiveViewerDpr } from "./AdaptiveViewerDpr";
import { AdaptiveViewerLines } from "./AdaptiveViewerLines";
import { getBuildingStepCount } from "./buildingSteps";
import { BuildingStepControls } from "./BuildingStepControls";
import { LDrawModel, LDrawModelSource, useLDrawModel } from "./LDrawModel";
import { ViewerCamera } from "./ViewerCamera";
import { WebGlLifecycle } from "./WebGlLifecycle";
import { maximumViewerDpr } from "./viewerQuality";
import {
  CameraCommand,
  CameraCommandInput,
  isEditableShortcutTarget,
  ViewerToolbar,
} from "./ViewerToolbar";

export const SYNTHETIC_MODEL_SOURCE: LDrawModelSource = {
  kind: "synthetic",
  key: "building-step-demo",
  url: "/models/demo-steps.ldr",
};

export function officialModelSource(partId: string, assetUrl: string): LDrawModelSource {
  return {
    kind: "official",
    key: `official-${partId}`,
    url: assetUrl,
    materialsUrl: "/api/ldraw/LDConfig.ldr",
    partsLibraryPath: "/api/ldraw/",
  };
}

export function importedModelSource(modelId: string, sourceUrl: string): LDrawModelSource {
  return {
    kind: "official",
    key: `imported-${modelId}`,
    url: sourceUrl,
    materialsUrl: "/api/ldraw/LDConfig.ldr",
    partsLibraryPath: "/api/ldraw/",
  };
}

interface LDrawViewerProps {
  source: LDrawModelSource;
  eyebrow: string;
  title: string;
}

export function LDrawViewer({ source, eyebrow, title }: LDrawViewerProps) {
  const [retryVersion, setRetryVersion] = useState(0);
  const [contextLost, setContextLost] = useState(false);
  const [canvasVersion, setCanvasVersion] = useState(0);
  const loadState = useLDrawModel(source, retryVersion);
  const [selectedStep, setSelectedStep] = useState(0);
  const [cameraCommand, setCameraCommand] = useState<CameraCommand>({
    id: 0,
    kind: "fit",
    preset: "isometric",
  });
  const viewerRef = useRef<HTMLElement>(null);
  const model = loadState.kind === "ready" ? loadState.model : null;
  const stepCount = useMemo(() => (model === null ? 1 : getBuildingStepCount(model)), [model]);

  useEffect(() => setSelectedStep(0), [model]);

  function selectStep(step: number) {
    setSelectedStep(Math.min(Math.max(Math.trunc(step), 0), stepCount - 1));
  }

  function issueCameraCommand(command: CameraCommandInput) {
    setCameraCommand((current) => ({ ...command, id: current.id + 1 }));
  }

  function handleShortcut(event: KeyboardEvent<HTMLElement>) {
    if (isEditableShortcutTarget(event.target)) return;
    const key = event.key.toLowerCase();
    if (key === "arrowleft") selectStep(selectedStep - 1);
    else if (key === "arrowright") selectStep(selectedStep + 1);
    else if (key === "home") selectStep(0);
    else if (key === "end") selectStep(stepCount - 1);
    else if (key === "r") issueCameraCommand({ kind: "fit", preset: "isometric" });
    else if (key === "1") issueCameraCommand({ kind: "fit", preset: "isometric" });
    else if (key === "2") issueCameraCommand({ kind: "fit", preset: "front" });
    else if (key === "3") issueCameraCommand({ kind: "fit", preset: "right" });
    else if (key === "4") issueCameraCommand({ kind: "fit", preset: "top" });
    else if (key === "+" || key === "=") issueCameraCommand({ kind: "zoom", direction: "in" });
    else if (key === "-" || key === "_") issueCameraCommand({ kind: "zoom", direction: "out" });
    else if (key === "f" && document.fullscreenEnabled) {
      if (document.fullscreenElement === viewerRef.current) void document.exitFullscreen();
      else void viewerRef.current?.requestFullscreen();
    } else return;
    event.preventDefault();
  }

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Shortcuts bubble up from the focusable viewer frame below; the section itself never takes focus.
    <section
      ref={viewerRef}
      className="viewer-section"
      aria-labelledby="viewer-title"
      onKeyDown={handleShortcut}
    >
      <div className="viewer-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2 id="viewer-title">{title}</h2>
        </div>
        <p>Drag to rotate · Scroll to zoom</p>
      </div>
      <ViewerToolbar containerRef={viewerRef} onCameraCommand={issueCameraCommand} />
      <div
        className="viewer-frame"
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- The frame hosts the 3D canvas and receives focus for the documented keyboard camera/step controls.
        tabIndex={0}
        aria-label={`Keyboard controls for ${title}`}
      >
        <Canvas
          key={canvasVersion}
          camera={{ fov: 40, near: 0.1, far: 10_000 }}
          dpr={[1, maximumViewerDpr(window.innerWidth, window.devicePixelRatio)]}
          frameloop="demand"
          performance={{ min: 0.75, debounce: 300 }}
          role="img"
          aria-label={`Interactive three-dimensional view of ${title}`}
          fallback={<div className="viewer-message">WebGL is unavailable.</div>}
        >
          <WebGlLifecycle
            onContextLost={() => setContextLost(true)}
            onContextRestored={() => {
              setContextLost(false);
              setCanvasVersion((version) => version + 1);
            }}
          />
          <AdaptiveViewerDpr />
          <AdaptiveViewerLines />
          <ambientLight intensity={1.45} />
          <directionalLight position={[100, 150, 100]} intensity={2.2} />
          <directionalLight position={[-80, 60, -100]} intensity={1.1} />
          {model !== null && <LDrawModel model={model} selectedStep={selectedStep} />}
          <ViewerCamera model={model} fitVersion={source.key} command={cameraCommand} />
        </Canvas>
        {loadState.kind === "loading" && (
          <div className="viewer-message" role="status">
            Loading LDraw model…
          </div>
        )}
        {loadState.kind === "error" && (
          <div className="viewer-message viewer-message--error" role="alert">
            <strong>Unable to load the LDraw model.</strong>
            <span>{loadState.message}</span>
            <button type="button" onClick={() => setRetryVersion((value) => value + 1)}>
              Try again
            </button>
          </div>
        )}
        {contextLost && (
          <div className="viewer-message viewer-message--error" role="alert">
            <strong>The 3D graphics context was interrupted.</strong>
            <span>The viewer will recover when the browser restores WebGL.</span>
          </div>
        )}
      </div>
      {loadState.kind === "ready" && (
        <>
          <p className="sr-only">
            {title}, step {selectedStep + 1} of {stepCount}.
          </p>
          <BuildingStepControls
            selectedStep={selectedStep}
            stepCount={stepCount}
            onStepChange={selectStep}
            onResetCamera={() => issueCameraCommand({ kind: "fit", preset: "isometric" })}
          />
        </>
      )}
    </section>
  );
}

export function LDrawAttribution() {
  return (
    <aside className="ldraw-attribution" aria-label="LDraw attribution">
      <strong>This software uses the LDraw Parts Library.</strong>{" "}
      <a href="https://www.ldraw.org/">LDraw.org</a> is community-run and is not sponsored,
      endorsed, or authorized by the LEGO Group. See the{" "}
      <a href="https://www.ldraw.org/legal-info">LDraw legal information</a>.
    </aside>
  );
}
