import { useEffect } from "react";
import { useThree } from "@react-three/fiber";
import { LineSegments, Object3D } from "three";

/**
 * Shows or hides every edge and conditional-line segment under `root`.
 * LineSegments visibility is owned exclusively by this module: building-step
 * visibility and presentation variants only ever write `visible` on Groups.
 */
export function setLineSegmentsVisible(root: Object3D, visible: boolean): number {
  let changed = 0;
  root.traverse((object) => {
    if (object instanceof LineSegments && object.visible !== visible) {
      object.visible = visible;
      changed += 1;
    }
  });
  return changed;
}

/**
 * Hides edge and conditional lines while a performance regression is active
 * (camera interaction, step scrubbing) and restores them afterwards. Every
 * part contributes its own line segments, so on high part-count models they
 * roughly double the scene's draw calls; dropping them during interaction is
 * the difference between a rotation that stutters and one that tracks.
 */
export function AdaptiveViewerLines() {
  const regressed = useThree((state) => state.performance.current < 1);
  const scene = useThree((state) => state.scene);
  const invalidate = useThree((state) => state.invalidate);

  useEffect(() => {
    setLineSegmentsVisible(scene, !regressed);
    invalidate();
    return () => {
      if (regressed) {
        setLineSegmentsVisible(scene, true);
      }
    };
  }, [invalidate, regressed, scene]);

  return null;
}
