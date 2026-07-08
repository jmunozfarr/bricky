import { RefObject, useEffect, useState } from "react";

export type CameraPreset = "isometric" | "front" | "right" | "top";
export type CameraCommand =
  | { id: number; kind: "fit"; preset: CameraPreset }
  | { id: number; kind: "zoom"; direction: "in" | "out" };
export type CameraCommandInput =
  { kind: "fit"; preset: CameraPreset } | { kind: "zoom"; direction: "in" | "out" };

interface ViewerToolbarProps {
  containerRef: RefObject<HTMLElement | null>;
  onCameraCommand: (command: CameraCommandInput) => void;
}

export function ViewerToolbar({ containerRef, onCameraCommand }: ViewerToolbarProps) {
  const [fullscreen, setFullscreen] = useState(false);
  const fullscreenAvailable = typeof document !== "undefined" && document.fullscreenEnabled;

  useEffect(() => {
    const update = () => setFullscreen(document.fullscreenElement === containerRef.current);
    document.addEventListener("fullscreenchange", update);
    return () => document.removeEventListener("fullscreenchange", update);
  }, [containerRef]);

  async function toggleFullscreen(): Promise<void> {
    if (!fullscreenAvailable) return;
    if (document.fullscreenElement === containerRef.current) {
      await document.exitFullscreen();
    } else {
      await containerRef.current?.requestFullscreen();
    }
  }

  return (
    <div className="viewer-toolbar" role="toolbar" aria-label="3D view controls">
      <div className="viewer-preset-actions" aria-label="Camera view preset">
        <button type="button" onClick={() => onCameraCommand({ kind: "fit", preset: "isometric" })}>
          Isometric
        </button>
        <button type="button" onClick={() => onCameraCommand({ kind: "fit", preset: "front" })}>
          Front
        </button>
        <button type="button" onClick={() => onCameraCommand({ kind: "fit", preset: "right" })}>
          Right
        </button>
        <button type="button" onClick={() => onCameraCommand({ kind: "fit", preset: "top" })}>
          Top
        </button>
      </div>
      <div className="viewer-zoom-actions">
        <button
          type="button"
          aria-label="Zoom in"
          onClick={() => onCameraCommand({ kind: "zoom", direction: "in" })}
        >
          +
        </button>
        <button
          type="button"
          aria-label="Zoom out"
          onClick={() => onCameraCommand({ kind: "zoom", direction: "out" })}
        >
          −
        </button>
        <button
          type="button"
          disabled={!fullscreenAvailable}
          aria-pressed={fullscreen}
          onClick={() => void toggleFullscreen()}
        >
          {fullscreen ? "Exit fullscreen" : "Fullscreen"}
        </button>
        <details className="viewer-shortcuts">
          <summary>Shortcuts</summary>
          <p>
            Left/Right steps · Home/End first/final · R reset · F fullscreen · H interface · 1–4
            views · +/− zoom
          </p>
        </details>
      </div>
    </div>
  );
}

export function isEditableShortcutTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      target instanceof HTMLInputElement ||
      target instanceof HTMLSelectElement ||
      target instanceof HTMLTextAreaElement)
  );
}
