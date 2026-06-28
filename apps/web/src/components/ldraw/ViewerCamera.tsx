import { useEffect, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import {
  Box3,
  Group,
  MathUtils,
  PerspectiveCamera,
  Sphere,
  Vector3,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

interface ViewerCameraProps {
  model: Group;
  resetVersion: number;
}

export function ViewerCamera({ model, resetVersion }: ViewerCameraProps) {
  const { camera, gl, invalidate } = useThree();
  const controlsRef = useRef<OrbitControls | null>(null);

  useEffect(() => {
    const controls = new OrbitControls(camera, gl.domElement);
    const handleChange = () => invalidate();
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;
    controls.addEventListener("change", handleChange);
    controlsRef.current = controls;

    return () => {
      controls.removeEventListener("change", handleChange);
      controls.dispose();
      controlsRef.current = null;
    };
  }, [camera, gl, invalidate]);

  useEffect(() => {
    const controls = controlsRef.current;
    if (controls === null || !(camera instanceof PerspectiveCamera)) {
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
    const viewDirection = new Vector3(1, 0.75, 1).normalize();

    camera.position.copy(sphere.center).addScaledVector(viewDirection, distance);
    camera.near = Math.max(distance / 100, 0.1);
    camera.far = Math.max(distance * 100, 1_000);
    camera.updateProjectionMatrix();

    controls.target.copy(sphere.center);
    controls.minDistance = Math.max(sphere.radius * 0.25, 1);
    controls.maxDistance = Math.max(sphere.radius * 12, distance * 2);
    controls.update();
    invalidate();
  }, [camera, invalidate, model, resetVersion]);

  useFrame(() => {
    controlsRef.current?.update();
  });

  return null;
}
