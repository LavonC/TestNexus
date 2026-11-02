"""
Unit tests for historical job tracking and stateful upsert (never deleting vanished jobs).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.database import DatabaseManager
from src.models import CompanyIntelligence, JobOpening


@pytest.fixture
async def test_db(tmp_path: Path):
    db_file = tmp_path / "test_historical.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()
    await db.seed_companies([
        {
            "name": "Spintly",
            "website": "https://spintly.com",
            "careers": "https://spintly.com/careers",
            "rss": None,
        }
    ])
    return db


@pytest.mark.asyncio
async def test_stateful_upsert_preserves_history(test_db: DatabaseManager, tmp_path: Path):
    # 1. Run 1: Ingest Job A and Job B
    intel_run1 = CompanyIntelligence(
        company_name="Spintly",
        goa_office_locations=["Verna"],
        core_domain="SaaS / IoT",
        primary_tech_stack=["Python", "React"],
        hiring_status="Actively Hiring",
        active_openings=[
            JobOpening(
                title="Python Backend Engineer",
                department="Engineering",
                experience_level="1-3 years",
                tech_stack=["Python", "FastAPI"],
                is_computer_eng_relevant=True,
                apply_url="https://spintly.com/careers/py",
            ),
            JobOpening(
                title="Frontend React Developer",
                department="Engineering",
                experience_level="Mid-Level",
                tech_stack=["React", "TypeScript"],
                is_computer_eng_relevant=True,
                apply_url="https://spintly.com/careers/react",
            ),
        ],
    )
    await test_db.save_company_intelligence_stateful("Spintly", intel_run1)

    # Verify both jobs active in Run 1
    active_run1 = await test_db.search_job_openings(active_only=True)
    assert len(active_run1) == 2
    for j in active_run1:
        assert j["is_active"] == 1
        assert j["first_seen_at"] != ""
        assert j["last_seen_at"] != ""
        assert j["closed_at"] is None

    first_seen_py = next(j["first_seen_at"] for j in active_run1 if "Python" in j["title"])

    # Small sleep so timestamps advance
    await asyncio.sleep(0.05)

    # 2. Run 2: Job B is omitted (closed), Job A persists, Job C is new
    intel_run2 = CompanyIntelligence(
        company_name="Spintly",
        goa_office_locations=["Verna"],
        core_domain="SaaS / IoT",
        primary_tech_stack=["Python", "React", "C++"],
        hiring_status="Actively Hiring",
        active_openings=[
            JobOpening(
                title="Python Backend Engineer",  # Existing, refreshed
                department="Platform Engineering",
                experience_level="2-4 years",
                tech_stack=["Python", "FastAPI", "Docker"],
                is_computer_eng_relevant=True,
                apply_url="https://spintly.com/careers/py",
            ),
            JobOpening(
                title="Embedded C++ Developer",  # Brand new
                department="Firmware",
                experience_level="Fresher",
                tech_stack=["C++", "RTOS"],
                is_computer_eng_relevant=True,
                apply_url="https://spintly.com/careers/cpp",
            ),
        ],
    )
    await test_db.save_company_intelligence_stateful("Spintly", intel_run2)

    # Verify active jobs in Run 2: should be 2 (Python and C++)
    active_run2 = await test_db.search_job_openings(active_only=True)
    assert len(active_run2) == 2
    active_titles = {j["title"] for j in active_run2}
    assert "Python Backend Engineer" in active_titles
    assert "Embedded C++ Developer" in active_titles
    assert "Frontend React Developer" not in active_titles

    # Verify historical records in DB: ALL 3 jobs must be preserved!
    all_jobs = await test_db.search_job_openings(include_historical=True)
    assert len(all_jobs) == 3
    all_by_title = {j["title"]: j for j in all_jobs}

    # Job A (Python)
    job_py = all_by_title["Python Backend Engineer"]
    assert job_py["is_active"] == 1
    assert job_py["first_seen_at"] == first_seen_py  # First seen preserved!
    assert job_py["closed_at"] is None
    assert job_py["department"] == "Platform Engineering"

    # Job B (React) - marked closed!
    job_react = all_by_title["Frontend React Developer"]
    assert job_react["is_active"] == 0
    assert job_react["closed_at"] is not None
    assert len(job_react["closed_at"]) > 5

    # Job C (C++) - new active
    job_cpp = all_by_title["Embedded C++ Developer"]
    assert job_cpp["is_active"] == 1
    assert job_cpp["closed_at"] is None

    # Stats validation
    stats = await test_db.get_stats()
    assert stats["total_openings"] == 2  # active only
    assert stats["total_historical_openings"] == 3

    # Verify Markdown digest excludes closed jobs from active roles
    md_file = tmp_path / "test_digest.md"
    await test_db.export_markdown_digest(md_file)
    md_content = md_file.read_text(encoding="utf-8")
    assert "Python Backend Engineer" in md_content
    assert "Embedded C++ Developer" in md_content
    # Closed job B must NOT be in active listings
    assert "Frontend React Developer" not in md_content

    # Verify JSON digest attaches active openings only to active_openings
    json_file = tmp_path / "test_digest.json"
    await test_db.export_json_digest(json_file)
    import json
    json_data = json.loads(json_file.read_text(encoding="utf-8"))
    comp = next(c for c in json_data["companies"] if c["company_name"] == "Spintly")
    assert len(comp["active_openings"]) == 2
    assert {j["title"] for j in comp["active_openings"]} == {"Python Backend Engineer", "Embedded C++ Developer"}
    assert len(comp["historical_openings"]) == 3
