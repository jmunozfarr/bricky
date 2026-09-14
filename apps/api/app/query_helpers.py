"""Shared query utilities used by multiple API modules."""

from __future__ import annotations


def escaped_pattern(query: str) -> str:
    """Escape SQL LIKE wildcards and wrap *query* for a contains-match."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
