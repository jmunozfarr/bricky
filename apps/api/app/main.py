from collections.abc import Iterator
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles

from app.catalog_api import create_catalog_router
from app.core.config import get_settings
from app.database import get_session_factory
from app.inventory_api import create_inventory_router
from app.models_api import create_models_router
from app.services.instruction_graph import InstructionGraphLimits
from app.services.instruction_playback import RenderComplexityLimits
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


def create_app(
    library_root: Path | None = None,
    session_factory: sessionmaker[Session] | None = None,
    model_storage_root: Path | None = None,
    model_max_upload_bytes: int | None = None,
    instruction_graph_limits: InstructionGraphLimits | None = None,
    render_complexity_limits: RenderComplexityLimits | None = None,
) -> FastAPI:
    settings = get_settings()
    resolved_library_root = library_root or settings.ldraw_library_root
    application = FastAPI(title="Bricky API")
    application.add_middleware(GZipMiddleware, minimum_size=1_024)
    active_session_factory = session_factory or get_session_factory()
    resolved_model_storage_root = model_storage_root or settings.model_storage_root
    resolved_model_max_upload_bytes = model_max_upload_bytes or settings.model_max_upload_bytes
    resolved_instruction_graph_limits = (
        instruction_graph_limits or settings.instruction_graph_limits()
    )
    resolved_render_complexity_limits = (
        render_complexity_limits or settings.render_complexity_limits()
    )

    def catalog_session() -> Iterator[Session]:
        with active_session_factory() as session:
            yield session

    @application.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        # Checks through the application's own session factory, so it
        # exercises the pooled SQLAlchemy engine instead of opening a fresh
        # database connection per probe.
        with active_session_factory() as session:
            result = session.execute(text("SELECT 1")).scalar_one()

        if result != 1:
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

    application.include_router(create_catalog_router(resolved_library_root, catalog_session))
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
