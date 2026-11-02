"""
Job openings API router.
Provides job search, fresher role shortcuts, government job calendar data, and email alerts.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from src.database import DatabaseManager
from src.models import JobAlertCreate, JobAlertResponse

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])


@router.get("", summary="Search and filter job openings")
async def list_jobs(
    request: Request,
    q: str = Query("", description="Free-text search query across titles, tech, and descriptions"),
    title: str = Query("", description="Role title or department filter"),
    tech: str = Query("", description="Required skill or technology"),
    company: str = Query("", description="Company name filter"),
    experience: str = Query("", description="Experience level (e.g. Fresher, Mid, Senior)"),
    location: str = Query("", description="Goa location filter"),
    ce_only: bool = Query(False, description="Restrict to Computer Engineering relevant roles"),
    active_only: bool = Query(True, description="Filter only active openings"),
    time_range: str = Query("", description="Time filter ('this week', 'this month', or days number)"),
    limit: int = Query(50, ge=1, le=250, description="Max jobs to return"),
) -> list[dict[str, Any]]:
    """Return filtered job openings across Goan tech companies."""
    db: DatabaseManager = request.app.state.db
    return await db.search_job_openings(
        query=q,
        title=title,
        tech=tech,
        company_name=company,
        experience_level=experience,
        location=location,
        only_ce_relevant=ce_only,
        active_only=active_only,
        time_range=time_range,
        limit=limit,
    )


@router.get("/freshers", summary="Shortcut for Computer Engineering relevant fresher & intern roles")
async def list_fresher_jobs(
    request: Request,
    tech: str = Query("", description="Optional technology filter"),
    location: str = Query("", description="Optional Goa location filter"),
    limit: int = Query(50, ge=1, le=250),
) -> list[dict[str, Any]]:
    """Convenience shortcut to get CE-relevant fresher, trainee, and intern roles."""
    db: DatabaseManager = request.app.state.db
    return await db.search_job_openings(
        tech=tech,
        location=location,
        experience_level="fresher",
        only_ce_relevant=True,
        active_only=True,
        limit=limit,
    )


@router.get("/govt", summary="Government, PSU, and autonomous body recruitment circulars")
async def list_govt_jobs(
    request: Request,
    upcoming_only: bool = Query(True, description="Sort by upcoming application deadline"),
) -> list[dict[str, Any]]:
    """Return government portal jobs (GPSC, CBES, etc.) with application deadlines."""
    db: DatabaseManager = request.app.state.db
    return await db.get_government_jobs(upcoming=upcoming_only)


@router.post("/alerts", response_model=JobAlertResponse, summary="Subscribe for email job alerts")
async def create_job_alert(
    request: Request,
    payload: JobAlertCreate,
) -> JobAlertResponse:
    """Subscribe to receive email notifications when matching jobs are scraped."""
    db: DatabaseManager = request.app.state.db
    res = await db.create_job_alert(
        email=payload.email,
        tech_filter=payload.tech_filter,
        location_filter=payload.location_filter,
        experience_filter=payload.experience_filter,
        ce_only=payload.ce_only,
    )
    return JobAlertResponse(**res)


@router.get("/alerts/unsubscribe", summary="Deactivate email job alerts subscription")
async def unsubscribe_alert(
    request: Request,
    token: str = Query(..., description="Unsubscribe token sent in alert email"),
) -> dict[str, Any]:
    """Deactivate an active job alert subscription."""
    db: DatabaseManager = request.app.state.db
    success = await db.unsubscribe_alert(token)
    if not success:
        raise HTTPException(status_code=404, detail="Invalid or expired unsubscribe token.")
    return {"status": "success", "message": "Successfully unsubscribed from GoaIT job alerts."}
