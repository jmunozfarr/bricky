# Bricky

Bricky is a deliberately small, local application. It runs a React, TypeScript, and Vite frontend, a Python 3.13 FastAPI backend, and PostgreSQL 18. Docker and Docker Compose are the only host requirements; do not install project runtimes or dependencies directly on the host.

Checkpoint 2 adds a browser-side LDraw viewer spike. Three.js `LDrawLoader` parses a local model, React Three Fiber renders it, and the interface provides orbit controls, camera reset, and building-step navigation.

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

## LDraw test fixture

The viewer loads [`apps/web/public/models/demo-steps.ldr`](apps/web/public/models/demo-steps.ldr). This small, synthetic MPD fixture contains three embedded, colored geometry stages and requires no external part files. It is a test asset, not an official LEGO model.

The official LDraw parts library is not installed yet. Consequently, the viewer currently supports only the bundled self-contained fixture; ordinary LDraw models that reference library parts are outside this checkpoint.

## Local URLs

- Frontend: <http://127.0.0.1:5173>
- API health: <http://127.0.0.1:8000/api/health>
- Proxied API health: <http://127.0.0.1:5173/api/health>

PostgreSQL is accessible only to other Compose services and is not published to the host. A healthy API response is `{"status":"ok","database":"ok"}` and is backed by a real `SELECT 1` query.
