import { lazy, Suspense, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { deleteModel, getModel, ModelDetail } from "../api/models";
import { filterModelBom, modelStatusLabel } from "../models/helpers";

const ImportedModelViewer = lazy(() => import("../components/ldraw/ImportedModelViewer"));

type DetailState =
  | { kind: "loading" }
  | { kind: "ready"; data: ModelDetail }
  | { kind: "error"; message: string };

export default function ModelDetailPage() {
  const { modelId = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [state, setState] = useState<DetailState>({ kind: "loading" });
  const [bomQuery, setBomQuery] = useState("");
  const [deleting, setDeleting] = useState(false);
  const returnTarget = `/models${params.get("return") ? `?${params.get("return")}` : ""}`;

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    void getModel(modelId, controller.signal)
      .then((data) => setState({ kind: "ready", data }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setState({ kind: "error", message: error instanceof Error ? error.message : "Unable to load model." });
        }
      });
    return () => controller.abort();
  }, [modelId]);

  async function remove() {
    if (!window.confirm("Delete this imported model and its preserved source file?")) return;
    setDeleting(true);
    try {
      await deleteModel(modelId);
      navigate(returnTarget);
    } catch (error: unknown) {
      setState({ kind: "error", message: error instanceof Error ? error.message : "Delete failed." });
      setDeleting(false);
    }
  }

  if (state.kind === "loading") return <div className="page-message">Loading model…</div>;
  if (state.kind === "error") return <div className="error" role="alert"><strong>Model request failed.</strong><span>{state.message}</span></div>;
  const model = state.data;
  const bom = filterModelBom(model.bom, bomQuery);

  return <div className="model-detail">
    <div className="detail-actions"><Link className="button-link" to={returnTarget}>Back to models</Link><button className="danger-button" disabled={deleting} onClick={() => void remove()}>{deleting ? "Deleting…" : "Delete model"}</button></div>
    <section className="page-panel">
      <div className="page-heading catalog-heading"><div><p className="eyebrow">Imported {model.sourceFormat.toUpperCase()}</p><h2>{model.name}</h2></div><span className={`model-status model-status--${model.importStatus}`}>{modelStatusLabel(model.importStatus)}</span></div>
      <dl className="part-metadata"><Meta label="Original filename" value={model.originalFilename} /><Meta label="Top-level source steps" value={model.declaredStepCount} /><Meta label="Physical parts" value={model.totalPartQuantity} /><Meta label="Part/color variants" value={model.uniquePartColorCount} /><Meta label="Unresolved references" value={model.unresolvedReferenceCount} /><Meta label="Source SHA-256" value={model.sourceSha256} /></dl>
    </section>
    <Suspense fallback={<div className="page-message">Loading 3D viewer…</div>}><ImportedModelViewer modelId={model.modelId} sourceUrl={model.sourceUrl} title={model.name} /></Suspense>
    <section className="page-panel">
      <div className="page-heading catalog-heading"><div><p className="eyebrow">Bill of materials</p><h2>Physical parts</h2></div><p>{model.totalPartQuantity} total</p></div>
      <label className="bom-search"><span>Search BOM</span><input type="search" value={bomQuery} onChange={(event) => setBomQuery(event.currentTarget.value)} placeholder="Part, name, or color" /></label>
      {bom.length === 0 ? <div className="empty-state">No BOM items match this search.</div> : <div className="table-scroll"><table className="bom-table"><thead><tr><th>Part</th><th>Name</th><th>Color</th><th>Quantity</th><th>Catalog</th></tr></thead><tbody>{bom.map((item) => <tr key={`${item.partId}-${item.colorCode}`}><td><span className="part-id">{item.partId}</span></td><td>{item.partName}</td><td><span className="inventory-color">{item.colorHex && <span className="color-swatch" style={{ backgroundColor: item.colorHex }} />}{item.colorName} ({item.colorCode})</span></td><td>{item.quantity}</td><td>{item.catalogAvailable ? <Link to={`/catalog?part=${encodeURIComponent(item.partId)}`}>Inspect official part</Link> : "Unavailable"}</td></tr>)}</tbody></table></div>}
    </section>
    {model.issues.length > 0 && <section className="page-panel"><div className="page-heading"><p className="eyebrow">Import diagnostics</p><h2>Warnings</h2></div><ul className="issue-list">{model.issues.map((issue, index) => <li key={`${issue.code}-${index}`}><strong>{issue.code.replaceAll("_", " ")}</strong><span>{issue.message}{issue.referencedFilename ? ` — ${issue.referencedFilename}` : ""}</span></li>)}</ul></section>}
  </div>;
}

function Meta({ label, value }: { label: string; value: string | number }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}
