import { useMemo } from "react";

import { LDrawAttribution, LDrawViewer, officialModelSource } from "./LDrawViewer";

interface OfficialPartViewerProps {
  partId: string;
  name: string;
  assetUrl: string;
}

export default function OfficialPartViewer({
  partId,
  name,
  assetUrl,
}: OfficialPartViewerProps) {
  const source = useMemo(
    () => officialModelSource(partId, assetUrl),
    [assetUrl, partId],
  );
  return (
    <>
      <LDrawViewer source={source} eyebrow={`Official part ${partId}`} title={name} />
      <LDrawAttribution />
    </>
  );
}
