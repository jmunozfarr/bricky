import os
from pathlib import Path

import psycopg
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field
from starlette.staticfiles import StaticFiles

from app.services.ldraw_library import get_library_status


class HealthResponse(BaseModel):
    status: str
    database: str


class LibraryFileCountsResponse(BaseModel):
    dat: int
    ldr: int
    png: int


class LibraryStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    installed: bool
    file_counts: LibraryFileCountsResponse | None = Field(alias="fileCounts")
    archive_sha256: str | None = Field(alias="archiveSha256")


class OptionalLibraryStaticFiles(StaticFiles):
    async def check_config(self) -> None:
        """Allow the API to start and return 404 while the library is absent."""


def create_app(library_root: Path | None = None) -> FastAPI:
    resolved_library_root = library_root or Path(
        os.environ.get("LDRAW_LIBRARY_ROOT", "/data/ldraw/official")
    )
    application = FastAPI(title="Bricky API")

    @application.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        database_url = os.environ["DATABASE_URL"]

        with psycopg.connect(database_url, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()

        if result != (1,):
            raise RuntimeError("PostgreSQL health query returned an unexpected result")

        return HealthResponse(status="ok", database="ok")

    @application.get("/api/library/status", response_model=LibraryStatusResponse)
    def library_status() -> LibraryStatusResponse:
        status = get_library_status(resolved_library_root)
        counts = status.file_counts
        return LibraryStatusResponse(
            installed=status.installed,
            file_counts=(
                LibraryFileCountsResponse(dat=counts.dat, ldr=counts.ldr, png=counts.png)
                if counts is not None
                else None
            ),
            archive_sha256=status.archive_sha256,
        )

    application.mount(
        "/api/ldraw",
        OptionalLibraryStaticFiles(directory=resolved_library_root, check_dir=False),
        name="ldraw-library",
    )
    return application


app = create_app()
