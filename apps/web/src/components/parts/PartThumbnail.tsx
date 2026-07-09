import { useState } from "react";

/**
 * Pre-rendered part image from the derived thumbnails directory
 * (scripts/render-thumbnails.sh). Purely decorative next to the textual
 * part identity, and collapses to a neutral tile when no thumbnail exists.
 */
export function PartThumbnail({ partId, className }: { partId: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  const classes = ["part-thumbnail", className].filter(Boolean).join(" ");
  if (failed) return <span className={`${classes} part-thumbnail--empty`} aria-hidden="true" />;
  return (
    <img
      className={classes}
      src={`/api/thumbnails/${encodeURIComponent(partId.trim().toLowerCase())}.png`}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
