import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";

import { getBuildingStepCount } from "./buildingSteps";
import { BuildingStepControls } from "./BuildingStepControls";
import {
  LDrawModel,
  LDrawModelSource,
  useLDrawModel,
} from "./LDrawModel";
import { useLibraryStatus } from "./useLibraryStatus";
import { ViewerCamera } from "./ViewerCamera";

const BOOTSTRAP_COMMAND =
  "docker compose run --rm api python -m app.cli.ldraw_library install";

const SYNTHETIC_MODEL: LDrawModelSource = {
  kind: "synthetic",
  key: "building-step-demo",
  url: "/models/demo-steps.ldr",
};

const OFFICIAL_BRICK: LDrawModelSource = {
  kind: "official",
  key: "official-3001",
  url: "/api/ldraw/parts/3001.dat",
  materialsUrl: "/api/ldraw/LDConfig.ldr",
  partsLibraryPath: "/api/ldraw/",
};

type ModelChoice = "demo" | "official";

export function LDrawViewer() {
  const libraryState = useLibraryStatus();
  const [modelChoice, setModelChoice] = useState<ModelChoice>("demo");
  const libraryInstalled =
    libraryState.kind === "ready" && libraryState.status.installed;
  const effectiveChoice = libraryInstalled ? modelChoice : "demo";
  const modelSource = effectiveChoice === "official" ? OFFICIAL_BRICK : SYNTHETIC_MODEL;
  const loadState = useLDrawModel(modelSource);
  const [selectedStep, setSelectedStep] = useState(0);
  const [resetVersion, setResetVersion] = useState(0);
  const model = loadState.kind === "ready" ? loadState.model : null;
  const stepCount = useMemo(
    () => (model === null ? 1 : getBuildingStepCount(model)),
    [model],
  );

  useEffect(() => {
    setSelectedStep(0);
  }, [model]);

  function selectStep(step: number) {
    const nextStep = Math.min(Math.max(Math.trunc(step), 0), stepCount - 1);
    setSelectedStep(nextStep);
  }

  return (
    <>
      <section className="viewer-section" aria-labelledby="viewer-title">
        <div className="viewer-heading">
          <div>
            <p className="eyebrow">Checkpoint 3</p>
            <h2 id="viewer-title">LDraw viewer</h2>
          </div>
          <p>Drag to rotate · Scroll to zoom</p>
        </div>

        <LibraryControls
          libraryState={libraryState}
          libraryInstalled={libraryInstalled}
          modelChoice={effectiveChoice}
          onModelChoice={setModelChoice}
        />

        <div className="viewer-frame">
          <Canvas
            camera={{ fov: 40, near: 0.1, far: 10_000 }}
            dpr={[1, 2]}
            role="img"
            aria-label="Interactive three-dimensional LDraw model"
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

      <aside className="ldraw-attribution" aria-label="LDraw attribution">
        <strong>This software uses the LDraw Parts Library.</strong>{" "}
        <a href="https://www.ldraw.org/">LDraw.org</a> is a community-run project
        and is not sponsored, endorsed, or authorized by the LEGO Group. Library
        files retain their upstream CC BY 2.0, CC BY 4.0, or CC0 notices as
        identified in each file; see the{" "}
        <a href="https://www.ldraw.org/legal-info">LDraw legal information</a>.
      </aside>
    </>
  );
}

interface LibraryControlsProps {
  libraryState: ReturnType<typeof useLibraryStatus>;
  libraryInstalled: boolean;
  modelChoice: ModelChoice;
  onModelChoice: (choice: ModelChoice) => void;
}

function LibraryControls({
  libraryState,
  libraryInstalled,
  modelChoice,
  onModelChoice,
}: LibraryControlsProps) {
  if (libraryState.kind === "loading") {
    return (
      <div className="library-notice" role="status">
        Checking official library status…
      </div>
    );
  }

  if (libraryState.kind === "error") {
    return (
      <div className="library-notice library-notice--warning" role="alert">
        Unable to check the official library. Showing the building-step demo.
        <span>{libraryState.message}</span>
      </div>
    );
  }

  if (!libraryInstalled) {
    return (
      <div className="library-notice library-notice--warning">
        <strong>Official library not installed</strong>
        <span>Install it once from the repository root:</span>
        <pre>
          <code>{BOOTSTRAP_COMMAND}</code>
        </pre>
      </div>
    );
  }

  return (
    <fieldset className="model-selector">
      <legend>Displayed model</legend>
      <label>
        <input
          type="radio"
          name="displayed-model"
          checked={modelChoice === "demo"}
          onChange={() => onModelChoice("demo")}
        />
        Building-step demo
      </label>
      <label>
        <input
          type="radio"
          name="displayed-model"
          checked={modelChoice === "official"}
          onChange={() => onModelChoice("official")}
        />
        Official Brick 2 x 4 (3001.dat)
      </label>
    </fieldset>
  );
}
