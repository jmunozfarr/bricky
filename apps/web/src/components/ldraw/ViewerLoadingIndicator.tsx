interface ViewerLoadingIndicatorProps {
  title: string;
  detail?: string;
}

/**
 * Loading state for the 3D viewers: a row of studded bricks being placed one
 * by one. Purely decorative — the text carries the status for assistive
 * technology, and the animation collapses to a static row under
 * prefers-reduced-motion.
 */
export function ViewerLoadingIndicator({ title, detail }: ViewerLoadingIndicatorProps) {
  return (
    <div className="viewer-message viewer-loading" role="status">
      <span className="viewer-loading-bricks" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
        <span />
      </span>
      <strong>{title}</strong>
      {detail !== undefined && <span>{detail}</span>}
    </div>
  );
}
