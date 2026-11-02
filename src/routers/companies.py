"""
Companies API router.
Provides company directory, profile detail, and side-by-side comparison endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from src.database import DatabaseManager

router = APIRouter(prefix="/api/companies", tags=["Companies"])


@router.get("", summary="Search and filter monitored companies")
async def list_companies(
    request: Request,
    q: str = Query("", description="Free-text search query across all company fields"),
    name: str = Query("", description="Company name prefix or substring filter"),
    location: str = Query("", description="Goa location filter (e.g. Panaji, Verna)"),
    tech: str = Query("", description="Tech stack filter (e.g. Python, React)"),
    hiring_status: str = Query("", description="Hiring status category"),
    status: str = Query("", description="Pipeline status ('COMPLETED', 'PENDING', 'FAILED')"),
    limit: int = Query(50, ge=1, le=250, description="Max records to return"),
) -> list[dict[str, Any]]:
    """Return filtered list of Goan tech companies with opening counts."""
    db: DatabaseManager = request.app.state.db
    return await db.search_companies(
        query=q,
        company_name=name,
        location=location,
        tech=tech,
        hiring_status=hiring_status,
        status=status,
        limit=limit,
    )


@router.get("/compare", summary="Compare 2-3 companies side by side")
async def compare_companies(
    request: Request,
    names: str = Query(..., description="Comma-separated list of company names to compare"),
) -> list[dict[str, Any]]:
    """Compare multiple companies by tech stack, hiring status, location, and openings."""
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    if not name_list:
        raise HTTPException(status_code=400, detail="Provide at least one company name in 'names' parameter.")
    if len(name_list) > 5:
        raise HTTPException(status_code=400, detail="Comparison limited to at most 5 companies.")

    db: DatabaseManager = request.app.state.db
    return await db.compare_companies(name_list)


@router.get("/{name}", summary="Get full company profile and openings")
async def get_company_profile(
    request: Request,
    name: str,
    active_only: bool = Query(False, description="Filter only active openings"),
) -> dict[str, Any]:
    """Retrieve complete intelligence profile and openings for a company."""
    db: DatabaseManager = request.app.state.db
    profile = await db.get_company_profile(name, active_only=active_only)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Company '{name}' not found.")
    return profile
