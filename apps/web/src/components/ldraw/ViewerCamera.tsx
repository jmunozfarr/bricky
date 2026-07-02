import { useEffect, useRef } from "react";
import { useThree } from "@react-three/fiber";
import { Box3, Group, MathUtils, PerspectiveCamera, Sphere, Vector3 } from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import { CameraCommand, CameraPreset } from "./ViewerToolbar";

interface ViewerCameraProps {
  model: Group | null;
  fitVersion: string | number;
  command: CameraCommand;
}

const presetDirections: Record<CameraPreset, Vector3> = {
  isometric: new Vector3(1, 0.75, 1).normalize(),
  front: new Vector3(0, 0, 1),
  right: new Vector3(1, 0, 0),
  top: new Vector3(0, 1, 0.001).normalize(),
};

export function ViewerCamera({ model, fitVersion, command }: ViewerCameraProps) {
  // Subscribe to individual store fields: `performance.regress()` replaces the
  // store's `performance` object, so depending on it (or on the whole store)
  // recreates the controls mid-drag on the first change event of a gesture.
  const camera = useThree((state) => state.camera);
  const gl = useThree((state) => state.gl);
  const invalidate = useThree((state) => state.invalidate);
  const regress = useThree((state) => state.performance.regress);
  const controlsRef = useRef<OrbitControls | null>(null);
  const fittedVersionRef = useRef<string | number | null>(null);
  const commandIdRef = useRef(-1);

  useEffect(() => {
    const controls = new OrbitControls(camera, gl.domElement);
    const handleChange = () => {
      regress();
      invalidate();
    };
    controls.enableDamping = false;
    controls.screenSpacePanning = true;
    controls.addEventListener("change", handleChange);
    controlsRef.current = controls;

    return () => {
      controls.removeEventListener("change", handleChange);
      controls.dispose();
      controlsRef.current = null;
    };
  }, [camera, gl, invalidate, regress]);

  useEffect(() => {
    const controls = controlsRef.current;
    if (controls === null || model === null || !(camera instanceof PerspectiveCamera)) {
      return;
    }

    const isNewScope = fittedVersionRef.current !== fitVersion;
    const isNewCommand = commandIdRef.current !== command.id;
    if (!isNewScope && !isNewCommand) return;
    fittedVersionRef.current = fitVersion;
    commandIdRef.current = command.id;

    if (command.kind === "zoom" && !isNewScope) {
      const offset = camera.position.clone().sub(controls.target);
      const factor = command.direction === "in" ? 0.8 : 1.25;
      camera.position.copy(controls.target).add(offset.multiplyScalar(factor));
      controls.update();
      invalidate();
      return;
    }

    model.updateWorldMatrix(true, true);
    const bounds = new Box3().setFromObject(model, true);
    if (bounds.isEmpty()) {
      return;
    }

    const sphere = bounds.getBoundingSphere(new Sphere());
    const halfFov = MathUtils.degToRad(camera.fov * 0.5);
    const distance = (sphere.radius / Math.sin(halfFov)) * 1.25;
    const preset = command.kind === "fit" ? command.preset : "isometric";
    const viewDirection = presetDirections[preset];

    camera.up.set(0, 1, 0);
    if (preset === "top") camera.up.set(0, 0, -1);

    camera.position.copy(sphere.center).addScaledVector(viewDirection, distance);
    camera.near = Math.max(distance / 100, 0.1);
    camera.far = Math.max(distance * 100, 1_000);
    camera.updateProjectionMatrix();

    controls.target.copy(sphere.center);
    controls.minDistance = Math.max(sphere.radius * 0.25, 1);
    controls.maxDistance = Math.max(sphere.radius * 12, distance * 2);
    controls.update();
    invalidate();
  }, [camera, command, fitVersion, invalidate, model]);

  return null;
}
