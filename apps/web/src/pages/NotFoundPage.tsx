import { Link, useLocation } from "react-router-dom";

export default function NotFoundPage() {
  const location = useLocation();
  return (
    <section className="page-panel not-found" aria-labelledby="not-found-title">
      <p className="eyebrow">404 · Page not found</p>
      <h2 id="not-found-title">That workspace route does not exist.</h2>
      <p>
        Bricky could not find <code>{location.pathname}</code>. No data was changed.
      </p>
      <Link className="button-link" to="/">
        Return to overview
      </Link>
    </section>
  );
}
