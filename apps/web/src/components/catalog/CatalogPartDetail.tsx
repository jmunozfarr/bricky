import { lazy, Suspense, useEffect, useState } from "react";

import { getPart, PartDetail } from "../../api/catalog";
import { InventoryEditor } from "../inventory/InventoryEditor";

const OfficialPartViewer = lazy(() => import("../ldraw/OfficialPartViewer"));

interface CatalogPartDetailProps {
  partId: string;
  onBack: () => void;
  backLabel?: string;
}

type DetailState =
  | { kind: "loading" }
  | { kind: "ready"; data: PartDetail }
  | { kind: "error"; message: string };

export function CatalogPartDetail({
  partId,
  onBack,
  backLabel = "Back to results",
}: CatalogPartDetailProps) {
  const [detail, setDetail] = useState<DetailState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    void getPart(partId, controller.signal)
      .then((data) => setDetail({ kind: "ready", data }))
      .catch((caught: unknown) => {
        if (!(caught instanceof DOMException && caught.name === "AbortError")) {
          setDetail({
            kind: "error",
            message: caught instanceof Error ? caught.message : "Unable to load part",
          });
        }
      });
    return () => controller.abort();
  }, [partId]);

  if (detail.kind === "loading") return <div className="page-message">Loading part…</div>;
  if (detail.kind === "error") {
    return <div className="error" role="alert"><strong>Part request failed.</strong><span>{detail.message}</span></div>;
  }

  return (
    <section className="part-inspector">
      <button type="button" className="back-button" onClick={onBack}>
        ← {backLabel}
      </button>
      <dl className="part-metadata">
        <div><dt>Part ID</dt><dd>{detail.data.partId}</dd></div>
        <div><dt>Category</dt><dd>{detail.data.category}</dd></div>
        <div><dt>Author</dt><dd>{detail.data.author ?? "Unknown"}</dd></div>
        <div><dt>Classification</dt><dd>{detail.data.orgClassification ?? "Not specified"}</dd></div>
        <div><dt>License</dt><dd>{detail.data.license ?? "See upstream file"}</dd></div>
      </dl>
      <InventoryEditor partId={detail.data.partId} />
      <Suspense fallback={<div className="page-message">Loading 3D viewer…</div>}>
        <OfficialPartViewer
          partId={detail.data.partId}
          name={detail.data.name}
          assetUrl={detail.data.renderAssetUrl}
        />
      </Suspense>
    </section>
  );
}
