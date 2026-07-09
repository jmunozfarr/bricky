import { Canvas } from "@react-three/fiber";
import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import { LDrawModel, useLDrawModel } from "../components/ldraw/LDrawModel";
import { officialModelSource } from "../components/ldraw/LDrawViewer";
import { ViewerCamera } from "../components/ldraw/ViewerCamera";

/**
 * Render surface for scripts/render-thumbnails.mjs: one official part on a
 * fixed square canvas with no chrome. The script reads readiness from the
 * wrapper's data-render-state attribute and screenshots the canvas.
 */
export default function ThumbnailHarnessPage() {
  const [params] = useSearchParams();
  const partId = params.get("part") ?? "";
  const assetUrl = params.get("asset") ?? "";
  const source = useMemo(() => officialModelSource(partId, assetUrl), [assetUrl, partId]);
  const loadState = useLDrawModel(source);
  const model = loadState.kind === "ready" ? loadState.model : null;

  if (partId === "" || assetUrl === "") {
    return <p>The part and asset query parameters are required.</p>;
  }
  return (
    <div className="thumbnail-harness" data-render-state={loadState.kind}>
      <Canvas
        camera={{ fov: 30, near: 0.1, far: 10_000 }}
        dpr={1}
        frameloop="demand"
        role="img"
        aria-label={`Thumbnail render of part ${partId}`}
        fallback={<p>WebGL is unavailable.</p>}
      >
        <ambientLight intensity={1.45} />
        <directionalLight position={[100, 150, 100]} intensity={2.2} />
        <directionalLight position={[-80, 60, -100]} intensity={1.1} />
        {model !== null && <LDrawModel model={model} selectedStep={0} />}
        <ViewerCamera
          model={model}
          fitVersion={loadState.kind === "ready" ? loadState.fitKey : "pending-scene"}
          command={{ id: 0, kind: "fit", preset: "isometric" }}
        />
      </Canvas>
    </div>
  );
}
