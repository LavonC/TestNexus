"""
Exports and RSS/Atom feed router.
Provides downloadable digests (Markdown, JSON), tabular CSVs, and an Atom RSS feed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from src.database import DatabaseManager

router = APIRouter(prefix="", tags=["Exports & Feeds"])


@router.get("/api/exports/digest.md", summary="Download Markdown intelligence digest")
async def export_markdown(request: Request) -> Response:
    """Generate and return full Markdown intelligence digest."""
    db: DatabaseManager = request.app.state.db
    path = await db.export_markdown_digest()
    content = path.read_text(encoding="utf-8")
    return PlainTextResponse(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="goa_tech_digest.md"'},
    )


@router.get("/api/exports/digest.json", summary="Download JSON intelligence digest")
async def export_json(request: Request) -> Response:
    """Generate and return full JSON intelligence digest."""
    db: DatabaseManager = request.app.state.db
    path = await db.export_json_digest()
    content = path.read_text(encoding="utf-8")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="goa_tech_digest.json"'},
    )


@router.get("/api/exports/jobs.csv", summary="Download active job openings as CSV")
async def export_jobs_csv(request: Request) -> Response:
    """Generate and return CSV file of active job openings."""
    db: DatabaseManager = request.app.state.db
    csv_text = await db.export_jobs_csv()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="goa_jobs.csv"'},
    )


@router.get("/api/exports/companies.csv", summary="Download company directory as CSV")
async def export_companies_csv(request: Request) -> Response:
    """Generate and return CSV file of monitored Goan tech companies."""
    db: DatabaseManager = request.app.state.db
    csv_text = await db.export_companies_csv()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="goa_companies.csv"'},
    )


@router.get("/api/feed/jobs.xml", summary="RSS / Atom XML feed of newly detected jobs")
async def get_rss_feed(request: Request) -> Response:
    """Generate an Atom XML feed of the latest 50 job openings."""
    db: DatabaseManager = request.app.state.db
    jobs = await db.get_latest_jobs_for_feed(limit=50)

    now_iso = datetime.now(timezone.utc).isoformat()
    feed_items = []
    for j in jobs:
        title = escape(j.get("title") or "Job Opening")
        comp = escape(j.get("company_name") or "Goa Tech Company")
        url = escape(j.get("apply_url") or "")
        job_id = j.get("id") or "0"
        detected = j.get("first_seen_at") or j.get("detected_at") or now_iso
        tech_list = j.get("tech_stack", [])
        tech_str = escape(", ".join(tech_list) if isinstance(tech_list, list) else str(tech_list))

        item_xml = f"""
    <entry>
        <title>{title} at {comp}</title>
        <id>tag:goait.dev,2026:job-{job_id}</id>
        <updated>{detected}</updated>
        <link href="{url or 'https://goait.dev'}" />
        <summary>Role: {title} | Company: {comp} | Tech: {tech_str} | Exp: {escape(j.get('experience_level', 'Any'))}</summary>
    </entry>"""
        feed_items.append(item_xml)

    atom_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
    <title>GoaIT - Goan Tech &amp; Engineering Job Openings</title>
    <subtitle>Continuous career intelligence feed for Goan engineering professionals</subtitle>
    <link href="https://goait.dev/api/feed/jobs.xml" rel="self" />
    <link href="https://goait.dev" />
    <updated>{now_iso}</updated>
    <id>tag:goait.dev,2026:jobs-feed</id>
    {''.join(feed_items)}
</feed>"""

    return Response(content=atom_xml, media_type="application/atom+xml")
