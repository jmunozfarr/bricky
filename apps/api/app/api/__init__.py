"""HTTP routers."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from sqlalchemy.orm import Session, sessionmaker

from app.api.helpers import ModelsRouterContext, SessionDependency
from app.api.instructions import register_instruction_routes
from app.api.models import register_model_routes
from app.services.instruction_graph import InstructionGraphLimits
from app.services.instruction_playback import RenderComplexityLimits


def create_models_router(
    session_dependency: SessionDependency,
    session_factory: sessionmaker[Session],
    library_root: Path,
    storage_root: Path,
    maximum_upload_bytes: int,
    instruction_graph_limits: InstructionGraphLimits | None = None,
    render_complexity_limits: RenderComplexityLimits | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/models")
    context = ModelsRouterContext(
        session_dependency=session_dependency,
        session_factory=session_factory,
        library_root=library_root,
        storage_root=storage_root,
        maximum_upload_bytes=maximum_upload_bytes,
        graph_limits=instruction_graph_limits or InstructionGraphLimits(),
        render_limits=render_complexity_limits or RenderComplexityLimits(),
    )
    register_model_routes(router, context)
    register_instruction_routes(router, context)
    return router
