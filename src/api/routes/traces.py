"""API routes for trace querying and analytics."""

from typing import Optional

from fastapi import APIRouter, HTTPException

from src.api.schemas import TraceListResponse, TraceResponse, UsageStatsResponse
from src.services.trace_service import TraceService

router = APIRouter(tags=["traces"])
trace_service = TraceService()


@router.get("", response_model=TraceListResponse)
async def list_traces(repo_id: Optional[str] = None, limit: int = 20):
    """List recent traces."""
    traces = trace_service.list_traces(repo_id=repo_id, limit=limit)
    return TraceListResponse(
        traces=[TraceResponse(**t) for t in traces],
        total=len(traces),
    )


@router.get("/stats", response_model=UsageStatsResponse)
async def get_usage_stats(repo_id: Optional[str] = None):
    """Get aggregated usage statistics."""
    stats = trace_service.get_usage_stats(repo_id=repo_id)
    return UsageStatsResponse(**stats)


@router.get("/{trace_id}", response_model=TraceResponse)
async def get_trace(trace_id: str):
    """Get full trace details with spans."""
    trace = trace_service.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return TraceResponse(**trace)
