import { importedModelSource, LDrawAttribution, LDrawViewer } from "./LDrawViewer";

export default function ImportedModelViewer({ modelId, sourceUrl, title }: { modelId: string; sourceUrl: string; title: string }) {
  return <><LDrawViewer source={importedModelSource(modelId, sourceUrl)} eyebrow="Imported source" title={title} /><LDrawAttribution /></>;
}
