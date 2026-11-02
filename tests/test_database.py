"""
Unit tests for SQLite database CRUD, checkpointing, and digest exports.
"""

import json
from pathlib import Path

import pytest

from src.database import DatabaseManager
from src.models import CompanyIntelligence, JobOpening


@pytest.fixture
async def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_goa_companies.db"
    db_manager = DatabaseManager(db_path=db_file)
    await db_manager.init_db()
    return db_manager


@pytest.mark.asyncio
async def test_seed_and_checkpoint_resumption(temp_db: DatabaseManager):
    seeds = [
        {
            "name": "Company A",
            "website": "https://a.com",
            "careers": "https://a.com/careers",
            "rss": None,
        },
        {
            "name": "Company B",
            "website": "https://b.com",
            "careers": "https://b.com/careers",
            "rss": None,
        },
    ]

    # Initial seed
    inserted = await temp_db.seed_companies(seeds)
    assert inserted == 2

    # Check pending
    pending = await temp_db.get_pending_companies()
    assert len(pending) == 2
    assert pending[0]["status"] == "PENDING"

    # Mark Company A completed
    intel_a = CompanyIntelligence(
        company_name="Company A",
        goa_office_locations=["Verna"],
        core_domain="IoT",
        primary_tech_stack=["C++", "Python"],
        hiring_status="Actively Hiring",
        active_openings=[
            JobOpening(
                title="Firmware Engineer",
                department="Embedded",
                experience_level="1-3 years",
                tech_stack=["C++", "FreeRTOS"],
                is_computer_eng_relevant=True,
                apply_url="https://a.com/apply/1",
            )
        ],
        application_contact_email="careers@a.com",
        summary_explanation="Company A develops IoT sensors in Verna.",
    )
    await temp_db.save_company_intelligence("Company A", intel_a, seed=seeds[0])

    # Check pending after completion - Company A must be excluded
    pending_after = await temp_db.get_pending_companies()
    assert len(pending_after) == 1
    assert pending_after[0]["name"] == "Company B"

    # Re-seeding with reset=False must NOT overwrite Company A's COMPLETED status
    inserted_again = await temp_db.seed_companies(seeds, reset=False)
    assert inserted_again == 0

    pending_still = await temp_db.get_pending_companies()
    assert len(pending_still) == 1
    assert pending_still[0]["name"] == "Company B"

    # Reseeding with reset=True must re-queue Company A
    inserted_reset = await temp_db.seed_companies(seeds, reset=True)
    assert inserted_reset == 2
    pending_reset = await temp_db.get_pending_companies()
    assert len(pending_reset) == 2


@pytest.mark.asyncio
async def test_mark_failed_and_logging(temp_db: DatabaseManager):
    seeds = [{"name": "Fail Co", "website": "https://fail.com"}]
    await temp_db.seed_companies(seeds)

    await temp_db.mark_company_failed("Fail Co", "Connection timeout after 15s")

    companies = await temp_db.get_all_companies()
    fail_record = next(c for c in companies if c["company_name"] == "Fail Co")
    assert fail_record["status"] == "FAILED"
    assert "timeout" in fail_record["error_message"]

    # FAILED companies should still appear in pending queue to allow retries
    pending = await temp_db.get_pending_companies()
    assert any(c["name"] == "Fail Co" for c in pending)


@pytest.mark.asyncio
async def test_stats_and_digest_export(temp_db: DatabaseManager, tmp_path: Path):
    seeds = [
        {
            "name": "Spintly",
            "website": "https://spintly.com",
            "careers": "https://spintly.com/careers",
        },
        {
            "name": "Teknorix",
            "website": "https://teknorix.com",
            "careers": "https://teknorix.com/careers",
        },
    ]
    await temp_db.seed_companies(seeds)

    intel1 = CompanyIntelligence(
        company_name="Spintly",
        goa_office_locations=["Panaji"],
        core_domain="Smart Buildings",
        primary_tech_stack=["React", "Python"],
        hiring_status="Actively Hiring",
        active_openings=[
            JobOpening(
                title="Python Backend Engineer",
                experience_level="Mid-Level",
                tech_stack=["Python", "FastAPI", "Docker"],
                is_computer_eng_relevant=True,
                apply_url="https://spintly.keka.com/jobs/1",
            )
        ],
        application_contact_email="careers@spintly.com",
        summary_explanation="Spintly builds cloud IoT access in Panaji.",
    )
    await temp_db.save_company_intelligence("Spintly", intel1)

    stats = await temp_db.get_stats()
    assert stats["total_companies"] == 2
    assert stats["completed"] == 1
    assert stats["pending"] == 1
    assert stats["actively_hiring_companies"] == 1
    assert stats["total_openings"] == 1
    assert stats["ce_relevant_openings"] == 1

    # Export markdown
    md_out = tmp_path / "digest.md"
    await temp_db.export_markdown_digest(md_out)
    assert md_out.exists()
    content = md_out.read_text(encoding="utf-8")
    assert "Panaji" in content
    assert "Python Backend Engineer" in content
    assert "FastAPI" in content
    assert "Spintly" in content

    # Export JSON
    json_out = tmp_path / "digest.json"
    await temp_db.export_json_digest(json_out)
    assert json_out.exists()
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert "metadata" in data
    assert "companies" in data
    assert len(data["companies"]) == 2
