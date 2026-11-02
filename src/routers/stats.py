"""
Dashboard and statistics API router.
Provides aggregated pipeline metrics, hiring trends, and scrape cycle timing.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

from src.database import DatabaseManager
from src.scheduler import get_scrape_status

router = APIRouter(prefix="/api/stats", tags=["Statistics"])

# In-memory simple TTL cache (5-minute TTL as requested in Section 11)
_stats_cache: dict[str, Any] = {"data": None, "timestamp": 0.0}
_trends_cache: dict[str, Any] = {"data": None, "timestamp": 0.0}
CACHE_TTL_SECONDS = 300.0


@router.get("", summary="Get overall pipeline metrics and scrape stats")
async def get_stats(request: Request) -> dict[str, Any]:
    """Return pipeline metrics, counts of active jobs, CE roles, and scrape status."""
    now = time.time()
    if _stats_cache["data"] and (now - _stats_cache["timestamp"] < CACHE_TTL_SECONDS):
        return _stats_cache["data"]

    db: DatabaseManager = request.app.state.db
    stats = await db.get_stats()
    scrape_status = get_scrape_status()

    response = {
        "pipeline": stats,
        "scrape_status": scrape_status,
        "cached": False,
    }
    _stats_cache["data"] = response
    _stats_cache["timestamp"] = now
    return response


@router.get("/trends", summary="Get visual hiring trends and analytics charts data")
async def get_hiring_trends(request: Request) -> dict[str, Any]:
    """Return hiring trends: weekly jobs, top companies, tech demand, and locations."""
    now = time.time()
    if _trends_cache["data"] and (now - _trends_cache["timestamp"] < CACHE_TTL_SECONDS):
        return _trends_cache["data"]

    db: DatabaseManager = request.app.state.db
    trends = await db.get_hiring_trends()

    response = {
        "trends": trends,
        "cached": False,
    }
    _trends_cache["data"] = response
    _trends_cache["timestamp"] = now
    return response
