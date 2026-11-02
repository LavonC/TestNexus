"""
Admin API router.
Protected by ADMIN_SECRET bearer token or header.
Provides manual scrape triggers, URL health checks, and seed company management.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from src.config import config
from src.database import DatabaseManager
from src.scheduler import get_scrape_status, run_scrape_cycle
from src.url_verifier import verify_company

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


async def verify_admin_secret(
    authorization: str | None = Header(None),
    x_admin_secret: str | None = Header(None),
) -> None:
    """Validate admin authorization token against config.ADMIN_SECRET."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif x_admin_secret:
        token = x_admin_secret.strip()

    if not token or token != config.ADMIN_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid or missing ADMIN_SECRET.",
        )


@router.post("/scrape", dependencies=[Depends(verify_admin_secret)], summary="Trigger immediate scrape cycle")
async def trigger_scrape(request: Request) -> dict[str, Any]:
    """Manually invoke a background scraping cycle."""
    db: DatabaseManager = request.app.state.db
    # Launch async task so request does not timeout on Render
    asyncio.create_task(run_scrape_cycle(db, limit=50))
    return {
        "status": "triggered",
        "message": "Scrape cycle dispatched in background.",
    }


@router.get("/scrape-status", dependencies=[Depends(verify_admin_secret)], summary="Get scrape status and telemetry")
async def scrape_status() -> dict[str, Any]:
    """Retrieve telemetry from the background scrape engine."""
    return get_scrape_status()


@router.post("/verify-urls", dependencies=[Depends(verify_admin_secret)], summary="Verify seed URLs health and DNS")
async def verify_urls(request: Request) -> dict[str, Any]:
    """Run health verification across monitored company websites."""
    db: DatabaseManager = request.app.state.db
    companies = await db.get_all_companies()

    async def _run_check():
        for comp in companies[:30]:
            try:
                report = await verify_company(comp)
                if report.is_dead:
                    await db.update_company_urls(
                        comp["company_name"],
                        is_dead=1,
                        error_message="Website unreachable or dead domain",
                    )
            except Exception as e:
                logger.debug("URL check failed for %s: %s", comp.get("company_name"), e)

    asyncio.create_task(_run_check())
    return {
        "status": "triggered",
        "message": "URL verification started in background.",
    }


@router.get("/seed", dependencies=[Depends(verify_admin_secret)], summary="Get seed companies list")
async def get_seed_list() -> list[dict[str, Any]]:
    """Retrieve checked-in seed company definitions."""
    if not config.SEED_FILE_PATH.exists():
        return []
    try:
        content = json.loads(config.SEED_FILE_PATH.read_text(encoding="utf-8"))
        return content if isinstance(content, list) else []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read seed file: {exc}")


@router.post("/seed", dependencies=[Depends(verify_admin_secret)], summary="Add company to seed list")
async def add_seed_company(request: Request, company_data: dict[str, Any]) -> dict[str, Any]:
    """Add a new company to the seed list and database queue."""
    name = company_data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required.")

    db: DatabaseManager = request.app.state.db
    await db.seed_companies([company_data], reset=False)

    # Append to seed JSON file if writeable
    try:
        seeds = []
        if config.SEED_FILE_PATH.exists():
            seeds = json.loads(config.SEED_FILE_PATH.read_text(encoding="utf-8"))
        if not any(s.get("name", "").lower() == name.lower() for s in seeds):
            seeds.append(company_data)
            config.SEED_FILE_PATH.write_text(json.dumps(seeds, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not write new company to seed file: %s", e)

    return {"status": "success", "message": f"Company '{name}' added to seed queue."}


@router.delete("/seed/{name}", dependencies=[Depends(verify_admin_secret)], summary="Remove company from seed list")
async def delete_seed_company(request: Request, name: str) -> dict[str, Any]:
    """Remove a company from the seed list and mark as dead in the database."""
    target_name = name.strip()
    if not target_name:
        raise HTTPException(status_code=400, detail="Company name is required.")

    db: DatabaseManager = request.app.state.db
    await db.update_company_urls(
        target_name,
        is_dead=1,
        error_message="Removed from monitored seed list by administrator",
    )

    try:
        if config.SEED_FILE_PATH.exists():
            seeds = json.loads(config.SEED_FILE_PATH.read_text(encoding="utf-8"))
            updated = [s for s in seeds if s.get("name", "").lower() != target_name.lower()]
            config.SEED_FILE_PATH.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not update seed file on delete: %s", e)

    return {"status": "success", "message": f"Company '{target_name}' removed from seed list."}


@router.put("/seed/{name}", dependencies=[Depends(verify_admin_secret)], summary="Update company in seed list")
async def update_seed_company(request: Request, name: str, update_data: dict[str, Any]) -> dict[str, Any]:
    """Update company URLs and metadata in the seed list and database."""
    target_name = name.strip()
    if not target_name:
        raise HTTPException(status_code=400, detail="Company name is required.")

    db: DatabaseManager = request.app.state.db
    await db.update_company_urls(
        target_name,
        website=update_data.get("website") or update_data.get("website_url"),
        careers=update_data.get("careers") or update_data.get("careers_url"),
        is_dead=update_data.get("is_dead"),
    )

    try:
        if config.SEED_FILE_PATH.exists():
            seeds = json.loads(config.SEED_FILE_PATH.read_text(encoding="utf-8"))
            for s in seeds:
                if s.get("name", "").lower() == target_name.lower():
                    s.update({k: v for k, v in update_data.items() if v is not None})
            config.SEED_FILE_PATH.write_text(json.dumps(seeds, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not update seed file: %s", e)

    return {"status": "success", "message": f"Company '{target_name}' updated successfully."}
