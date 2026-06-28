import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";

import { getBuildingStepCount } from "./buildingSteps";
import { BuildingStepControls } from "./BuildingStepControls";
import { LDrawModel, LDrawModelSource, useLDrawModel } from "./LDrawModel";
import { ViewerCamera } from "./ViewerCamera";

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
  const loadState = useLDrawModel(source);
  const [selectedStep, setSelectedStep] = useState(0);
  const [resetVersion, setResetVersion] = useState(0);
  const model = loadState.kind === "ready" ? loadState.model : null;
  const stepCount = useMemo(
    () => (model === null ? 1 : getBuildingStepCount(model)),
    [model],
  );

  useEffect(() => setSelectedStep(0), [model]);

  function selectStep(step: number) {
    setSelectedStep(Math.min(Math.max(Math.trunc(step), 0), stepCount - 1));
  }

  return (
    <section className="viewer-section" aria-labelledby="viewer-title">
      <div className="viewer-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2 id="viewer-title">{title}</h2>
        </div>
        <p>Drag to rotate · Scroll to zoom</p>
      </div>
      <div className="viewer-frame">
        <Canvas
          camera={{ fov: 40, near: 0.1, far: 10_000 }}
          dpr={[1, 2]}
          role="img"
          aria-label={`Interactive three-dimensional view of ${title}`}
          fallback={<div className="viewer-message">WebGL is unavailable.</div>}
        >
          <color attach="background" args={["#e6e7e8"]} />
          <ambientLight intensity={1.4} />
          <directionalLight position={[100, 150, 100]} intensity={2.2} />
          <directionalLight position={[-80, 60, -100]} intensity={1.1} />
          {model !== null && (
            <>
              <LDrawModel model={model} selectedStep={selectedStep} />
              <ViewerCamera model={model} resetVersion={resetVersion} />
            </>
          )}
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
          </div>
        )}
      </div>
      {loadState.kind === "ready" && (
        <BuildingStepControls
          selectedStep={selectedStep}
          stepCount={stepCount}
          onStepChange={selectStep}
          onResetCamera={() => setResetVersion((version) => version + 1)}
        />
      )}
    </section>
  );
}

export function LDrawAttribution() {
  return (
    <aside className="ldraw-attribution" aria-label="LDraw attribution">
      <strong>This software uses the LDraw Parts Library.</strong>{" "}
      <a href="https://www.ldraw.org/">LDraw.org</a> is community-run and is not
      sponsored, endorsed, or authorized by the LEGO Group. See the{" "}
      <a href="https://www.ldraw.org/legal-info">LDraw legal information</a>.
    </aside>
  );
}
