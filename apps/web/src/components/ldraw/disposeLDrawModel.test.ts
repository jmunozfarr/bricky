import { BufferGeometry, Group, Mesh, MeshStandardMaterial, Texture } from "three";
import { describe, expect, it, vi } from "vitest";

import { disposeLDrawModel } from "./LDrawModel";

describe("disposeLDrawModel", () => {
  it("disposes geometries, materials, and their textures (A3)", () => {
    const model = new Group();
    const geometry = new BufferGeometry();
    const texture = new Texture();
    const material = new MeshStandardMaterial({ map: texture });
    model.add(new Mesh(geometry, material));

    const geometryDispose = vi.spyOn(geometry, "dispose");
    const materialDispose = vi.spyOn(material, "dispose");
    const textureDispose = vi.spyOn(texture, "dispose");

    disposeLDrawModel(model);

    expect(geometryDispose).toHaveBeenCalledTimes(1);
    expect(materialDispose).toHaveBeenCalledTimes(1);
    expect(textureDispose).toHaveBeenCalledTimes(1);
  });

  it("disposes each shared geometry and material exactly once", () => {
    const model = new Group();
    const geometry = new BufferGeometry();
    const material = new MeshStandardMaterial();
    model.add(new Mesh(geometry, material), new Mesh(geometry, material));

    const geometryDispose = vi.spyOn(geometry, "dispose");
    const materialDispose = vi.spyOn(material, "dispose");

    disposeLDrawModel(model);

    expect(geometryDispose).toHaveBeenCalledTimes(1);
    expect(materialDispose).toHaveBeenCalledTimes(1);
  });
});
