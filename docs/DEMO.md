# Bricky portfolio demo

This script is designed for a 3–5 minute local demonstration.

1. **Local architecture — 30 seconds**
   - Open the overview at `http://127.0.0.1:8080` in production-like mode.
   - Point out that only Nginx is published; API and PostgreSQL are internal.
   - Show library/catalog status and the hidden single local workspace.

2. **Catalog and 3D rendering — 45 seconds**
   - Search the catalog for `3001`.
   - Open the official part and rotate the lazy-loaded Three.js viewer.
   - Mention explicit offline LDraw installation and transactional indexing.

3. **Immutable model import — 60 seconds**
   - Import a small deterministic MPD.
   - Show source SHA-256, recursive BOM, authored step navigation, and diagnostics.
   - Explain that source bytes stay unchanged while validated `Moved to` aliases canonicalize only derived BOM rows.

4. **Inventory and readiness — 60 seconds**
   - Open build readiness and the missing-parts view.
   - Add the exact required part/color quantity.
   - Show coverage and wishlist update immediately without reimport or reservation.
   - Add a wrong color briefly to demonstrate that it does not count.

5. **Operational reliability — 45 seconds**
   - Run `./scripts/backup.sh --prod`.
   - Show the timestamped archive validation output and explain that `.env` and the reinstallable LDraw library are excluded.
   - Mention tested restore safeguards: recognized format, checksums, path safety, and explicit `--force`.

6. **Close — 20 seconds**
   - Highlight strict TypeScript, deterministic Pytest/Vitest coverage, multi-stage production images, natural-ID isolation, and zero SaaS/runtime dependencies.
   - Delete any temporary model and inventory entries created for the demo.
