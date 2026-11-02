"""
Tests for Gemini Model 404 Resolution, Fast-Failing, Dynamic Cascading,
and Database Reset/Update functionalities.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.database import DatabaseManager
from src.gemini_agent import DatabaseQAAgent, GeminiIntelligenceAgent
from src.heuristic_extractor import build_offline_profile
from src.models import ScrapedData


@pytest.mark.asyncio
async def test_agent_fast_fails_on_404_without_retrying():
    """Verify that when a model throws 404 NOT_FOUND, the agent does not retry attempt 2,
    records the model in _unavailable_models, and cascades immediately."""
    agent = GeminiIntelligenceAgent(
        api_key="mock_key",
        model_name="gemini-2.5-flash",
        fallback_models=["gemini-3.8-flash"],
        rate_limit_rpm=600.0,
    )

    models_called = []

    async def mock_generate_content(model, contents, config=None):
        models_called.append(model)
        if model == "gemini-2.5-flash":
            raise Exception("404 NOT_FOUND. {'error': {'code': 404, 'message': 'This model models/gemini-2.5-flash is no longer available to new users.'}}")

        # Fallback model succeeds
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "company_name": "Goa Cloud Tech",
            "goa_office_locations": ["Panaji"],
            "core_domain": "Cloud Services",
            "primary_tech_stack": ["Python", "Docker"],
            "hiring_status": "Actively Hiring",
            "active_openings": [],
            "summary_explanation": "Extracted via gemini-3.8-flash fallback.",
        })
        return mock_resp

    agent.client.aio.models.generate_content = AsyncMock(side_effect=mock_generate_content)

    scraped = ScrapedData(
        company_name="Goa Cloud Tech",
        homepage_text="Official homepage of Goa Cloud Tech in Panaji, Goa.",
        careers_page_text="We build cloud infra.",
    )

    intel = await agent.extract_structured_intelligence("Goa Cloud Tech", scraped, "")

    assert intel.company_name == "Goa Cloud Tech"
    # gemini-2.5-flash was called EXACTLY ONCE (no retry attempt 2 on 404!)
    assert models_called.count("gemini-2.5-flash") == 1
    # Model was marked as unavailable
    assert "gemini-2.5-flash" in agent._unavailable_models
    # Fallback model was called
    assert "gemini-3.8-flash" in models_called

    # On a subsequent call, gemini-2.5-flash should not even be attempted
    models_called.clear()
    intel2 = await agent.extract_structured_intelligence("Goa Cloud Tech 2", scraped, "")
    assert intel2.company_name == "Goa Cloud Tech"
    assert "gemini-2.5-flash" not in models_called
    assert "gemini-3.8-flash" in models_called


@pytest.mark.asyncio
async def test_batch_extraction_fast_fails_on_404():
    """Verify batch extraction cascades immediately on 404 NOT_FOUND."""
    agent = GeminiIntelligenceAgent(
        api_key="mock_key",
        model_name="gemini-2.0-flash",
        fallback_models=["gemini-3.5-flash"],
        rate_limit_rpm=600.0,
    )

    models_called = []

    async def mock_generate_content(model, contents, config=None):
        models_called.append(model)
        if model == "gemini-2.0-flash":
            raise Exception("404 NOT_FOUND: models/gemini-2.0-flash is no longer available.")

        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "companies": [
                {
                    "company_name": "Batch Company A",
                    "goa_office_locations": ["Verna"],
                    "core_domain": "Embedded Systems",
                    "primary_tech_stack": ["C++", "RTOS"],
                    "hiring_status": "No Listed Openings",
                    "active_openings": [],
                    "summary_explanation": "Extracted via batch.",
                }
            ]
        })
        return mock_resp

    agent.client.aio.models.generate_content = AsyncMock(side_effect=mock_generate_content)

    sdata = ScrapedData(
        company_name="Batch Company A",
        homepage_text="Embedded tech company located in Verna Industrial Estate.",
        careers_page_text="",
    )
    items = [("Batch Company A", sdata, "")]

    res = await agent.extract_batch_structured_intelligence(items)
    assert len(res) == 1
    assert res[0].company_name == "Batch Company A"
    assert models_called.count("gemini-2.0-flash") == 1
    assert "gemini-2.0-flash" in agent._unavailable_models
    assert "gemini-3.5-flash" in models_called


@pytest.mark.asyncio
async def test_qa_agent_handles_404_and_excludes_model():
    """Verify DatabaseQAAgent records 404 models and cascades."""
    mock_db = MagicMock(spec=DatabaseManager)
    qa_agent = DatabaseQAAgent(
        db_manager=mock_db,
        api_key="mock_key",
        model_name="gemini-1.5-flash",
        fallback_models=["gemini-3.8-flash"],
    )

    models_called = []

    async def mock_init_chat(model):
        models_called.append(model)
        if model == "gemini-1.5-flash":
            raise Exception("404 NOT_FOUND: models/gemini-1.5-flash is not found for API version v1beta")

        mock_chat = AsyncMock()
        resp = MagicMock()
        resp.text = "Answer from gemini-3.8-flash"
        mock_chat.send_message.return_value = resp
        qa_agent._chat = mock_chat

    qa_agent.init_chat = AsyncMock(side_effect=mock_init_chat)

    answer = await qa_agent.ask("What companies in Goa use Python?")
    assert "Answer from gemini-3.8-flash" in answer
    assert models_called.count("gemini-1.5-flash") == 1
    assert "gemini-1.5-flash" in qa_agent._unavailable_models


@pytest.mark.asyncio
async def test_database_reset_failed(tmp_path):
    """Verify reset_failed resets FAILED and IN_PROGRESS companies to PENDING."""
    db_file = tmp_path / "test_goa.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()

    # Seed 3 companies
    seeds = [
        {"name": "Co A", "website": "https://a.com", "careers": None, "rss": None},
        {"name": "Co B", "website": "https://b.com", "careers": None, "rss": None},
        {"name": "Co C", "website": "https://c.com", "careers": None, "rss": None},
    ]
    await db.seed_companies(seeds)

    # Mark Co A as FAILED, Co B as IN_PROGRESS, Co C as COMPLETED
    await db.mark_company_failed("Co A", "429 Quota exhausted")
    await db.mark_in_progress("Co B")

    stats_before = await db.get_stats()
    assert stats_before["failed"] == 1
    assert stats_before["in_progress"] == 1

    # Reset failed and in_progress
    count = await db.reset_failed(include_in_progress=True)
    assert count == 2

    stats_after = await db.get_stats()
    assert stats_after["failed"] == 0
    assert stats_after["in_progress"] == 0
    assert stats_after["pending"] == 3


@pytest.mark.asyncio
async def test_database_update_company_urls(tmp_path):
    """Verify update_company_urls updates canonical URLs and does not overwrite COMPLETED."""
    db_file = tmp_path / "test_urls.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()

    await db.seed_companies([
        {"name": "Intuio", "website": "https://www.intuio.io", "careers": "https://www.intuio.io/careers", "rss": None},
        {"name": "CompletedCo", "website": "https://comp.com", "careers": None, "rss": None},
    ])

    await db.update_company_urls(company_name="CompletedCo", status="COMPLETED")

    await db.update_company_urls(
        company_name="Intuio",
        website="https://intuio.io/",
        careers="https://intuio.io/careers-new",
    )

    # Attempt to set FAILED status on CompletedCo via URL sync
    await db.update_company_urls(
        company_name="CompletedCo",
        website="https://comp-redirect.com",
        status="FAILED",
        error_message="Domain dead",
    )

    all_comps = await db.get_all_companies()
    intuio = next(c for c in all_comps if c["company_name"] == "Intuio")
    assert intuio["website_url"] == "https://intuio.io/"
    assert intuio["careers_url"] == "https://intuio.io/careers-new"

    comp = next(c for c in all_comps if c["company_name"] == "CompletedCo")
    assert comp["website_url"] == "https://comp-redirect.com"
    # Status MUST remain COMPLETED!
    assert comp["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_get_pending_companies_filters_failed_when_specified(tmp_path):
    """Verify get_pending_companies returns FAILED companies by default for retry, and excludes them when include_failed=False."""
    db_file = tmp_path / "test_pending.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()

    await db.seed_companies([
        {"name": "PendingCo", "website": "https://p.com", "careers": None, "rss": None},
        {"name": "FailedCo", "website": "https://f.com", "careers": None, "rss": None},
    ])
    await db.mark_company_failed("FailedCo", "HTTP 500 error")

    # Default: includes FAILED so runs can retry failed companies
    pending_default = await db.get_pending_companies()
    names_default = [c["name"] for c in pending_default]
    assert "PendingCo" in names_default
    assert "FailedCo" in names_default

    # With include_failed=False: excludes FAILED
    pending_only = await db.get_pending_companies(include_failed=False)
    names_only = [c["name"] for c in pending_only]
    assert "PendingCo" in names_only
    assert "FailedCo" not in names_only


def test_heuristic_profile_no_fake_openings_on_dead_careers_even_with_internal_links():
    """Verify build_offline_profile does not invent dummy openings when careers page 404s,
    even if the homepage has internal navigation links like '[Careers](https://intuio.io/careers)'."""
    dead_careers_scrape = ScrapedData(
        company_name="Intuio Labs",
        homepage_text="Software consulting studio in Miramar, Goa. Contact: careers@intuio.io",
        careers_page_text="HTTP 404 Not Found",
        careers_fetch_failed=True,
        ats_links=["[Careers](https://intuio.io/careers)", "[Jobs](https://intuio.io/jobs)"],
    )
    seed = {
        "name": "Intuio Labs",
        "website": "https://intuio.io",
        "careers": "https://intuio.io/careers",
    }

    profile = build_offline_profile("Intuio Labs", dead_careers_scrape, seed=seed)
    # Must NOT create fake active openings for dead internal career links
    assert len(profile.active_openings) == 0
    assert profile.hiring_status == "Open Applications Only"  # because careers email is present
    assert profile.application_contact_email == "careers@intuio.io"


def test_heuristic_profile_accepts_verified_external_ats():
    """Verify build_offline_profile accepts verified external ATS links like Keka and extracts clean URL."""
    ats_scrape = ScrapedData(
        company_name="Verna Embedded",
        homepage_text="Embedded tech company in Verna, Goa.",
        careers_page_text="",
        careers_fetch_failed=False,
        ats_links=["[Careers Portal](https://vernaembedded.keka.com/careers)"],
    )

    profile = build_offline_profile("Verna Embedded", ats_scrape)
    assert profile.hiring_status == "Actively Hiring"
    assert len(profile.active_openings) == 1
    assert profile.active_openings[0].apply_url == "https://vernaembedded.keka.com/careers"


@pytest.mark.asyncio
async def test_quota_exhausted_models_deprioritized():
    """Verify that models encountering 429 quota exhaustion are remembered and deprioritized
    so subsequent calls do not repeat the failing model attempts."""
    agent = GeminiIntelligenceAgent(
        api_key="mock_key",
        model_name="gemini-3.8-flash",
        fallback_models=["gemini-3.5-flash-lite"],
        rate_limit_rpm=600.0,
    )

    call_counts = {"gemini-3.8-flash": 0, "gemini-3.5-flash-lite": 0}

    async def mock_generate_content(model, contents, config=None):
        call_counts[model] = call_counts.get(model, 0) + 1
        if model == "gemini-3.8-flash":
            raise Exception("429 RESOURCE_EXHAUSTED. Quota exceeded for metric: free_tier_requests, limit: 20")

        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "company_name": "Test Co",
            "goa_office_locations": ["Panaji"],
            "core_domain": "Cloud",
            "primary_tech_stack": ["Python"],
            "hiring_status": "Actively Hiring",
            "active_openings": [],
            "summary_explanation": "Extracted via lite model.",
        })
        return mock_resp

    agent.client.aio.models.generate_content = AsyncMock(side_effect=mock_generate_content)

    sdata = ScrapedData(company_name="Test Co", homepage_text="Cloud tech company in Panaji", careers_page_text="Hiring")

    # Call 1: 3.8-flash fails with 429, cascades to 3.5-flash-lite
    await agent.extract_structured_intelligence("Test Co", sdata, "")
    assert call_counts["gemini-3.8-flash"] == 1
    assert call_counts["gemini-3.5-flash-lite"] == 1
    assert "gemini-3.8-flash" in agent._quota_exhausted_models

    # Call 2: On next call, 3.5-flash-lite is prioritized FIRST, 3.8-flash is NOT called!
    call_counts["gemini-3.8-flash"] = 0
    call_counts["gemini-3.5-flash-lite"] = 0
    await agent.extract_structured_intelligence("Test Co 2", sdata, "")
    assert call_counts["gemini-3.8-flash"] == 0
    assert call_counts["gemini-3.5-flash-lite"] == 1
