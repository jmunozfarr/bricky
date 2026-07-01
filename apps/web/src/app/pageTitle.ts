import { useEffect } from "react";

export const APPLICATION_NAME = "Bricky";

export function formatPageTitle(pageTitle: string): string {
  const normalized = pageTitle.trim();
  return normalized ? `${normalized} · ${APPLICATION_NAME}` : APPLICATION_NAME;
}

export function useDocumentTitle(pageTitle: string): void {
  useEffect(() => {
    document.title = formatPageTitle(pageTitle);
  }, [pageTitle]);
}
