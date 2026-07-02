import { useEffect } from "react";
import { useThree } from "@react-three/fiber";

/**
 * Lowers the canvas device-pixel ratio while a performance regression is
 * active (camera interaction, step scrubbing) and restores it afterwards.
 * Without a subscriber like this, `performance.regress()` has no effect.
 */
export function AdaptiveViewerDpr() {
  const current = useThree((state) => state.performance.current);
  const initialDpr = useThree((state) => state.viewport.initialDpr);
  const setDpr = useThree((state) => state.setDpr);
  const invalidate = useThree((state) => state.invalidate);

  useEffect(() => {
    setDpr(current * initialDpr);
    invalidate();
  }, [current, initialDpr, invalidate, setDpr]);

  return null;
}
