"""
Unit and integration tests for CLI flags (--offline, --online, --stale-hours, --loop, --verify-links)
and offline batching in PipelineOrchestrator.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.database import DatabaseManager
from src.main import PipelineOrchestrator, parse_args
from src.models import ScrapedData


def test_cli_parser_defaults():
    """Verify that default CLI arguments set offline=True and stale_hours=6.0."""
    with patch("sys.argv", ["main.py"]):
        args = parse_args()
        assert args.offline is True
        assert args.stale_hours == 6.0
        assert args.loop is False
        assert args.verify_links is False
        assert args.verify_urls is False
        assert args.verify_only is False


def test_cli_parser_custom_cadence_and_flags():
    """Verify custom flags --online, --stale-hours, --loop, --verify-links."""
    with patch("sys.argv", ["main.py", "--online", "--stale-hours", "12.5", "--loop", "--verify-links"]):
        args = parse_args()
        assert args.offline is False
        assert args.stale_hours == 12.5
        assert args.loop is True
        assert args.verify_links is True
        assert args.verify_urls is True
        assert args.verify_only is False


def test_cli_parser_daemon_and_verify_urls_aliases():
    """Verify aliases --daemon and --verify-urls."""
    with patch("sys.argv", ["main.py", "--daemon", "--verify-urls", "--verify-only"]):
        args = parse_args()
        assert args.loop is True
        assert args.verify_links is True
        assert args.verify_urls is True
        assert args.verify_only is True


@pytest.mark.asyncio
async def test_offline_batch_processing(tmp_path: Path):
    """Verify that PipelineOrchestrator._process_company_batch uses build_offline_profile in offline mode without calling Gemini."""
    db_file = tmp_path / "test_offline_batch.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()

    seeds = [
        {"name": "Batch Company A", "website": "https://comp-a.com", "careers": "https://comp-a.com/careers"},
        {"name": "Batch Company B", "website": "https://comp-b.com", "careers": "https://comp-b.com/careers"},
    ]
    await db.seed_companies(seeds)

    orchestrator = PipelineOrchestrator(
        db_manager=db,
        concurrency=2,
        offline=True,
    )
    assert orchestrator.offline is True

    mock_client = AsyncMock()

    sdata_a = ScrapedData(
        company_name="Batch Company A",
        homepage_text="Tech company based in Panaji, Goa.",
        careers_page_text="# Careers\n- Senior Python Engineer (Panaji)",
        ats_links=[],
    )
    sdata_b = ScrapedData(
        company_name="Batch Company B",
        homepage_text="Firm in Verna Industrial Estate.",
        careers_page_text="We have openings for Embedded Firmware Developer in Verna.",
        ats_links=[],
    )

    with (
        patch.object(orchestrator.scraper, "scrape_company", side_effect=[sdata_a, sdata_b]),
        patch.object(orchestrator.gemini, "analyze_batch", new_callable=AsyncMock) as mock_gemini_batch,
    ):
        results = await orchestrator._process_company_batch(seeds, mock_client)
        assert results == [True, True]
        # Gemini analyze_batch MUST NOT have been called!
        mock_gemini_batch.assert_not_called()

    # Verify database state
    stats = await db.get_stats()
    assert stats["completed"] == 2
    assert stats["total_openings"] >= 1

    profile_a = await db.get_company_profile("Batch Company A")
    assert profile_a is not None
    assert profile_a["company_name"] == "Batch Company A"


@pytest.mark.asyncio
async def test_orchestrator_run_calls_stale_companies(tmp_path: Path):
    """Verify that orchestrator.run passes stale_hours to get_stale_companies."""
    db_file = tmp_path / "test_stale_run.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()

    orchestrator = PipelineOrchestrator(
        db_manager=db,
        offline=True,
    )

    with patch.object(db, "get_stale_companies", new_callable=AsyncMock) as mock_get_stale:
        mock_get_stale.return_value = []
        await orchestrator.run(limit=5, stale_hours=8.0)
        mock_get_stale.assert_called_once_with(stale_hours=8.0, limit=5)
