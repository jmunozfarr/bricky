from collections.abc import Iterator
import os
from pathlib import Path

import psycopg
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from app.catalog_api import create_catalog_router
from app.database import SessionFactory
from app.inventory_api import create_inventory_router
from app.models_api import create_models_router
from app.services.instruction_graph import (
    DEFAULT_MAX_EXPANDED_OCCURRENCES,
    DEFAULT_MAX_INSTRUCTION_NODES,
    DEFAULT_MAX_NESTING_DEPTH,
    InstructionGraphLimits,
)
from app.services.ldraw_library import get_library_status
from app.services.instruction_playback import (
    DEFAULT_RENDER_MAX_DERIVED_SOURCE_BYTES,
    DEFAULT_RENDER_MAX_DIRECT_GEOMETRY_COMMANDS,
    DEFAULT_RENDER_MAX_EXPANDED_INSTRUCTION_NODES,
    DEFAULT_RENDER_MAX_EXPANDED_OCCURRENCES,
    RenderComplexityLimits,
)
from app.services.model_import import DEFAULT_MAX_UPLOAD_BYTES


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


def create_app(
    library_root: Path | None = None,
    session_factory: sessionmaker[Session] | None = None,
    model_storage_root: Path | None = None,
    model_max_upload_bytes: int | None = None,
    instruction_graph_limits: InstructionGraphLimits | None = None,
    render_complexity_limits: RenderComplexityLimits | None = None,
) -> FastAPI:
    resolved_library_root = library_root or Path(
        os.environ.get("LDRAW_LIBRARY_ROOT", "/data/ldraw/official")
    )
    application = FastAPI(title="Bricky API")
    application.add_middleware(GZipMiddleware, minimum_size=1_024)
    active_session_factory = session_factory or SessionFactory
    resolved_model_storage_root = model_storage_root or Path(
        os.environ.get("MODEL_STORAGE_ROOT", "/data/models")
    )
    resolved_model_max_upload_bytes = model_max_upload_bytes or int(
        os.environ.get("MODEL_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES))
    )
    resolved_instruction_graph_limits = instruction_graph_limits or InstructionGraphLimits(
        max_nesting_depth=int(
            os.environ.get(
                "INSTRUCTION_GRAPH_MAX_NESTING_DEPTH", str(DEFAULT_MAX_NESTING_DEPTH)
            )
        ),
        max_expanded_occurrences=int(
            os.environ.get(
                "INSTRUCTION_GRAPH_MAX_EXPANDED_OCCURRENCES",
                str(DEFAULT_MAX_EXPANDED_OCCURRENCES),
            )
        ),
        max_instruction_nodes=int(
            os.environ.get(
                "INSTRUCTION_GRAPH_MAX_INSTRUCTION_NODES",
                str(DEFAULT_MAX_INSTRUCTION_NODES),
            )
        ),
    )
    resolved_render_complexity_limits = (
        render_complexity_limits
        or RenderComplexityLimits(
            max_expanded_instruction_nodes=int(
                os.environ.get(
                    "RENDER_MAX_EXPANDED_INSTRUCTION_NODES",
                    str(DEFAULT_RENDER_MAX_EXPANDED_INSTRUCTION_NODES),
                )
            ),
            max_expanded_occurrences=int(
                os.environ.get(
                    "RENDER_MAX_EXPANDED_OCCURRENCES",
                    str(DEFAULT_RENDER_MAX_EXPANDED_OCCURRENCES),
                )
            ),
            max_direct_geometry_commands=int(
                os.environ.get(
                    "RENDER_MAX_DIRECT_GEOMETRY_COMMANDS",
                    str(DEFAULT_RENDER_MAX_DIRECT_GEOMETRY_COMMANDS),
                )
            ),
            max_derived_source_bytes=int(
                os.environ.get(
                    "RENDER_MAX_DERIVED_SOURCE_BYTES",
                    str(DEFAULT_RENDER_MAX_DERIVED_SOURCE_BYTES),
                )
            ),
        )
    )

    def catalog_session() -> Iterator[Session]:
        with active_session_factory() as session:
            yield session

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

    application.include_router(
        create_catalog_router(resolved_library_root, catalog_session)
    )
    application.include_router(create_inventory_router(catalog_session))
    application.include_router(
        create_models_router(
            catalog_session,
            active_session_factory,
            resolved_library_root,
            resolved_model_storage_root,
            resolved_model_max_upload_bytes,
            resolved_instruction_graph_limits,
            resolved_render_complexity_limits,
        )
    )

    application.mount(
        "/api/ldraw",
        OptionalLibraryStaticFiles(directory=resolved_library_root, check_dir=False),
        name="ldraw-library",
    )
    return application


app = create_app()
