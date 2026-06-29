import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";

import { useDocumentTitle } from "./app/pageTitle";

const OverviewPage = lazy(() => import("./pages/OverviewPage"));
const CatalogPage = lazy(() => import("./pages/CatalogPage"));
const InventoryPage = lazy(() => import("./pages/InventoryPage"));
const ViewerDemoPage = lazy(() => import("./pages/ViewerDemoPage"));
const ModelsPage = lazy(() => import("./pages/ModelsPage"));
const ModelDetailPage = lazy(() => import("./pages/ModelDetailPage"));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage"));

function TitledRoute({ title, children }: { title: string; children: ReactNode }) {
  useDocumentTitle(title);
  return children;
}

export function App() {
  return (
    <BrowserRouter>
      <a className="skip-link" href="#main-content">Skip to main content</a>
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
            <NavLink to="/" end>Overview</NavLink>
            <NavLink to="/catalog">Catalog</NavLink>
            <NavLink to="/inventory">Inventory</NavLink>
            <NavLink to="/models">Models</NavLink>
            <NavLink to="/viewer-demo">Viewer demo</NavLink>
          </nav>
        </header>

        <main id="main-content" tabIndex={-1}>
          <Suspense fallback={<div className="page-message" role="status" aria-live="polite">Loading page…</div>}>
            <Routes>
              <Route path="/" element={<TitledRoute title="Overview"><OverviewPage /></TitledRoute>} />
              <Route path="/catalog" element={<TitledRoute title="Catalog"><CatalogPage /></TitledRoute>} />
              <Route path="/inventory" element={<TitledRoute title="Inventory"><InventoryPage /></TitledRoute>} />
              <Route path="/models" element={<TitledRoute title="Models"><ModelsPage /></TitledRoute>} />
              <Route path="/models/:modelId" element={<TitledRoute title="Model details"><ModelDetailPage /></TitledRoute>} />
              <Route path="/viewer-demo" element={<TitledRoute title="Viewer demo"><ViewerDemoPage /></TitledRoute>} />
              <Route path="*" element={<TitledRoute title="Page not found"><NotFoundPage /></TitledRoute>} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </BrowserRouter>
  );
}
