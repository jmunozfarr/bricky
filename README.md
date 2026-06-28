# Bricky

Bricky Checkpoint 1 is a deliberately small, local application skeleton. It runs a React, TypeScript, and Vite frontend, a Python 3.13 FastAPI backend, and PostgreSQL 18. Docker and Docker Compose are the only host requirements; do not install project runtimes or dependencies directly on the host.

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

## Local URLs

- Frontend: <http://127.0.0.1:5173>
- API health: <http://127.0.0.1:8000/api/health>
- Proxied API health: <http://127.0.0.1:5173/api/health>

PostgreSQL is accessible only to other Compose services and is not published to the host. A healthy API response is `{"status":"ok","database":"ok"}` and is backed by a real `SELECT 1` query.
