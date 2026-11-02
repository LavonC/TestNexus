"""
End-to-end tests for PipelineOrchestrator and CLI runner.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.database import DatabaseManager
from src.main import PipelineOrchestrator
from src.models import CompanyIntelligence, JobOpening, ScrapedData


@pytest.mark.asyncio
async def test_pipeline_orchestrator_run(tmp_path: Path):
    db_file = tmp_path / "test_pipeline.db"
    db_manager = DatabaseManager(db_path=db_file)
    await db_manager.init_db()

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
    await db_manager.seed_companies(seeds)

    orchestrator = PipelineOrchestrator(
        db_manager=db_manager,
        concurrency=2,
        api_key="mock_key",
    )

    mock_scraped = ScrapedData(
        company_name="Spintly",
        homepage_text="Spintly Home",
        careers_page_text="Software Dev",
        ats_links=["https://spintly.keka.com"],
    )

    mock_intel = CompanyIntelligence(
        company_name="Spintly",
        goa_office_locations=["Verna"],
        core_domain="SaaS",
        primary_tech_stack=["React", "Node.js"],
        hiring_status="Actively Hiring",
        active_openings=[
            JobOpening(
                title="React Dev",
                tech_stack=["React", "TypeScript"],
                experience_level="1-3 years",
            )
        ],
        application_contact_email="careers@spintly.com",
        summary_explanation="Builds SaaS in Verna.",
    )

    with (
        patch.object(
            orchestrator.scraper, "scrape_company", new_callable=AsyncMock
        ) as mock_scrape,
        patch.object(
            orchestrator.gemini, "analyze_company", new_callable=AsyncMock
        ) as mock_analyze,
    ):
        mock_scrape.return_value = mock_scraped
        mock_analyze.return_value = mock_intel

        # Run for limit 1
        await orchestrator.run(limit=1)

        stats = await db_manager.get_stats()
        assert stats["completed"] == 1
        assert stats["pending"] == 1
        assert stats["total_openings"] == 1

        # Check export generation
        md_file = await db_manager.export_markdown_digest(
            tmp_path / "exports" / "digest.md"
        )
        assert md_file.exists()
        content = md_file.read_text(encoding="utf-8")
        assert "React Dev" in content
