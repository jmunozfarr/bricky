# Bricky

Bricky is a deliberately small, local application. It runs a React, TypeScript, and Vite frontend, a Python 3.13 FastAPI backend, and PostgreSQL 18. Docker and Docker Compose are the only host requirements; do not install project runtimes or dependencies directly on the host.

Checkpoint 2 adds a browser-side LDraw viewer spike. Three.js `LDrawLoader` parses a local model, React Three Fiber renders it, and the interface provides orbit controls, camera reset, and building-step navigation. Checkpoint 3 adds an explicit local bootstrap for the official LDraw Parts Library, safe API file serving, and rendering of the official `3001.dat` brick.

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

## LDraw attribution and licensing

This software uses the [LDraw Parts Library](https://www.ldraw.org/). LDraw is a community-run project and is not sponsored, endorsed, or authorized by the LEGO Group. Bricky is not affiliated with LDraw.org or the LEGO Group.

Library files retain their original headers, author credits, `CAreadme.txt`, and other upstream notices. Applicable licenses are identified per upstream file and contributor agreement, including CC BY 2.0, CC BY 4.0, and CC0 content. See the [LDraw legal information](https://www.ldraw.org/legal-info) and the legal files included with the installed archive for the authoritative terms.

## Local URLs

- Frontend: <http://127.0.0.1:5173>
- API health: <http://127.0.0.1:8000/api/health>
- Proxied API health: <http://127.0.0.1:5173/api/health>

PostgreSQL is accessible only to other Compose services and is not published to the host. A healthy API response is `{"status":"ok","database":"ok"}` and is backed by a real `SELECT 1` query.
