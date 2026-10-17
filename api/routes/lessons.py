"""Lessons endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from api.auth import require_token
from api.deps import RuntimeDep

router = APIRouter(
    prefix="/api", tags=["lessons"], dependencies=[Depends(require_token)]
)


@router.get("/lessons")
async def lessons(
    runtime: RuntimeDep,
    limit: int = Query(default=15, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    repo = getattr(runtime.orchestrator, "lesson_repo", None)
    if repo is not None:
        rows = await repo.recent(limit=limit, offset=offset)
        total = await repo.count()
        has_more = (offset + len(rows)) < total
        return {
            "lessons": rows,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "source": "db",
        }
    mem_patterns = runtime.patterns.top(limit + offset)
    p_slice = mem_patterns[offset : offset + limit]
    return {
        "lessons": p_slice,
        "total": len(mem_patterns),
        "offset": offset,
        "limit": limit,
        "has_more": (offset + len(p_slice)) < len(mem_patterns),
        "source": "memory",
    }


__all__ = ["router"]
