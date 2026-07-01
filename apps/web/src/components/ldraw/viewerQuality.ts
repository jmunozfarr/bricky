export function maximumViewerDpr(
  viewportWidth: number,
  devicePixelRatio: number,
): number {
  const deviceMaximum = viewportWidth <= 896 ? 1.5 : 2;
  return Math.max(1, Math.min(deviceMaximum, devicePixelRatio));
}
