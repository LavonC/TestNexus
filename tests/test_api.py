"""
Comprehensive integration tests for FastAPI backend routers and endpoints.
"""

from __future__ import annotations

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


@pytest.mark.asyncio
async def test_rate_limit_middleware(app_with_db):
    """Verify that RateLimitMiddleware protects data and chat endpoints, while health check is exempt."""
    mock_agent = AsyncMock()
    mock_agent.ask = AsyncMock(return_value="pong")
    mock_agent.model_name = "gemini-3.8-flash"
    app_with_db.state.qa_agent = mock_agent

    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Health check should never be throttled
        for _ in range(15):
            resp = await client.get("/api/health")
            assert resp.status_code == 200

        # 2. Chat endpoint has a limit of 10 requests per minute
        for _ in range(10):
            await client.post("/api/chat", json={"question": "ping"})
        # 11th request should be rate-limited
        resp_429 = await client.post("/api/chat", json={"question": "ping"})
        assert resp_429.status_code == 429
        assert "Rate limit exceeded" in resp_429.json()["detail"]


@pytest.mark.asyncio
async def test_admin_seed_management(app_with_db, tmp_path: Path):
    """Verify admin seed CRUD operations (add, get, update, delete)."""
    from src.config import config

    headers = {"X-Admin-Secret": config.ADMIN_SECRET}
    dummy_seed_file = tmp_path / "companies_seed.json"
    dummy_seed_file.write_text("[]", encoding="utf-8")

    transport = ASGITransport(app=app_with_db)
    with patch.object(config, "SEED_FILE_PATH", dummy_seed_file):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Add company
            add_resp = await client.post(
                "/api/admin/seed",
                json={"name": "NewGoaTech", "website": "https://newgoa.tech"},
                headers=headers,
            )
            assert add_resp.status_code == 200
            assert "added to seed queue" in add_resp.json()["message"]

            # 2. Get seed list
            get_resp = await client.get("/api/admin/seed", headers=headers)
            assert get_resp.status_code == 200
            seeds = get_resp.json()
            assert any(s["name"] == "NewGoaTech" for s in seeds)

            # 3. Update company
            put_resp = await client.put(
                "/api/admin/seed/NewGoaTech",
                json={"careers": "https://newgoa.tech/careers"},
                headers=headers,
            )
            assert put_resp.status_code == 200
            assert "updated successfully" in put_resp.json()["message"]

            # 4. Delete company
            del_resp = await client.delete("/api/admin/seed/NewGoaTech", headers=headers)
            assert del_resp.status_code == 200
            assert "removed from seed list" in del_resp.json()["message"]


@pytest.mark.asyncio
async def test_turso_database_manager_integration(tmp_path: Path):
    """Deep integration test for DatabaseManager using Turso LibSQL client (via file: URL)."""
    db_file = tmp_path / "turso_integration.db"
    turso_url = f"file:{db_file}"

    db = DatabaseManager(turso_url=turso_url)
    assert db.is_turso is True

    try:
        # 1. init_db (must exercise both execute and context manager protocol)
        await db.init_db()

        # 2. seed_companies
        count = await db.seed_companies([
            {"name": "TursoCorp", "website": "https://tursocorp.com", "careers": "https://tursocorp.com/jobs"},
        ])
        assert count == 1

        # 3. save_company_intelligence_stateful
        intel = CompanyIntelligence(
            company_name="TursoCorp",
            core_domain="Cloud Databases",
            goa_office_locations=["Panaji"],
            primary_tech_stack=["Rust", "Python", "SQLite"],
            hiring_status="Actively Hiring",
            active_openings=[
                JobOpening(
                    title="Distributed Systems Engineer",
                    experience_level="Mid-Level",
                    tech_stack=["Rust", "LibSQL"],
                    is_computer_eng_relevant=True,
                    apply_url="https://tursocorp.com/jobs/1",
                ),
            ],
            summary_explanation="Edge-hosted SQLite compatible distributed database.",
        )
        await db.save_company_intelligence_stateful("TursoCorp", intel)

        # 4. stats
        stats = await db.get_stats()
        assert stats["total_companies"] == 1
        assert stats["completed"] == 1
        assert stats["total_openings"] == 1

        # 5. search_companies & search_job_openings
        comps = await db.search_companies(query="TursoCorp")
        assert len(comps) == 1
        assert comps[0]["company_name"] == "TursoCorp"

        jobs = await db.search_job_openings(query="Distributed")
        assert len(jobs) == 1
        assert jobs[0]["title"] == "Distributed Systems Engineer"

        # 6. job alerts
        alert_res = await db.create_job_alert("dev@turso.com", tech_filter=["Rust"])
        token = alert_res["unsubscribe_token"]
        assert token

        active_alerts = await db.get_active_alerts()
        assert len(active_alerts) == 1
        assert active_alerts[0]["email"] == "dev@turso.com"

        unsub_ok = await db.unsubscribe_alert(token)
        assert unsub_ok is True

        # 7. exports and suggestions
        suggestions = await db.get_search_suggestions("Dist")
        assert any("Distributed Systems Engineer" in s for s in suggestions)

        feed_jobs = await db.get_latest_jobs_for_feed(limit=5)
        assert len(feed_jobs) == 1

        csv_text = await db.export_jobs_csv()
        assert "Distributed Systems Engineer" in csv_text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_migrate_to_turso_integration(tmp_path: Path):
    """Test full SQLite -> Turso migration script with data verification and FTS5 rebuild."""
    from scripts.migrate_to_turso import migrate_to_turso

    src_sqlite = tmp_path / "source_sqlite.db"
    dest_turso_file = tmp_path / "dest_turso.db"
    dest_turso_url = f"file:{dest_turso_file}"

    # Prepare populated source database
    src_db = DatabaseManager(db_path=src_sqlite)
    await src_db.init_db()
    await src_db.seed_companies([{"name": "MigrateMe", "website": "https://migrate.com"}])
    await src_db.create_job_alert("alert@migrate.com", tech_filter=["Python"])
    await src_db.close()

    # Run migration script
    success = await migrate_to_turso(
        source_sqlite_path=src_sqlite,
        turso_url=dest_turso_url,
        turso_token="dummy_token",
    )
    assert success is True

    # Verify data on destination Turso database
    dest_db = DatabaseManager(turso_url=dest_turso_url)
    try:
        stats = await dest_db.get_stats()
        assert stats["total_companies"] == 1
        comps = await dest_db.search_companies(query="MigrateMe")
        assert len(comps) == 1
        alerts = await dest_db.get_active_alerts()
        assert len(alerts) == 1
    finally:
        await dest_db.close()
