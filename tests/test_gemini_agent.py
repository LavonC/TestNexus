"""
Unit tests for Gemini Intelligence Agent (mocking Google GenAI SDK).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gemini_agent import GeminiIntelligenceAgent
from src.models import CompanyIntelligence, ScrapedData


@pytest.mark.asyncio
async def test_search_grounding_invokes_google_search():
    agent = GeminiIntelligenceAgent(api_key="mock_key")

    mock_resp = MagicMock()
    mock_resp.text = "Found Goa office in Verna. Hiring React & Python engineers."

    mock_generate = AsyncMock(return_value=mock_resp)
    agent.client.aio.models.generate_content = mock_generate

    notes = await agent.run_search_grounding("Spintly")

    assert "Found Goa office in Verna" in notes
    mock_generate.assert_called_once()
    call_kwargs = mock_generate.call_args[1]
    assert call_kwargs["model"] == "gemini-3.8-flash"
    assert call_kwargs["config"].tools is not None


@pytest.mark.asyncio
async def test_extract_structured_intelligence():
    agent = GeminiIntelligenceAgent(api_key="mock_key")

    expected_intel = {
        "company_name": "Spintly",
        "goa_office_locations": ["Verna"],
        "core_domain": "SaaS / IoT",
        "primary_tech_stack": ["React", "Node.js", "Python"],
        "hiring_status": "Actively Hiring",
        "active_openings": [
            {
                "title": "Software Engineer",
                "department": "Engineering",
                "experience_level": "Fresher/Intern",
                "tech_stack": ["Python", "FastAPI"],
                "is_computer_eng_relevant": True,
                "apply_url": "https://keka.com/jobs/1",
            }
        ],
        "application_contact_email": "careers@spintly.com",
        "summary_explanation": "Spintly develops IoT solutions in Verna.",
    }

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(expected_intel)

    mock_generate = AsyncMock(return_value=mock_resp)
    agent.client.aio.models.generate_content = mock_generate

    scraped = ScrapedData(
        company_name="Spintly",
        homepage_text="Spintly Home",
        careers_page_text="We have openings for Software Engineer",
        ats_links=["https://keka.com/jobs/1"],
    )

    intel = await agent.extract_structured_intelligence(
        "Spintly", scraped, "Search notes here"
    )

    assert intel.company_name == "Spintly"
    assert intel.core_domain == "SaaS / IoT"
    assert len(intel.active_openings) == 1
    assert intel.active_openings[0].title == "Software Engineer"
    assert intel.goa_locations == ["Verna"]
    assert intel.careers_email == "careers@spintly.com"

    mock_generate.assert_called_once()
    call_kwargs = mock_generate.call_args[1]
    assert call_kwargs["config"].response_schema == CompanyIntelligence
    assert call_kwargs["config"].response_mime_type == "application/json"


@pytest.mark.asyncio
async def test_analyze_company_two_pass_pipeline():
    agent = GeminiIntelligenceAgent(api_key="mock_key")

    scraped = ScrapedData(
        company_name="Acme Tech",
        careers_page_text="",
        careers_fetch_failed=True,
        needs_search_grounding=True,
    )

    expected_intel = {
        "company_name": "Acme Tech",
        "goa_office_locations": ["Panaji"],
        "core_domain": "IT Services",
        "primary_tech_stack": ["Java", "Spring"],
        "hiring_status": "No Listed Openings",
        "active_openings": [],
        "summary_explanation": "Acme operates in Panaji.",
    }

    with (
        patch.object(
            agent, "run_search_grounding", new_callable=AsyncMock
        ) as mock_grounding,
        patch.object(
            agent, "extract_structured_intelligence", new_callable=AsyncMock
        ) as mock_extract,
    ):
        mock_grounding.return_value = "Search found office in Panaji"
        mock_extract.return_value = CompanyIntelligence.model_validate(expected_intel)

        intel = await agent.analyze_company(scraped)

        mock_grounding.assert_called_once_with("Acme Tech")
        mock_extract.assert_called_once()
        assert intel.company_name == "Acme Tech"
