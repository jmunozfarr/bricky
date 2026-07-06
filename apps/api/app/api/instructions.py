"""Instruction playback, build-manifest, and graph routes."""

from __future__ import annotations

import hashlib
import uuid
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.helpers import (
    SCOPE_COMPLEXITY_DETAIL,
    ModelsRouterContext,
    _inventory_for_requirements,
    _managed_source_path,
)
from app.schemas.instructions import (
    BuildManifestResponse,
    InstructionGraphResponse,
    InstructionPlaybackIssueResponse,
    InstructionPlaybackOccurrenceResponse,
    InstructionPlaybackSummaryResponse,
    PlaybackBreadcrumbResponse,
    PlaybackChildResponse,
    PlaybackStepSummaryResponse,
    _instruction_graph_response,
    _render_complexity_response,
)
from app.services.build_manifest import assemble_build_manifest
from app.services.instruction_graph import parse_instruction_graph
from app.services.instruction_playback import (
    PLAYBACK_CHILD_PAGE_SIZE,
    PLAYBACK_CHILD_PAGE_SIZE_MAXIMUM,
    derive_occurrence_source,
    playback_occurrence,
    select_render_strategy,
)
from app.services.ldraw_model_parser import ModelParseError
from app.services.ldraw_pack import LDrawPackError, LDrawPackLimitError


def register_instruction_routes(router: APIRouter, context: ModelsRouterContext) -> None:
    @router.get(
        "/{model_id}/instruction-playback",
        response_model=InstructionPlaybackSummaryResponse,
    )
    def model_instruction_playback(
        model_id: uuid.UUID, session: Session = Depends(context.session_dependency)
    ) -> InstructionPlaybackSummaryResponse:
        model = context.find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        data = context.playback_data_for(model)
        fallback_reason = None
        selection = (
            select_render_strategy(data, data.graph.root_occurrence_id, context.render_limits)
            if data.available
            else None
        )
        if not data.available:
            fallback_reason = (
                data.issues[0].message if data.issues else "The instruction graph is incomplete"
            )
        return InstructionPlaybackSummaryResponse(
            model_id=model.public_id,
            available=data.available,
            root_occurrence_id=(data.graph.root_occurrence_id if data.available else None),
            fallback_reason=fallback_reason,
            issues=[
                InstructionPlaybackIssueResponse(code=issue.code, message=issue.message)
                for issue in data.issues
            ],
            recommended_render_strategy=(
                selection.recommended_strategy if selection is not None else None
            ),
            render_strategy_reason=(
                selection.reason if selection is not None else "instruction_graph_unavailable"
            ),
            complexity=(
                _render_complexity_response(selection.complexity) if selection is not None else None
            ),
            flattened_rendering_allowed=(
                selection is None or selection.recommended_strategy == "subtree"
            ),
        )

    @router.get(
        "/{model_id}/instruction-occurrences/{occurrence_id}/build-manifest",
        response_model=BuildManifestResponse,
    )
    def model_build_manifest(
        model_id: uuid.UUID,
        occurrence_id: str,
        session: Session = Depends(context.session_dependency),
    ) -> BuildManifestResponse:
        model = context.find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        data = context.playback_data_for(model)
        if occurrence_id not in data.occurrence_by_id:
            raise HTTPException(status_code=404, detail="Instruction occurrence not found")
        if not data.available:
            raise HTTPException(status_code=409, detail="Hierarchical playback is unavailable")
        manifest = assemble_build_manifest(
            session,
            model,
            data,
            occurrence_id,
            library_root=context.library_root,
            render_limits=context.render_limits,
            scene_identity=context.scene_identity,
            packed_scene_for=context.packed_scene_for,
            inventory_for_requirements=_inventory_for_requirements,
        )
        return manifest

    @router.get(
        "/{model_id}/instruction-occurrences/{occurrence_id}",
        response_model=InstructionPlaybackOccurrenceResponse,
    )
    def model_instruction_occurrence(
        model_id: uuid.UUID,
        occurrence_id: str,
        step: int = Query(default=1, ge=1),
        child_offset: int = Query(default=0, alias="childOffset", ge=0),
        child_limit: int = Query(
            default=PLAYBACK_CHILD_PAGE_SIZE,
            alias="childLimit",
            ge=1,
            le=PLAYBACK_CHILD_PAGE_SIZE_MAXIMUM,
        ),
        requested_strategy: Literal["recommended", "subtree", "local"] = Query(
            default="recommended", alias="renderStrategy"
        ),
        session: Session = Depends(context.session_dependency),
    ) -> InstructionPlaybackOccurrenceResponse:
        model = context.find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        data = context.playback_data_for(model)
        if occurrence_id not in data.occurrence_by_id:
            raise HTTPException(status_code=404, detail="Instruction occurrence not found")
        if not data.available:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Hierarchical playback is unavailable",
                    "issues": [
                        {"code": issue.code, "message": issue.message} for issue in data.issues
                    ],
                },
            )
        try:
            result = playback_occurrence(
                data,
                occurrence_id,
                current_step=step,
                child_offset=child_offset,
                child_limit=child_limit,
            )
            selection = select_render_strategy(data, occurrence_id, context.render_limits)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        render_strategy = (
            selection.recommended_strategy
            if requested_strategy == "recommended"
            else requested_strategy
        )
        if render_strategy == "subtree" and selection.recommended_strategy == "local":
            raise HTTPException(status_code=409, detail=SCOPE_COMPLEXITY_DETAIL)
        occurrence = result.occurrence
        encoded_occurrence = quote(occurrence_id, safe="")
        return InstructionPlaybackOccurrenceResponse(
            model_id=model.public_id,
            occurrence_id=occurrence.occurrence_id,
            parent_occurrence_id=occurrence.parent_occurrence_id,
            source_submodel_name=occurrence.source_submodel_name,
            attachment_step=occurrence.attachment_step,
            depth=occurrence.depth,
            traversal_order=occurrence.traversal_order,
            breadcrumbs=[
                PlaybackBreadcrumbResponse(
                    occurrence_id=item.occurrence_id,
                    source_submodel_name=item.source_submodel_name,
                )
                for item in result.breadcrumbs
            ],
            local_step_count=result.local_step_count,
            current_step=result.current_step,
            previous_step=result.previous_step,
            next_step=result.next_step,
            complete=result.complete,
            empty=result.empty,
            repeated_definition_count=result.repeated_definition_count,
            repeated_definition_index=result.repeated_definition_index,
            step_summary=PlaybackStepSummaryResponse(
                step=result.step_summary.step,
                local_part_count=result.step_summary.local_part_count,
                child_attachment_count=result.step_summary.child_attachment_count,
                direct_geometry_command_count=(result.step_summary.direct_geometry_command_count),
            ),
            children=[
                PlaybackChildResponse(
                    occurrence_id=child.occurrence_id,
                    source_submodel_name=child.source_submodel_name,
                    attachment_step=child.attachment_step,
                    traversal_order=child.traversal_order,
                    repeated_definition_count=child.repeated_definition_count,
                    repeated_definition_index=child.repeated_definition_index,
                )
                for child in result.children
            ],
            child_total=result.child_total,
            child_offset=result.child_offset,
            child_limit=result.child_limit,
            scene_source_url=(
                f"/api/models/{quote(str(model.public_id), safe='')}/"
                f"instruction-occurrences/{encoded_occurrence}/source"
                f"?mode={render_strategy}&step={result.current_step}"
            ),
            render_strategy=render_strategy,
            recommended_render_strategy=selection.recommended_strategy,
            render_strategy_reason=selection.reason,
            complexity=_render_complexity_response(selection.complexity),
        )

    @router.get(
        "/{model_id}/instruction-occurrences/{occurrence_id}/source",
        response_class=Response,
    )
    def model_instruction_occurrence_source(
        model_id: uuid.UUID,
        occurrence_id: str,
        request: Request,
        mode: Literal["subtree", "local"] = Query(default="subtree"),
        step: int | None = Query(default=None, ge=1),
        delivery: Literal["external", "packed"] = Query(default="external"),
        session: Session = Depends(context.session_dependency),
    ) -> Response:
        model = context.find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        data = context.playback_data_for(model)
        if occurrence_id not in data.occurrence_by_id:
            raise HTTPException(status_code=404, detail="Instruction occurrence not found")
        if not data.available:
            raise HTTPException(status_code=409, detail="Hierarchical playback is unavailable")
        try:
            selection = select_render_strategy(data, occurrence_id, context.render_limits)
            if mode == "subtree" and selection.recommended_strategy == "local":
                raise HTTPException(status_code=409, detail=SCOPE_COMPLEXITY_DETAIL)
            if delivery == "packed":
                if step is not None:
                    raise HTTPException(
                        status_code=422,
                        detail="Packed delivery is available only for complete scenes",
                    )
                _cache_key, packed = context.packed_scene_for(model, data, occurrence_id, mode)
                content = packed.content
            else:
                content = derive_occurrence_source(
                    data, occurrence_id, current_step=step, strategy=mode
                )
        except LDrawPackLimitError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except LDrawPackError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        etag = hashlib.sha256(content).hexdigest()
        cache_control = (
            "private, max-age=31536000, immutable"
            if delivery == "packed"
            else "private, max-age=3600"
        )
        if request.headers.get("if-none-match") == f'"{etag}"':
            return Response(
                status_code=304,
                headers={"Cache-Control": cache_control, "ETag": f'"{etag}"'},
            )
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={
                "Cache-Control": cache_control,
                "ETag": f'"{etag}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/{model_id}/instruction-graph", response_model=InstructionGraphResponse)
    def model_instruction_graph(
        model_id: uuid.UUID, session: Session = Depends(context.session_dependency)
    ) -> InstructionGraphResponse:
        model = context.find_model(session, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        source_path = _managed_source_path(context.storage_root, model)
        if source_path is None or not source_path.is_file():
            raise HTTPException(status_code=404, detail="Model source not found")
        try:
            graph = parse_instruction_graph(
                source_path.read_bytes(),
                source_name=model.original_filename,
                limits=context.graph_limits,
            )
        except ModelParseError as error:
            raise HTTPException(
                status_code=422, detail=f"Instruction graph unavailable: {error}"
            ) from error
        return _instruction_graph_response(model.public_id, graph, context.graph_limits)
