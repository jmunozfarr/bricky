// @vitest-environment jsdom

import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { isEditableShortcutTarget, ViewerToolbar } from "./ViewerToolbar";

describe("viewer toolbar", () => {
  it("emits camera preset and zoom commands", () => {
    const onCameraCommand = vi.fn();
    render(
      <ViewerToolbar
        containerRef={createRef<HTMLElement>()}
        onCameraCommand={onCameraCommand}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Front" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));

    expect(onCameraCommand).toHaveBeenNthCalledWith(1, {
      kind: "fit",
      preset: "front",
    });
    expect(onCameraCommand).toHaveBeenNthCalledWith(2, {
      kind: "zoom",
      direction: "in",
    });
  });

  it("does not treat shortcuts typed into fields as viewer commands", () => {
    expect(isEditableShortcutTarget(document.createElement("input"))).toBe(true);
    expect(isEditableShortcutTarget(document.createElement("select"))).toBe(true);
    expect(isEditableShortcutTarget(document.createElement("button"))).toBe(false);
  });
});
