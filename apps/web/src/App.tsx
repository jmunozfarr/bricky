import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";

import { useDocumentTitle } from "./app/pageTitle";
import { ThemePreference, useThemePreference } from "./theme/theme";

const OverviewPage = lazy(() => import("./pages/OverviewPage"));
const CatalogPage = lazy(() => import("./pages/CatalogPage"));
const InventoryPage = lazy(() => import("./pages/InventoryPage"));
const ViewerDemoPage = lazy(() => import("./pages/ViewerDemoPage"));
const ModelsPage = lazy(() => import("./pages/ModelsPage"));
const ModelDetailPage = lazy(() => import("./pages/ModelDetailPage"));
const VisualBuilderPage = lazy(() => import("./pages/VisualBuilderPage"));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage"));

function TitledRoute({ title, children }: { title: string; children: ReactNode }) {
  useDocumentTitle(title);
  return children;
}

export function App() {
  const theme = useThemePreference();

  return (
    <BrowserRouter>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <div className="app-shell">
        <header className="app-header">
          <NavLink className="brand" to="/" aria-label="Bricky overview">
            <img src="/favicon.svg" alt="" width="52" height="52" />
            <span>
              <strong>Bricky</strong>
              <small>Local LEGO workspace</small>
            </span>
          </NavLink>
          <nav className="primary-nav" aria-label="Primary navigation">
            <NavLink to="/" end>
              Overview
            </NavLink>
            <NavLink to="/catalog">Catalog</NavLink>
            <NavLink to="/inventory">Inventory</NavLink>
            <NavLink to="/models">Models</NavLink>
            <NavLink to="/viewer-demo">Viewer demo</NavLink>
          </nav>
          <label className="theme-control">
            <span>Theme</span>
            <select
              value={theme.preference}
              onChange={(event) =>
                theme.setPreference(event.currentTarget.value as ThemePreference)
              }
            >
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
        </header>

        <main id="main-content" tabIndex={-1}>
          <h1 className="sr-only">Bricky local LEGO workspace</h1>
          <Suspense
            fallback={
              <div className="page-message" role="status" aria-live="polite">
                Loading page…
              </div>
            }
          >
            <Routes>
              <Route
                path="/"
                element={
                  <TitledRoute title="Overview">
                    <OverviewPage />
                  </TitledRoute>
                }
              />
              <Route
                path="/catalog"
                element={
                  <TitledRoute title="Catalog">
                    <CatalogPage />
                  </TitledRoute>
                }
              />
              <Route
                path="/inventory"
                element={
                  <TitledRoute title="Inventory">
                    <InventoryPage />
                  </TitledRoute>
                }
              />
              <Route
                path="/models"
                element={
                  <TitledRoute title="Models">
                    <ModelsPage />
                  </TitledRoute>
                }
              />
              <Route
                path="/models/:modelId"
                element={
                  <TitledRoute title="Model details">
                    <ModelDetailPage />
                  </TitledRoute>
                }
              />
              <Route
                path="/models/:modelId/build"
                element={
                  <TitledRoute title="Visual builder">
                    <VisualBuilderPage />
                  </TitledRoute>
                }
              />
              <Route
                path="/viewer-demo"
                element={
                  <TitledRoute title="Viewer demo">
                    <ViewerDemoPage />
                  </TitledRoute>
                }
              />
              <Route
                path="*"
                element={
                  <TitledRoute title="Page not found">
                    <NotFoundPage />
                  </TitledRoute>
                }
              />
            </Routes>
          </Suspense>
        </main>
      </div>
    </BrowserRouter>
  );
}
