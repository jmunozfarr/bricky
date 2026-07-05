import { createLDrawLoader, prepareOfficialLoader } from "./ldrawLoaderSetup";
import { serializeLDrawScene } from "./ldrawSceneTransfer";

/**
 * Parses LDraw source off the main thread. Each request uses a fresh loader
 * (matching the previous main-thread behavior, so per-model !COLOUR
 * definitions and part caches never leak between scenes) and answers with a
 * serialized scene graph whose geometry buffers are transferred, not copied.
 */

export interface LDrawParseRequest {
  id: number;
  /** "parse" for already-fetched text, "load" to let the loader fetch the URL. */
  mode: "parse" | "load";
  text?: string;
  url?: string;
  /** Absent for synthetic sources, which use the loader's default materials. */
  officialMaterials: { materialsUrl: string; partsLibraryPath: string } | null;
}

export type LDrawParseResponse =
  | { id: number; ok: true; root: ReturnType<typeof serializeLDrawScene>["root"] }
  | { id: number; ok: false; message: string };

const scope = self as unknown as {
  onmessage: ((event: MessageEvent<LDrawParseRequest>) => void) | null;
  postMessage(message: LDrawParseResponse, transfer?: Transferable[]): void;
};

async function handle(request: LDrawParseRequest): Promise<void> {
  try {
    const loader = createLDrawLoader();
    if (request.officialMaterials !== null) {
      await prepareOfficialLoader(
        loader,
        request.officialMaterials.materialsUrl,
        request.officialMaterials.partsLibraryPath,
      );
    } else {
      loader.addDefaultMaterials();
    }
    const model =
      request.mode === "load"
        ? await loader.loadAsync(request.url ?? "")
        : await new Promise<Awaited<ReturnType<typeof loader.loadAsync>>>((resolve, reject) => {
            loader.parse(request.text ?? "", resolve, reject);
          });
    const { root, buffers } = serializeLDrawScene(model);
    scope.postMessage({ id: request.id, ok: true, root }, buffers);
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Unknown LDraw parse error";
    scope.postMessage({ id: request.id, ok: false, message });
  }
}

scope.onmessage = (event: MessageEvent<LDrawParseRequest>) => {
  void handle(event.data);
};
