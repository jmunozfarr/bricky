from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.instruction_graph import (
    DEFAULT_MAX_EXPANDED_OCCURRENCES,
    DEFAULT_MAX_INSTRUCTION_NODES,
    DEFAULT_MAX_NESTING_DEPTH,
    InstructionGraphLimits,
)
from app.services.instruction_playback import (
    DEFAULT_RENDER_MAX_DERIVED_SOURCE_BYTES,
    DEFAULT_RENDER_MAX_DIRECT_GEOMETRY_COMMANDS,
    DEFAULT_RENDER_MAX_EXPANDED_INSTRUCTION_NODES,
    DEFAULT_RENDER_MAX_EXPANDED_OCCURRENCES,
    RenderComplexityLimits,
)
from app.services.inventory_import import DEFAULT_MAX_CSV_UPLOAD_BYTES
from app.services.model_import import DEFAULT_MAX_UPLOAD_BYTES


class Settings(BaseSettings):
    """Environment-backed application settings.

    Field names map 1:1 to the environment variables documented in
    `.env.example`; compose files provide the same defaults as the code so
    that a bare environment and the dev stack behave identically.
    """

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    database_url: str = ""
    ldraw_library_root: Path = Path("/data/ldraw/official")
    model_storage_root: Path = Path("/data/models")
    part_thumbnail_root: Path = Path("/data/thumbnails")
    model_max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    inventory_max_upload_bytes: int = DEFAULT_MAX_CSV_UPLOAD_BYTES
    # Used only by `python -m app.cli.rebrickable_mapping populate`, never in
    # the request path — the app stays offline-first at runtime.
    rebrickable_api_key: str | None = None

    instruction_graph_max_nesting_depth: int = DEFAULT_MAX_NESTING_DEPTH
    instruction_graph_max_expanded_occurrences: int = DEFAULT_MAX_EXPANDED_OCCURRENCES
    instruction_graph_max_instruction_nodes: int = DEFAULT_MAX_INSTRUCTION_NODES

    render_max_expanded_instruction_nodes: int = DEFAULT_RENDER_MAX_EXPANDED_INSTRUCTION_NODES
    render_max_expanded_occurrences: int = DEFAULT_RENDER_MAX_EXPANDED_OCCURRENCES
    render_max_direct_geometry_commands: int = DEFAULT_RENDER_MAX_DIRECT_GEOMETRY_COMMANDS
    render_max_derived_source_bytes: int = DEFAULT_RENDER_MAX_DERIVED_SOURCE_BYTES

    def instruction_graph_limits(self) -> InstructionGraphLimits:
        return InstructionGraphLimits(
            max_nesting_depth=self.instruction_graph_max_nesting_depth,
            max_expanded_occurrences=self.instruction_graph_max_expanded_occurrences,
            max_instruction_nodes=self.instruction_graph_max_instruction_nodes,
        )

    def render_complexity_limits(self) -> RenderComplexityLimits:
        return RenderComplexityLimits(
            max_expanded_instruction_nodes=self.render_max_expanded_instruction_nodes,
            max_expanded_occurrences=self.render_max_expanded_occurrences,
            max_direct_geometry_commands=self.render_max_direct_geometry_commands,
            max_derived_source_bytes=self.render_max_derived_source_bytes,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    """Test hook: force the next get_settings() to re-read the environment."""
    get_settings.cache_clear()
