# Bricky

Bricky is a deliberately small, local application. It runs a React, TypeScript, and Vite frontend, a Python 3.13 FastAPI backend, and PostgreSQL 18. Docker and Docker Compose are the only host requirements; do not install project runtimes or dependencies directly on the host.

Checkpoint 2 adds browser-side LDraw rendering and building-step navigation. Checkpoint 3 adds the official LDraw Parts Library. Checkpoint 4 adds the PostgreSQL catalog index and search UI. Checkpoint 5 adds persistent quantities for one hidden, no-login local workspace. Checkpoint 6 adds local LDR/MPD import, recursive bill-of-materials parsing, and model viewing. Checkpoint 7 adds live inventory coverage, build readiness, and a derived missing-parts wishlist for each imported model. Library installation and catalog indexing remain explicit operations.

## Requirements

- Docker Engine with Docker Compose support
- Available loopback ports `5173` and `8000`

No SaaS products or external runtime services are required.

## Environment setup

Create the local environment file from the safe development template:

```sh
cp .env.example .env
```

The template configures the PostgreSQL database, user, and development password. Change these values locally if needed. Do not commit `.env`.

On Linux, the API container runs with `LOCAL_UID` and `LOCAL_GID` so files written through the `data/models` bind mount belong to the host developer rather than root. The template defaults both values to `1000`. If your account uses different IDs, obtain them and either export them before Compose commands or place the numeric results in `.env`:

```sh
export LOCAL_UID="$(id -u)"
export LOCAL_GID="$(id -g)"
```

After upgrading an existing checkout, repair previously imported model ownership once without deleting any models:

```sh
docker compose run --rm --no-deps --user root api \
  sh -c 'chown -R "$LOCAL_UID:$LOCAL_GID" /data/models'
```

This command changes ownership only; it does not make the directory world-writable or modify model contents. The PostgreSQL container continues to use its image-defined user.

## Run locally

Build and start every service:

```sh
docker compose up --build -d
```

Useful lifecycle commands:

```sh
docker compose logs -f api web db  # Follow service logs
docker compose down                # Stop and preserve database data
docker compose down --volumes      # Stop and remove all named volumes
```

Re-run `docker compose up --build -d` after changing dependency files or Dockerfiles. Source changes reload automatically through bind mounts.

For a new checkout, use this complete setup sequence:

```sh
cp .env.example .env
docker compose up --build -d
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.cli.ldraw_library install
docker compose exec api python -m app.cli.ldraw_catalog rebuild
```

## Frontend checks

Run all frontend checks inside the existing Compose service:

```sh
docker compose exec -T web npm run typecheck
docker compose exec -T web npm test
docker compose exec -T web npm run build
```

Run API tests inside the API service:

```sh
docker compose exec -T api pytest -q
```

## LDraw test fixture

The viewer loads [`apps/web/public/models/demo-steps.ldr`](apps/web/public/models/demo-steps.ldr). This small, synthetic MPD fixture contains three embedded, colored geometry stages and requires no external part files. It is a test asset, not an official LEGO model.

## Official LDraw Parts Library

The official library is intentionally absent from Git and Docker images. It is large, changes independently from Bricky, and contains upstream attribution and license files that must remain unmodified. Bricky never downloads or updates it during normal application startup.

Install it once from the repository root:

```sh
docker compose run --rm api python -m app.cli.ldraw_library install
```

The command streams the official `complete.zip`, verifies its SHA-256, validates and safely extracts it, then atomically installs it. `LDRAW_LIBRARY_URL` in `.env` can override the download URL. An existing archive mounted under `data/ldraw` can be used without network access:

```sh
docker compose run --rm api python -m app.cli.ldraw_library install --archive /data/ldraw/complete.zip
```

Inspect installation status and recorded metadata:

```sh
docker compose run --rm api python -m app.cli.ldraw_library status
```

Files are stored at `data/ldraw/official` on the host and mounted at `/data/ldraw/official` in the API container. The Bricky manifest is stored beside that directory. After installation, runtime rendering and API operation are offline and no automatic updates occur.

To reinstall atomically, rerun the install command with `--force`. To remove the local copy entirely:

```sh
docker compose run --rm api sh -c 'rm -rf /data/ldraw/official /data/ldraw/official.manifest.json'
```

Deleting `data/ldraw` removes the local library. Keep `data/ldraw/.gitkeep` when cleaning the directory.

The API exposes installation metadata at `/api/library/status` and serves only installed library files below `/api/ldraw/`.

## Parts catalog index

Apply database migrations explicitly after starting the stack:

```sh
docker compose run --rm api alembic upgrade head
```

Installing files does not index them. Build or replace the PostgreSQL catalog with:

```sh
docker compose exec api python -m app.cli.ldraw_catalog rebuild
```

Inspect the installed and indexed fingerprints, counts, timestamp, and stale state:

```sh
docker compose exec api python -m app.cli.ldraw_catalog status
```

The index stores only searchable metadata, colors, relative asset paths, and one fingerprint record—never geometry or absolute filesystem paths. Replacing the official library changes its archive SHA-256. The API compares that installed fingerprint with the indexed fingerprint and marks the catalog stale until `rebuild` is run again.

After replacing or force-reinstalling the library, rerun the catalog rebuild command. Rebuilds parse headers without modifying upstream files and replace catalog data in one database transaction. Indexing never runs automatically during API startup or from the browser.

## Personal inventory

Bricky resolves one deterministic internal workspace named `Local workspace` (`local-default`). There is no login, user identity, onboarding flow, or workspace picker. Every inventory request is scoped to this workspace by the API; browser requests cannot select a workspace ID.

Inventory is stored in PostgreSQL rather than browser storage so quantities have one durable source of truth shared by the overview, catalog detail, and inventory screens. Browser local storage is not the source of truth.

Apply the latest migration, including the workspace and inventory tables, with:

```sh
docker compose run --rm api alembic upgrade head
```

The inventory API provides:

- `GET /api/inventory/summary`
- `GET /api/inventory/items` with search, category, color, and pagination filters
- `GET /api/inventory/items/{part_id}` for owned color variants
- `PUT /api/inventory/items/{part_id}/{color_code}` to replace a quantity
- `DELETE /api/inventory/items/{part_id}/{color_code}` for idempotent removal

Inventory rows reference stable LDraw part IDs and color codes without destructive foreign keys to the rebuildable catalog tables. Writes validate against the current catalog, while reads preserve and display an inventory row even if catalog metadata temporarily disappears. Replacing or rebuilding the LDraw catalog does not intentionally delete personal inventory.

Deleting the PostgreSQL Docker volume deletes personal inventory permanently:

```sh
docker compose down --volumes
```

Current limitations: one local workspace, positive quantities only, no history, reserved quantities, storage locations, sets, wishlists, import/export, scanning, or offline synchronization.

## Imported LDraw models

The Models page at <http://127.0.0.1:5173/models> accepts `.ldr` and `.mpd` files up to 25 MiB by default. Configure the server limit with `MODEL_MAX_UPLOAD_BYTES`. Uploaded originals are stored below `data/models/originals`, mounted only into the API container, and preserved byte-for-byte. Storage paths are application-generated; neither paths nor workspace IDs are accepted from browser requests.

LDR is normally a single model file. MPD packages a main model and embedded submodels in one source, so MPD is recommended whenever a model depends on submodels. External sibling `.ldr` files and ZIP projects are not resolved in this checkpoint.

The importer recursively resolves embedded MPD submodels, multiplies repeated submodel quantities, applies LDraw color-16 inheritance, and records indexed official parts as physical BOM items. Official part geometry remains in the separately installed LDraw library and is not copied into PostgreSQL. Primitives, official subparts, geometry lines, and color 24 are not physical BOM entries. Unknown colors and unresolved references are retained as structured warnings where possible. The stored declared-step count describes separators in the top-level source; runtime Three.js step metadata controls interactive navigation.

Some official LDraw files are compatibility aliases whose description is `~Moved to <part-id>` and whose only geometry reference points to the canonical replacement. New imports validate both signals, follow moved-alias chains, and store the final canonical part ID in the derived BOM. References to an alias and its canonical replacement therefore merge when their physical color also matches. This is limited to authoritative official `Moved to` files; it is not general substitution, shortcut expansion, similar-part matching, or alternate-color matching. Alias failures retain the original BOM ID with a structured warning.

Canonicalization never changes the uploaded source bytes, original filename, or source SHA-256. Models imported before this behavior keep their existing derived BOM until they are explicitly deleted and reimported; Bricky does not rewrite existing models during startup.

Import statuses are:

- `ready`: parsed without warnings.
- `ready_with_warnings`: renderable/importable source with unresolved or non-fatal diagnostics.
- `failed`: reserved for a persisted fatal result; structurally unusable uploads are currently rejected with HTTP 422 and are not stored.

Model API endpoints are `POST /api/models`, paginated `GET /api/models`, `GET /api/models/{model_id}`, `GET /api/models/{model_id}/source`, and `DELETE /api/models/{model_id}`. Deleting a model removes its managed original, BOM, and issues, but never changes personal inventory or official library data. Duplicate source bytes in the local workspace return HTTP 409 with the existing model ID.

Deleting `data/models` removes imported source files and leaves any corresponding database metadata unable to render. Delete models through the UI or API to remove both metadata and managed files consistently. Current limitations include no editing, generated steps, `.io` files, sibling-file projects, custom-part inventory, or thumbnails.

## Model inventory coverage and missing parts

Each imported model is compared dynamically with the current `local-default` inventory. Matching uses the normalized LDraw part ID and exact numeric physical color code. A quantity owned in another color, or a similar or aliased part, does not count. Missing catalog names or color metadata do not stop an exact natural-key match.

Coverage distinguishes unique BOM rows from physical piece quantities. For each part/color row, available quantity is the smaller of required and owned quantity, and missing quantity never drops below zero. The primary readiness percentage is based on physical pieces: total available quantity divided by total required quantity. Percentages are rounded half-up to two decimal places. An empty BOM is treated as 100% covered and fully buildable.

The model detail page exposes all coverage rows and a “Missing parts” view. This wishlist is a query result derived from current BOM and inventory data; it is not stored in a separate table and cannot become stale independently. Inventory edits refresh readiness and remove completed rows from the missing-parts view without reimporting the model.

Inventory is not reserved or allocated between models. Every model is evaluated independently against the full current inventory, so totals across models are explicitly per-model comparisons and must not be interpreted as a globally buildable combination.

Coverage endpoints are:

- `GET /api/models/{model_id}/coverage`, optionally filtered with `status=complete|partial|missing` and `query=<part ID or name>`.
- `GET /api/models/readiness-summary` for bounded overview aggregation.
- `GET /api/models` includes a current coverage summary for each model on the requested page without frontend per-model requests.

Current coverage limitations include no substitutions, alternate-color matching, reservations, allocations, inventory consumption, multiple model copies, persisted or manually edited wishlists, prices, stores, or purchase links.

## LDraw attribution and licensing

This software uses the [LDraw Parts Library](https://www.ldraw.org/). LDraw is a community-run project and is not sponsored, endorsed, or authorized by the LEGO Group. Bricky is not affiliated with LDraw.org or the LEGO Group.

Library files retain their original headers, author credits, `CAreadme.txt`, and other upstream notices. Applicable licenses are identified per upstream file and contributor agreement, including CC BY 2.0, CC BY 4.0, and CC0 content. See the [LDraw legal information](https://www.ldraw.org/legal-info) and the legal files included with the installed archive for the authoritative terms.

## Local URLs

- Overview: <http://127.0.0.1:5173/>
- Searchable catalog: <http://127.0.0.1:5173/catalog>
- Personal inventory: <http://127.0.0.1:5173/inventory>
- Imported models: <http://127.0.0.1:5173/models>
- Synthetic step viewer: <http://127.0.0.1:5173/viewer-demo>
- API health: <http://127.0.0.1:8000/api/health>
- Proxied API health: <http://127.0.0.1:5173/api/health>

PostgreSQL is accessible only to other Compose services and is not published to the host. A healthy API response is `{"status":"ok","database":"ok"}` and is backed by a real `SELECT 1` query.

Catalog search is deterministic, case-insensitive substring matching without fuzzy-search extensions. Imported models preserve their source and derived BOM locally; editing, thumbnails, external sibling files, and automatic updates remain outside the current scope.
