from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from time import perf_counter

import pytest
from instruction_fixture_factory import generated_large_repeated_model

from app.services.instruction_graph import parse_instruction_graph


@pytest.mark.parametrize("physical_parts", [100, 1_000, 5_000])
def test_generated_fixture_diagnostics(
    physical_parts: int, record_property: Callable[[str, object], None]
) -> None:
    source = generated_large_repeated_model(physical_parts)
    started = perf_counter()
    graph = parse_instruction_graph(source)
    duration_ms = (perf_counter() - started) * 1_000
    output_size_bytes = len(json.dumps(asdict(graph), separators=(",", ":")).encode("utf-8"))
    diagnostics = {
        "physicalPartOccurrences": physical_parts,
        "durationMs": round(duration_ms, 3),
        "modelDefinitionCount": len(graph.model_definitions),
        "expandedOccurrenceCount": len(graph.occurrences),
        "instructionNodeCount": len(graph.instruction_nodes),
        "maximumNestingDepth": graph.maximum_nesting_depth,
        "outputSizeBytes": output_size_bytes,
    }
    record_property("instruction_graph_diagnostics", json.dumps(diagnostics))
    print(f"instruction-graph diagnostic: {json.dumps(diagnostics)}")

    assert len(graph.model_definitions) == 2
    assert len(graph.occurrences) == physical_parts + 1
    assert len(graph.instruction_nodes) == physical_parts * 2
    assert graph.maximum_nesting_depth == 1
    assert graph.issues == ()
