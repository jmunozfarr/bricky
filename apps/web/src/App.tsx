import { lazy, Suspense } from "react";
import {
  BrowserRouter,
  NavLink,
  Navigate,
  Route,
  Routes,
} from "react-router-dom";

const OverviewPage = lazy(() => import("./pages/OverviewPage"));
const CatalogPage = lazy(() => import("./pages/CatalogPage"));
const ViewerDemoPage = lazy(() => import("./pages/ViewerDemoPage"));

export function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <header className="app-header">
          <div>
            <h1>Bricky</h1>
            <p className="subtitle">Local LEGO workspace</p>
          </div>
          <nav className="primary-nav" aria-label="Primary navigation">
            <NavLink to="/" end>
              Overview
            </NavLink>
            <NavLink to="/catalog">Catalog</NavLink>
            <NavLink to="/viewer-demo">Viewer demo</NavLink>
          </nav>
        </header>

        <main>
          <Suspense fallback={<div className="page-message">Loading page…</div>}>
            <Routes>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/catalog" element={<CatalogPage />} />
              <Route path="/viewer-demo" element={<ViewerDemoPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </BrowserRouter>
  );
}
