"""Shared API dependencies."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status


def get_runtime(request: Request) -> Any:
    """Return the live Runtime, or 503 if it is not running."""
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="runtime not enabled",
        )
    return runtime


RuntimeDep = Annotated[Any, Depends(get_runtime)]

__all__ = ["get_runtime", "RuntimeDep"]
