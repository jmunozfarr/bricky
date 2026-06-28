# Repository Guidelines

## Scope and Architecture

Bricky is a local Docker Compose application. `apps/web/` contains the React, TypeScript, and Vite frontend; `apps/api/` contains the Python 3.13 and FastAPI backend. PostgreSQL is the source of truth for persisted data. Keep code within the service that owns it, and do not implement features outside the explicitly requested checkpoint.

Preserve imported source files exactly as received. If imported data needs normalization, create a derived file or transformation step instead of modifying the source.

## Development Commands

Run everything through Docker Compose. Never install Node.js, npm, Python, pip, or project dependencies on the host.

- `docker compose up --build`: build and start the complete development stack.
- `docker compose down`: stop containers while preserving named volumes.
- `docker compose logs -f api web db`: inspect service output.
- `docker compose down --volumes`: remove containers and local persistent data.

Copy `.env.example` to `.env` before running commands. Do not add SaaS dependencies or third-party runtime services; the application must remain locally runnable.

## Coding Style and Testing

Use English for source code, documentation, comments, identifiers, and commit messages. TypeScript must remain strict and avoid `any`; Python code must use type annotations. Follow the configured tools and established language conventions. Use `PascalCase` for React components, `camelCase` for TypeScript values, and `snake_case` for Python modules and functions.

Add tests when changing critical logic, particularly persistence, validation, and service integration. Keep tests deterministic and run them inside Compose containers. Maintain lockfiles and exact or otherwise reproducible dependency versions whenever dependencies change.

## Commits and Pull Requests

Use short, imperative commit subjects such as `feat: add health status` or `fix: handle database timeout`. Keep commits scoped and do not mix unrelated refactors. Pull requests should describe the change, list Compose-based validation commands, link relevant issues, and include screenshots for interface changes. Never commit `.env`, credentials, generated builds, caches, or local data.
