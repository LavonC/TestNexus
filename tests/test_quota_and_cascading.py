"""
Comprehensive unit and integration tests for free-tier quota circumvention:
1. Model selection & tier cascading on 429
2. Multi-API-key rotation on quota exhaustion
3. Adaptive rate limiting (respecting 15 RPM)
4. Batch company extraction bundling (5-10 companies per request)
5. Local hybrid heuristic pre-extraction (emails, Goa locations, tech stack)
6. Dead/unreachable site offline-first profile without LLM calls
7. Local LLM (Ollama) fallback client
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gemini_agent import GeminiIntelligenceAgent
from src.heuristic_extractor import (
    build_offline_profile,
    extract_emails,
    extract_goa_locations,
    extract_tech_stack,
    is_site_unreachable,
)
from src.key_rotator import KeyRotator
from src.local_llm import LocalLLMClient
from src.models import CompanyIntelligence, JobOpening, ScrapedData
from src.rate_limiter import AsyncRateLimiter

# ==============================================================================
# 1. HEURISTIC PRE-EXTRACTION TESTS
# ==============================================================================

def test_heuristic_extract_emails():
    text = (
        "Contact our team at careers@spintly.com or hr@spintly.com. "
        "General inquiries: info@spintly.com. "
        "Ignore image asset logo@2x.png and sample test@example.com."
    )
    emails = extract_emails(text)
    assert "careers@spintly.com" in emails
    assert "hr@spintly.com" in emails
    assert "info@spintly.com" in emails
    # Check invalid extensions and test domains are filtered
    assert not any(e.endswith(".png") for e in emails)
    assert not any("example.com" in e for e in emails)
    # Check prioritization: careers/hr comes before info
    assert emails.index("careers@spintly.com") < emails.index("info@spintly.com")


def test_heuristic_extract_goa_locations():
    text = (
        "We are based in Verna Industrial Estate, Goa with a branch office in Panjim "
        "and another team meeting near Margao and Porvorim."
    )
    locations = extract_goa_locations(text)
    assert "Verna" in locations
    assert "Panaji" in locations  # Normalized from Panjim
    assert "Margao" in locations
    assert "Porvorim" in locations


def test_heuristic_extract_tech_stack():
    text = (
        "We build high performance cloud services using Python, FastAPI, and PostgreSQL. "
        "Our frontend is built with React and TypeScript. "
        "We also do Embedded firmware in C++ and Go, running on AWS with Docker."
    )
    tech = extract_tech_stack(text)
    assert "Python" in tech
    assert "FastAPI" in tech
    assert "PostgreSQL" in tech
    assert "React" in tech
    assert "TypeScript" in tech
    assert "C++" in tech
    assert "Go" in tech
    assert "AWS" in tech
    assert "Docker" in tech
    assert "Embedded" in tech


def test_is_site_unreachable_detection():
    # Dead / DNS failed site (like Innvion System)
    dead_scrape = ScrapedData(
        company_name="Innvion System",
        homepage_text="Failed to fetch http://innvionsystem.com: [Errno 11001] getaddrinfo failed",
        careers_page_text="Failed to fetch http://innvionsystem.com/careers: [Errno 11001] getaddrinfo failed",
        careers_fetch_failed=True,
    )
    assert is_site_unreachable(dead_scrape) is True

    # Reachable site with content
    valid_scrape = ScrapedData(
        company_name="Active Co",
        homepage_text="Welcome to Active Co! We build scalable cloud solutions for enterprises. Our office is located in Verna, Goa.",
        careers_page_text="We are looking for talented developers to join our growing engineering team.",
        careers_fetch_failed=False,
    )
    assert is_site_unreachable(valid_scrape) is False

    # Site with ATS links is never marked unreachable
    ats_scrape = ScrapedData(
        company_name="ATS Co",
        homepage_text="Failed to fetch homepage",
        careers_page_text="",
        ats_links=["https://keka.com/atsco"],
        careers_fetch_failed=True,
    )
    assert is_site_unreachable(ats_scrape) is False


def test_build_offline_profile_sensible_defaults():
    dead_scrape = ScrapedData(
        company_name="Dead Tech Goa",
        homepage_text="Failed to fetch",
        careers_page_text="HTTP 404 Error",
        careers_fetch_failed=True,
    )
    profile = build_offline_profile("Dead Tech Goa", dead_scrape)
    assert isinstance(profile, CompanyIntelligence)
    assert profile.company_name == "Dead Tech Goa"
    assert "Goa" in profile.goa_office_locations
    assert profile.hiring_status == "Unknown"
    assert "offline" in profile.summary_explanation.lower() or "unreachable" in profile.summary_explanation.lower()


# ==============================================================================
# 2. KEY ROTATION TESTS
# ==============================================================================

def test_key_rotator_basic_and_rotation():
    rotator = KeyRotator("key_1, key_2, key_3")
    assert rotator.total_keys == 3
    assert rotator.get_current_key() == "key_1"

    # Rotate to next
    next_key = rotator.rotate_key()
    assert next_key == "key_2"
    assert rotator.get_current_key() == "key_2"


def test_key_rotator_exhaustion():
    rotator = KeyRotator(["key_a", "key_b"])
    assert rotator.has_available_keys() is True

    # Mark key_a exhausted
    next_key = rotator.mark_key_exhausted("key_a", "429 Quota Exceeded")
    assert next_key == "key_b"
    assert rotator.get_current_key() == "key_b"
    assert "key_a" in rotator.exhausted_keys

    # Mark key_b exhausted
    exhausted_result = rotator.mark_key_exhausted("key_b", "429 Quota Exceeded")
    assert exhausted_result is None
    assert rotator.has_available_keys() is False
    assert rotator.all_exhausted() is True

    # Reset
    rotator.reset()
    assert rotator.has_available_keys() is True
    assert rotator.get_current_key() == "key_a"


# ==============================================================================
# 3. RATE LIMITING TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_async_rate_limiter_interval():
    # 600 RPM = 0.1s interval
    limiter = AsyncRateLimiter(requests_per_minute=600.0)
    assert limiter.interval == 0.1

    start = time.monotonic()
    await limiter.acquire()
    waited = await limiter.acquire()
    elapsed = time.monotonic() - start

    assert elapsed >= 0.09
    assert waited > 0.0


# ==============================================================================
# 4. MODEL TIER CASCADING ON 429
# ==============================================================================

@pytest.mark.asyncio
async def test_model_cascades_on_429():
    """Verify that when the primary model returns 429 RESOURCE_EXHAUSTED, the agent cascades to fallback model."""
    agent = GeminiIntelligenceAgent(
        api_key="mock_key",
        model_name="gemini-2.5-flash",
        fallback_models=["gemini-2.0-flash", "gemini-1.5-flash"],
        rate_limit_rpm=600.0,
    )

    models_called = []

    async def mock_generate_content(model, contents, config=None):
        models_called.append(model)
        if model == "gemini-2.5-flash":
            raise Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for metric: generate_content_free_tier_requests")
        # Fallback model succeeds
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "company_name": "Cascading Co",
            "goa_office_locations": ["Verna"],
            "core_domain": "Cloud Software",
            "primary_tech_stack": ["Python", "FastAPI"],
            "hiring_status": "Actively Hiring",
            "active_openings": [],
            "summary_explanation": "Extracted via fallback model.",
        })
        return mock_resp

    agent.client.aio.models.generate_content = AsyncMock(side_effect=mock_generate_content)

    scraped = ScrapedData(
        company_name="Cascading Co",
        homepage_text="Valid homepage text for Cascading Co in Verna Goa with lots of details.",
        careers_page_text="Join our engineering team in Verna.",
        ats_links=["https://keka.com/cascadingco"],
    )

    intel = await agent.extract_structured_intelligence(
        "Cascading Co", scraped, "Search notes"
    )

    assert intel.company_name == "Cascading Co"
    assert intel.core_domain == "Cloud Software"
    # Primary model gemini-2.5-flash failed with 429, so gemini-2.0-flash was called
    assert "gemini-2.5-flash" in models_called
    assert "gemini-2.0-flash" in models_called


# ==============================================================================
# 5. BATCH COMPANY EXTRACTION TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_extract_batch_structured_intelligence():
    """Verify bundling multiple companies into a single request collapses LLM calls."""
    agent = GeminiIntelligenceAgent(
        api_key="mock_key",
        model_name="gemini-2.5-flash",
        rate_limit_rpm=600.0,
    )

    batch_output = {
        "companies": [
            {
                "company_name": "Company Alpha",
                "goa_office_locations": ["Panaji"],
                "core_domain": "FinTech",
                "primary_tech_stack": ["Java", "Spring Boot"],
                "hiring_status": "Actively Hiring",
                "active_openings": [
                    {
                        "title": "Java Dev",
                        "department": "Engineering",
                        "experience_level": "Mid",
                        "tech_stack": ["Java"],
                        "is_computer_eng_relevant": True,
                        "apply_url": "https://alpha.com/jobs/1",
                    }
                ],
                "summary_explanation": "Fintech in Panaji.",
            },
            {
                "company_name": "Company Beta",
                "goa_office_locations": ["Margao"],
                "core_domain": "Industrial IoT",
                "primary_tech_stack": ["C++", "Qt"],
                "hiring_status": "No Listed Openings",
                "active_openings": [],
                "summary_explanation": "IoT in Margao.",
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(batch_output)

    mock_generate = AsyncMock(return_value=mock_resp)
    agent.client.aio.models.generate_content = mock_generate

    batch_items = [
        (
            "Company Alpha",
            ScrapedData(
                company_name="Company Alpha",
                homepage_text="Alpha fintech homepage with details",
                careers_page_text="Hiring Java devs",
                ats_links=["https://alpha.com/jobs/1"],
            ),
            "Notes Alpha",
        ),
        (
            "Company Beta",
            ScrapedData(
                company_name="Company Beta",
                homepage_text="Beta IoT homepage with details",
                careers_page_text="No current roles",
            ),
            "Notes Beta",
        ),
    ]

    results = await agent.extract_batch_structured_intelligence(batch_items)

    # 1 LLM request processed both companies
    mock_generate.assert_called_once()
    assert len(results) == 2
    assert results[0].company_name == "Company Alpha"
    assert results[0].core_domain == "FinTech"
    assert len(results[0].active_openings) == 1

    assert results[1].company_name == "Company Beta"
    assert results[1].core_domain == "Industrial IoT"
    assert results[1].hiring_status == "No Listed Openings"


# ==============================================================================
# 6. LOCAL LLM FALLBACK TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_local_llm_client_mock():
    client = LocalLLMClient(base_url="http://localhost:11434", model="llama3.2")

    mock_json = json.dumps({
        "company_name": "Local Extracted Co",
        "goa_office_locations": ["Verna"],
        "core_domain": "Robotics",
        "primary_tech_stack": ["ROS", "Python"],
        "hiring_status": "Actively Hiring",
        "active_openings": [],
        "summary_explanation": "Extracted via local Ollama LLM.",
    })

    with patch.object(client, "_call_ollama_or_openai", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = f"```json\n{mock_json}\n```"

        scraped = ScrapedData(
            company_name="Local Extracted Co",
            homepage_text="Robotics company text",
        )
        intel = await client.extract_structured_intelligence("Local Extracted Co", scraped)

        assert intel.company_name == "Local Extracted Co"
        assert intel.core_domain == "Robotics"
        assert intel.goa_locations == ["Verna"]


@pytest.mark.asyncio
async def test_gemini_agent_rotates_api_keys_on_429():
    """Verify that agent rotates to next API key when 429 is encountered on the active key."""
    agent = GeminiIntelligenceAgent(
        api_keys=["key_first", "key_second"],
        model_name="gemini-2.5-flash",
        rate_limit_rpm=600.0,
    )

    attempt_count = 0

    async def mock_generate_content(model, contents, config=None):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            raise Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for metric: generate_content_free_tier_requests")

        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "company_name": "Key Rotation Co",
            "goa_office_locations": ["Panaji"],
            "core_domain": "Cloud Solutions",
            "primary_tech_stack": ["Go", "Docker"],
            "hiring_status": "Actively Hiring",
            "active_openings": [],
            "summary_explanation": "Extracted with rotated key.",
        })
        return mock_resp

    agent.client.aio.models.generate_content = AsyncMock(side_effect=mock_generate_content)

    scraped = ScrapedData(
        company_name="Key Rotation Co",
        homepage_text="Homepage text for Key Rotation Co in Panaji with details",
        careers_page_text="Careers text here",
        ats_links=["https://keyco.keka.com"],
    )

    intel = await agent.extract_structured_intelligence("Key Rotation Co", scraped, "Search notes")

    assert intel.company_name == "Key Rotation Co"
    assert intel.core_domain == "Cloud Solutions"
    assert attempt_count == 2
    # Verify key_first is marked exhausted and active key is key_second
    assert "key_first" in agent.key_rotator.exhausted_keys


@pytest.mark.asyncio
async def test_orchestrator_batch_mode_execution(tmp_path):
    """Test PipelineOrchestrator running in batch mode (batch_size=2)."""
    from src.database import DatabaseManager
    from src.main import PipelineOrchestrator

    db_file = tmp_path / "batch_test.db"
    db_manager = DatabaseManager(db_path=db_file)
    await db_manager.init_db()

    seeds = [
        {"name": "Batch Co 1", "website": "https://b1.com", "careers": "https://b1.com/careers"},
        {"name": "Batch Co 2", "website": "https://b2.com", "careers": "https://b2.com/careers"},
    ]
    await db_manager.seed_companies(seeds)

    orchestrator = PipelineOrchestrator(
        db_manager=db_manager,
        concurrency=2,
        batch_size=2,
        api_key="mock_key",
    )

    mock_scraped1 = ScrapedData(company_name="Batch Co 1", homepage_text="B1 home text with details", ats_links=["https://b1.com/a1"])
    mock_scraped2 = ScrapedData(company_name="Batch Co 2", homepage_text="B2 home text with details", ats_links=["https://b2.com/a2"])

    mock_intel1 = CompanyIntelligence(
        company_name="Batch Co 1",
        goa_office_locations=["Verna"],
        core_domain="SaaS",
        primary_tech_stack=["Python"],
        hiring_status="Actively Hiring",
        active_openings=[JobOpening(title="Python Dev", tech_stack=["Python"])],
        summary_explanation="B1 explanation.",
    )
    mock_intel2 = CompanyIntelligence(
        company_name="Batch Co 2",
        goa_office_locations=["Panaji"],
        core_domain="Automation",
        primary_tech_stack=["C++"],
        hiring_status="Actively Hiring",
        active_openings=[JobOpening(title="C++ Dev", tech_stack=["C++"])],
        summary_explanation="B2 explanation.",
    )

    with (
        patch.object(orchestrator.scraper, "scrape_company") as mock_scrape,
        patch.object(orchestrator.gemini, "analyze_batch") as mock_analyze_batch,
    ):
        mock_scrape.side_effect = [mock_scraped1, mock_scraped2]
        mock_analyze_batch.return_value = [("Batch Co 1", mock_intel1), ("Batch Co 2", mock_intel2)]

        await orchestrator.run(batch_size=2)

        stats = await db_manager.get_stats()
        assert stats["completed"] == 2
        assert stats["pending"] == 0
        assert stats["total_openings"] == 2
        mock_analyze_batch.assert_called_once()


@pytest.mark.asyncio
async def test_multi_key_rotation_past_two_keys():
    """Verify that agent with >2 keys continues rotating past attempt 2 until a valid key succeeds."""
    agent = GeminiIntelligenceAgent(
        api_keys=["k1", "k2", "k3", "k4"],
        model_name="gemini-2.5-flash",
        rate_limit_rpm=600.0,
    )

    call_keys = []

    async def mock_generate_content(model, contents, config=None):
        curr_key = agent.key_rotator.get_current_key(model=model)
        call_keys.append(curr_key)
        if len(call_keys) < 4:
            raise Exception(f"429 RESOURCE_EXHAUSTED: Quota exceeded on key {curr_key}")
        # Key 4 succeeds
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "company_name": "FourKey Co",
            "goa_office_locations": ["Porvorim"],
            "core_domain": "Fintech",
            "primary_tech_stack": ["Python"],
            "hiring_status": "Actively Hiring",
            "active_openings": [],
            "summary_explanation": "Succeeded on fourth key.",
        })
        return mock_resp

    agent.client.aio.models.generate_content = AsyncMock(side_effect=mock_generate_content)

    scraped = ScrapedData(
        company_name="FourKey Co",
        homepage_text="Homepage text for FourKey Co with extensive details in Porvorim Goa",
        careers_page_text="Careers text",
        ats_links=["https://keka.com/fourkey"],
    )

    intel = await agent.extract_structured_intelligence("FourKey Co", scraped, "Search notes")
    assert intel.company_name == "FourKey Co"
    assert len(call_keys) == 4
    assert call_keys == ["k1", "k2", "k3", "k4"]


@pytest.mark.asyncio
async def test_per_model_key_exhaustion_cascading():
    """Verify that exhausting keys on gemini-2.5-flash does not prevent using those keys on gemini-2.0-flash."""
    agent = GeminiIntelligenceAgent(
        api_keys=["key_a", "key_b"],
        model_name="gemini-2.5-flash",
        fallback_models=["gemini-2.0-flash"],
        rate_limit_rpm=600.0,
    )

    models_called = []

    async def mock_generate_content(model, contents, config=None):
        models_called.append((model, agent.key_rotator.get_current_key(model=model)))
        if model == "gemini-2.5-flash":
            raise Exception("429 RESOURCE_EXHAUSTED on gemini-2.5-flash")

        # gemini-2.0-flash succeeds
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "company_name": "PerModel Co",
            "goa_office_locations": ["Margao"],
            "core_domain": "HealthTech",
            "primary_tech_stack": ["React", "FastAPI"],
            "hiring_status": "Actively Hiring",
            "active_openings": [],
            "summary_explanation": "Extracted via gemini-2.0-flash fallback.",
        })
        return mock_resp

    agent.client.aio.models.generate_content = AsyncMock(side_effect=mock_generate_content)

    scraped = ScrapedData(
        company_name="PerModel Co",
        homepage_text="Homepage for PerModel Co in Margao with lots of content",
        careers_page_text="Careers at PerModel",
        ats_links=["https://permodel.com/careers"],
    )

    intel = await agent.extract_structured_intelligence("PerModel Co", scraped, "Notes")
    assert intel.company_name == "PerModel Co"

    # key_a and key_b were both tried on gemini-2.5-flash
    flash25_calls = [k for m, k in models_called if m == "gemini-2.5-flash"]
    assert "key_a" in flash25_calls
    assert "key_b" in flash25_calls

    # When cascading to gemini-2.0-flash, keys were still available
    flash20_calls = [k for m, k in models_called if m == "gemini-2.0-flash"]
    assert len(flash20_calls) >= 1
    assert flash20_calls[0] in ("key_a", "key_b")


@pytest.mark.asyncio
async def test_batch_extraction_with_markdown_fences():
    """Verify that batch extraction gracefully strips ```json ``` code fences."""
    agent = GeminiIntelligenceAgent(api_key="mock_key", rate_limit_rpm=600.0)

    fenced_output = """```json
    {
        "companies": [
            {
                "company_name": "Fence Co",
                "goa_office_locations": ["Verna"],
                "core_domain": "Firmware / Embedded",
                "primary_tech_stack": ["C++", "FreeRTOS"],
                "hiring_status": "Actively Hiring",
                "active_openings": [],
                "summary_explanation": "Extracted inside markdown fences."
            }
        ]
    }
    ```"""

    mock_resp = MagicMock()
    mock_resp.text = fenced_output
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    batch_items = [
        (
            "Fence Co",
            ScrapedData(
                company_name="Fence Co",
                homepage_text="Fence Co homepage text in Verna",
                careers_page_text="We build firmware",
                ats_links=["https://fence.com/job"],
            ),
            "Notes",
        )
    ]

    results = await agent.extract_batch_structured_intelligence(batch_items)
    assert len(results) == 1
    assert results[0].company_name == "Fence Co"
    assert results[0].core_domain == "Firmware / Embedded"
    assert "Verna" in results[0].goa_office_locations


@pytest.mark.asyncio
async def test_batch_extraction_fuzzy_matching_no_cross_contamination():
    """Verify company matching maps variations (Pvt Ltd, Technologies) without stealing other items."""
    agent = GeminiIntelligenceAgent(api_key="mock_key", rate_limit_rpm=600.0)

    llm_output = {
        "companies": [
            {
                "company_name": "Acme",
                "goa_office_locations": ["Panaji"],
                "core_domain": "SaaS Platform",
                "primary_tech_stack": ["Python", "Django"],
                "hiring_status": "Actively Hiring",
                "active_openings": [],
                "summary_explanation": "Acme explanation.",
            },
            {
                "company_name": "Innvion",
                "goa_office_locations": ["Verna"],
                "core_domain": "Industrial IoT",
                "primary_tech_stack": ["C++", "Qt"],
                "hiring_status": "No Listed Openings",
                "active_openings": [],
                "summary_explanation": "Innvion explanation.",
            },
            {
                "company_name": "Acme Cloud",
                "goa_office_locations": ["Margao"],
                "core_domain": "Cloud Hosting",
                "primary_tech_stack": ["Kubernetes", "Go"],
                "hiring_status": "Actively Hiring",
                "active_openings": [],
                "summary_explanation": "Acme Cloud explanation.",
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(llm_output)
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    batch_items = [
        (
            "Acme Technologies Pvt. Ltd.",
            ScrapedData(
                company_name="Acme Technologies Pvt. Ltd.",
                homepage_text="Acme Technologies homepage",
                ats_links=["https://acme.com/jobs"],
            ),
            "Notes 1",
        ),
        (
            "Innvion Systems",
            ScrapedData(
                company_name="Innvion Systems",
                homepage_text="Innvion Systems homepage",
                ats_links=["https://innvion.com/careers"],
            ),
            "Notes 2",
        ),
        (
            "Acme Cloud",
            ScrapedData(
                company_name="Acme Cloud",
                homepage_text="Acme Cloud hosting homepage",
                ats_links=["https://cloud.acme.com"],
            ),
            "Notes 3",
        ),
    ]

    results = await agent.extract_batch_structured_intelligence(batch_items)
    assert len(results) == 3
    # Check canonical names and core domains were correctly mapped
    assert results[0].company_name == "Acme Technologies Pvt. Ltd."
    assert results[0].core_domain == "SaaS Platform"

    assert results[1].company_name == "Innvion Systems"
    assert results[1].core_domain == "Industrial IoT"

    assert results[2].company_name == "Acme Cloud"
    assert results[2].core_domain == "Cloud Hosting"


@pytest.mark.asyncio
async def test_dead_site_skips_grounding_and_llm():
    """Verify that an unreachable site skips live search grounding and Gemini API calls."""
    agent = GeminiIntelligenceAgent(
        api_key="mock_key",
        enable_search_grounding=True,
    )

    dead_scraped = ScrapedData(
        company_name="Dead DNS Co",
        homepage_text="Failed to fetch http://deaddns.com: [Errno 11001] getaddrinfo failed",
        careers_page_text="",
        careers_fetch_failed=True,
    )

    with (
        patch.object(agent, "run_search_grounding", new_callable=AsyncMock) as mock_grounding,
        patch.object(agent.client.aio.models, "generate_content", new_callable=AsyncMock) as mock_generate,
    ):
        intel = await agent.analyze_company(dead_scraped, force_grounding=False)

        # Neither grounding nor LLM generate_content should be called
        mock_grounding.assert_not_called()
        mock_generate.assert_not_called()

        assert intel.company_name == "Dead DNS Co"
        assert "Goa" in intel.goa_office_locations
        assert intel.hiring_status == "Unknown"


@pytest.mark.asyncio
async def test_rate_limiter_backoff_cooldown():
    """Verify that calling backoff causes rate limiter to delay requests."""
    limiter = AsyncRateLimiter(requests_per_minute=6000.0)  # Very fast RPM
    start = time.monotonic()
    await limiter.acquire()

    # Trigger 0.15s backoff
    await limiter.backoff(delay=0.15)

    waited = await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.14
    assert waited >= 0.10


def test_clean_json_text_helper():
    from src.heuristic_extractor import clean_json_text

    # Raw clean JSON
    assert clean_json_text('{"a": 1}') == '{"a": 1}'

    # Markdown fenced JSON
    assert clean_json_text('```json\n{"b": 2}\n```') == '{"b": 2}'

    # Text before and after JSON
    assert clean_json_text('Preamble text\n{"c": 3}\nPostamble text') == '{"c": 3}'

    # JSON Array
    assert clean_json_text('[{"d": 4}]') == '[{"d": 4}]'

    # Empty
    assert clean_json_text('') == '{}'


