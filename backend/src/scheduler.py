"""
Background scraping scheduler using APScheduler (in-process for Render Free Tier).
Runs scrape cycles every 6 hours with rate-throttled mini-batches (5 concurrent, 2s delays),
builds offline heuristic profiles (0 AI calls during ingestion), and triggers job email alerts.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
import httpx

from src.config import config
from src.database import DatabaseManager
from src.heuristic_extractor import build_offline_profile
from src.models import CompanySeed
from src.scraper import Scraper

logger = logging.getLogger(__name__)

# Global status tracking for monitoring and admin endpoints
_scrape_status: dict[str, Any] = {
    "is_running": False,
    "last_run_at": None,
    "last_duration_seconds": 0.0,
    "companies_scraped_last_run": 0,
    "total_jobs_detected_last_run": 0,
    "errors_last_run": 0,
    "status_message": "Scheduler initialized; waiting for next cycle.",
}


def get_scrape_status() -> dict[str, Any]:
    """Return read-only copy of current scrape status."""
    return dict(_scrape_status)


async def send_email_alert(
    email: str,
    matched_jobs: list[dict[str, Any]],
    unsubscribe_token: str,
) -> bool:
    """Send job alert email via Resend if RESEND_API_KEY is configured."""
    if not config.RESEND_API_KEY:
        logger.info(
            "RESEND_API_KEY not configured. Mocking email alert to %s (%d jobs)",
            email,
            len(matched_jobs),
        )
        return True

    job_items_html = "".join([
        f"<li><strong>{j.get('title')}</strong> at {j.get('company_name')} "
        f"({j.get('experience_level', 'Any')}) - "
        f"<a href='{j.get('apply_url') or '#'}'>Apply</a></li>"
        for j in matched_jobs[:10]
    ])

    unsub_url = f"{config.FRONTEND_URL}/jobs?unsubscribe={unsubscribe_token}"

    html_content = f"""
    <h2>New Goa Tech Jobs Matching Your Alert</h2>
    <p>We found {len(matched_jobs)} new job openings matching your preferences:</p>
    <ul>{job_items_html}</ul>
    <hr />
    <p><small><a href="{unsub_url}">Unsubscribe from job alerts</a></small></p>
    """

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {config.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": config.RESEND_FROM_EMAIL,
                    "to": [email],
                    "subject": f"GoaIT Job Alert: {len(matched_jobs)} New Jobs Detected",
                    "html": html_content,
                },
            )
            return resp.status_code in (200, 201)
    except Exception as e:
        logger.warning("Failed to send Resend email alert to %s: %s", email, e)
        return False


async def check_and_send_alerts(db: DatabaseManager, new_jobs: list[dict[str, Any]]) -> None:
    """Check newly detected jobs against active email alert subscriptions."""
    if not new_jobs:
        return

    try:
        alerts = await db.get_active_alerts()
        for alert in alerts:
            email = alert["email"]
            tech_filters = [t.lower() for t in alert.get("tech_filter", [])]
            loc_filters = [loc.lower() for loc in alert.get("location_filter", [])]
            exp_filter = (alert.get("experience_filter") or "").lower().strip()
            ce_only = bool(alert.get("ce_only", False))

            matched: list[dict[str, Any]] = []
            for j in new_jobs:
                if ce_only and not j.get("is_computer_eng_relevant"):
                    continue

                if exp_filter and exp_filter not in (j.get("experience_level") or "").lower():
                    continue

                if tech_filters:
                    stack = [str(s).lower() for s in j.get("tech_stack", [])]
                    if not any(tf in stack for tf in tech_filters):
                        continue

                matched.append(j)

            if matched:
                await send_email_alert(email, matched, alert.get("unsubscribe_token", ""))
    except Exception as exc:
        logger.warning("Error evaluating job alerts: %s", exc)


async def run_scrape_cycle(db: DatabaseManager, limit: int = 50) -> dict[str, Any]:
    """
    Execute a background scrape cycle across stale companies.
    Runs entirely offline with 0 Gemini AI calls during ingestion.
    """
    global _scrape_status

    if _scrape_status["is_running"]:
        logger.warning("Scrape cycle already in progress; skipping duplicate run.")
        return {"status": "already_running"}

    _scrape_status["is_running"] = True
    start_time = datetime.now(timezone.utc)
    _scrape_status["last_run_at"] = start_time.isoformat()
    _scrape_status["status_message"] = "Scraping in progress..."

    scraped_count = 0
    total_jobs = 0
    errors_count = 0
    all_detected_jobs: list[dict[str, Any]] = []

    try:
        scraper = Scraper(concurrency=config.MAX_CONCURRENT_SCRAPES)

        # 1. Fetch stale companies (older than 6 hours) or pending
        candidates = await db.get_stale_companies(stale_hours=6.0, limit=limit)
        if not candidates:
            candidates = await db.get_pending_companies(limit=limit)

        if not candidates:
            _scrape_status["status_message"] = "All companies up-to-date; nothing to scrape."
            logger.info("Scrape cycle completed: 0 companies needed scraping.")
            return {"status": "no_work_needed"}

        logger.info("Starting scrape cycle for %d companies", len(candidates))

        # 2. Process in mini-batches of 5 with 2s delay
        batch_size = 5
        for i in range(0, len(candidates), batch_size):
            batch = candidates[i : i + batch_size]
            for item in batch:
                cname = item.get("company_name") or item.get("name")
                if not cname:
                    continue

                seed = CompanySeed(
                    name=cname,
                    website=item.get("website_url") or item.get("website"),
                    careers=item.get("careers_url") or item.get("careers"),
                    rss=item.get("rss_url") or item.get("rss"),
                )

                try:
                    await db.mark_in_progress(cname)
                    scraped_data = await scraper.scrape_company(seed)
                    intel = build_offline_profile(cname, scraped_data, seed=item)
                    await db.save_company_intelligence_stateful(cname, intel, seed=item)

                    scraped_count += 1
                    total_jobs += len(intel.active_openings)

                    for opening in intel.active_openings:
                        all_detected_jobs.append({
                            "company_name": cname,
                            "title": opening.title,
                            "department": opening.department,
                            "experience_level": opening.experience_level,
                            "tech_stack": opening.tech_stack,
                            "is_computer_eng_relevant": opening.is_computer_eng_relevant,
                            "apply_url": opening.apply_url,
                            "source_type": opening.source_type,
                        })

                except Exception as comp_err:
                    errors_count += 1
                    logger.warning("Scrape failed for %s: %s", cname, comp_err)
                    await db.mark_company_failed(cname, str(comp_err))

            # Courtesy delay between mini-batches to respect 0.1 CPU on Render
            if i + batch_size < len(candidates):
                await asyncio.sleep(2.0)

        # 3. Check and send job alerts
        if all_detected_jobs:
            await check_and_send_alerts(db, all_detected_jobs)

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        _scrape_status["last_duration_seconds"] = duration
        _scrape_status["companies_scraped_last_run"] = scraped_count
        _scrape_status["total_jobs_detected_last_run"] = total_jobs
        _scrape_status["errors_last_run"] = errors_count
        _scrape_status["status_message"] = (
            f"Completed scrape: {scraped_count} companies, {total_jobs} active openings in {duration:.1f}s."
        )

        logger.info(
            "Scrape cycle finished in %.1fs: %d companies, %d jobs, %d errors",
            duration,
            scraped_count,
            total_jobs,
            errors_count,
        )

        return {
            "status": "completed",
            "companies_scraped": scraped_count,
            "jobs_detected": total_jobs,
            "errors": errors_count,
            "duration_seconds": duration,
        }

    except Exception as exc:
        logger.exception("Scrape cycle encountered unhandled error: %s", exc)
        _scrape_status["status_message"] = f"Scrape cycle error: {exc}"
        return {"status": "error", "message": str(exc)}
    finally:
        _scrape_status["is_running"] = False


def create_scheduler(db: DatabaseManager) -> AsyncIOScheduler:
    """Create and configure AsyncIOScheduler with 6-hour scrape cadence."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_scrape_cycle,
        "interval",
        hours=6,
        args=[db],
        id="goait_scrape_cycle",
        replace_existing=True,
    )
    return scheduler
