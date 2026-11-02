"""
Comprehensive integration tests for FastAPI backend routers and endpoints.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.app import create_app
from src.database import DatabaseManager
from src.models import CompanyIntelligence, JobOpening


@pytest.fixture
async def app_with_db(tmp_path: Path):
    """Fixture providing a test FastAPI app configured with a populated temporary SQLite database."""
    db_file = tmp_path / "test_api_goa.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()

    # Seed sample companies
    seeds = [
        {"name": "Spintly", "website": "https://spintly.com", "careers": "https://spintly.com/careers"},
        {"name": "Codemax", "website": "https://codemax.in", "careers": "https://codemax.in/careers"},
        {"name": "Goa Public Service Commission", "website": "https://gpsc.goa.gov.in"},
    ]
    await db.seed_companies(seeds)

    # Save intelligence
    spintly_intel = CompanyIntelligence(
        company_name="Spintly",
        goa_office_locations=["Panaji"],
        core_domain="SaaS",
        primary_tech_stack=["Python", "FastAPI", "React"],
        hiring_status="Actively Hiring",
        active_openings=[
            JobOpening(
                title="Fresher Python Developer",
                experience_level="Fresher",
                tech_stack=["Python", "FastAPI"],
                is_computer_eng_relevant=True,
                apply_url="https://spintly.com/jobs/1",
            ),
            JobOpening(
                title="Senior C++ Engineer",
                experience_level="Senior",
                tech_stack=["C++", "FreeRTOS"],
                is_computer_eng_relevant=True,
                apply_url="https://spintly.com/jobs/2",
            ),
        ],
        application_contact_email="careers@spintly.com",
        summary_explanation="Builds smart IoT access solutions.",
    )
    await db.save_company_intelligence_stateful("Spintly", spintly_intel, seed=seeds[0])

    # Government job
    gpsc_intel = CompanyIntelligence(
        company_name="Goa Public Service Commission",
        goa_office_locations=["Panaji"],
        core_domain="Government Services",
        primary_tech_stack=["Govt Admin", "SQL"],
        hiring_status="Actively Hiring",
        active_openings=[
            JobOpening(
                title="Assistant Director of IT",
                department="Department of Information Technology",
                experience_level="3-5 years",
                tech_stack=["Database", "Networking"],
                is_computer_eng_relevant=True,
                source_type="PDF",
                source_url="https://gpsc.goa.gov.in/circular_01.pdf",
                application_deadline="2026-12-31",
                is_government=True,
            )
        ],
        summary_explanation="Government autonomous recruitment commission.",
    )
    await db.save_company_intelligence_stateful("Goa Public Service Commission", gpsc_intel, seed=seeds[2])

    test_app = create_app()
    test_app.state.db = db

    return test_app


@pytest.mark.asyncio
async def test_health_check_endpoint(app_with_db):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "timestamp" in data
        assert data["service"] == "goait-api"


@pytest.mark.asyncio
async def test_stats_and_trends_endpoints(app_with_db):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. /api/stats
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "pipeline" in data
        assert data["pipeline"]["total_companies"] == 3
        assert data["pipeline"]["completed"] == 2
        assert data["pipeline"]["total_openings"] == 3

        # 2. /api/stats/trends
        resp_trends = await client.get("/api/stats/trends")
        assert resp_trends.status_code == 200
        t_data = resp_trends.json()
        assert "trends" in t_data
        assert "top_companies" in t_data["trends"]
        assert "top_tech_stack" in t_data["trends"]
        assert "active_vs_closed" in t_data["trends"]


@pytest.mark.asyncio
async def test_companies_endpoints(app_with_db):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # List companies
        resp = await client.get("/api/companies")
        assert resp.status_code == 200
        comps = resp.json()
        assert len(comps) == 3
        names = [c["company_name"] for c in comps]
        assert "Spintly" in names

        # Filter by location
        resp_panaji = await client.get("/api/companies?location=Panaji")
        assert resp_panaji.status_code == 200
        assert len(resp_panaji.json()) >= 1

        # Profile endpoint
        resp_prof = await client.get("/api/companies/Spintly")
        assert resp_prof.status_code == 200
        prof = resp_prof.json()
        assert prof["company_name"] == "Spintly"
        assert len(prof["active_openings"]) == 2

        # 404 for unknown company
        resp_404 = await client.get("/api/companies/NonExistentCo")
        assert resp_404.status_code == 404

        # Compare endpoint
        resp_comp = await client.get("/api/companies/compare?names=Spintly,Codemax")
        assert resp_comp.status_code == 200
        comp_res = resp_comp.json()
        assert len(comp_res) >= 1


@pytest.mark.asyncio
async def test_jobs_endpoints(app_with_db):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # All active jobs
        resp = await client.get("/api/jobs")
        assert resp.status_code == 200
        jobs = resp.json()
        assert len(jobs) == 3

        # Fresher shortcut endpoint
        resp_fresher = await client.get("/api/jobs/freshers")
        assert resp_fresher.status_code == 200
        fresher_jobs = resp_fresher.json()
        assert len(fresher_jobs) == 1
        assert "Fresher" in fresher_jobs[0]["title"]

        # Government jobs endpoint
        resp_govt = await client.get("/api/jobs/govt")
        assert resp_govt.status_code == 200
        govt_jobs = resp_govt.json()
        assert len(govt_jobs) == 1
        assert "Assistant Director" in govt_jobs[0]["title"]


@pytest.mark.asyncio
async def test_job_alerts_subscription_and_unsubscribe(app_with_db):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Subscribe
        payload = {
            "email": "engineer@goa.dev",
            "tech_filter": ["Python", "FastAPI"],
            "location_filter": ["Panaji"],
            "ce_only": True,
        }
        resp = await client.post("/api/jobs/alerts", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "engineer@goa.dev"
        token = data["unsubscribe_token"]
        assert token

        # Unsubscribe
        resp_unsub = await client.get(f"/api/jobs/alerts/unsubscribe?token={token}")
        assert resp_unsub.status_code == 200
        assert resp_unsub.json()["status"] == "success"

        # Invalid token
        resp_bad = await client.get("/api/jobs/alerts/unsubscribe?token=nonexistent_token_123")
        assert resp_bad.status_code == 404


@pytest.mark.asyncio
async def test_exports_and_feeds(app_with_db):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Markdown digest
        resp_md = await client.get("/api/exports/digest.md")
        assert resp_md.status_code == 200
        assert "Spintly" in resp_md.text

        # JSON digest
        resp_json = await client.get("/api/exports/digest.json")
        assert resp_json.status_code == 200
        j_data = resp_json.json()
        assert "companies" in j_data

        # Jobs CSV
        resp_jcsv = await client.get("/api/exports/jobs.csv")
        assert resp_jcsv.status_code == 200
        assert "Fresher Python Developer" in resp_jcsv.text

        # Companies CSV
        resp_ccsv = await client.get("/api/exports/companies.csv")
        assert resp_ccsv.status_code == 200
        assert "Spintly" in resp_ccsv.text

        # Atom XML Feed
        resp_feed = await client.get("/api/feed/jobs.xml")
        assert resp_feed.status_code == 200
        assert "<feed" in resp_feed.text
        assert "Spintly" in resp_feed.text


@pytest.mark.asyncio
async def test_search_suggest(app_with_db):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/search/suggest?q=spin")
        assert resp.status_code == 200
        suggestions = resp.json()
        assert any("Spintly" in s for s in suggestions)


@pytest.mark.asyncio
async def test_admin_router_security_and_triggers(app_with_db):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Unauthorized without secret
        resp_unauth = await client.post("/api/admin/scrape")
        assert resp_unauth.status_code == 401

        # Authorized with X-Admin-Secret
        from src.config import config

        headers = {"X-Admin-Secret": config.ADMIN_SECRET}
        resp_auth = await client.post("/api/admin/scrape", headers=headers)
        assert resp_auth.status_code == 200
        assert resp_auth.json()["status"] == "triggered"

        # Scrape status
        resp_status = await client.get("/api/admin/scrape-status", headers=headers)
        assert resp_status.status_code == 200
        assert "is_running" in resp_status.json()


@pytest.mark.asyncio
async def test_chat_endpoint_offline_fallback(app_with_db):
    from src.config import config
    transport = ASGITransport(app=app_with_db)
    with patch.object(config, "GEMINI_API_KEY", ""), patch.object(config, "GEMINI_API_KEYS", ""), patch.dict("os.environ", {"GEMINI_API_KEY": "", "GEMINI_API_KEYS": ""}):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Query without API key falls back to offline database search
            resp = await client.post("/api/chat", json={"question": "Python jobs in Panaji"})
            assert resp.status_code == 200
            data = resp.json()
            assert "answer" in data
            assert "source" in data
            assert data["source"] in ("offline_db", "gemini_server")
