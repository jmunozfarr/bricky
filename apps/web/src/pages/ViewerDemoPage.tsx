import {
  LDrawAttribution,
  LDrawViewer,
  SYNTHETIC_MODEL_SOURCE,
} from "../components/ldraw/LDrawViewer";

export default function ViewerDemoPage() {
  return (
    <>
      <LDrawViewer
        source={SYNTHETIC_MODEL_SOURCE}
        eyebrow="Synthetic fixture"
        title="Building-step demo"
      />
      <LDrawAttribution />
    </>
  );
}
