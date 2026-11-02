"""
Unit tests for edge cases, empty inputs, malformed data, and boundary values.
"""

import json
from pathlib import Path

import pytest

from src.database import DatabaseManager
from src.models import CompanyIntelligence, JobOpening
from src.scraper import clean_html_to_markdown


def test_clean_html_empty_and_whitespace():
    text, links = clean_html_to_markdown("")
    assert text == ""
    assert links == []

    text, links = clean_html_to_markdown("   \n\t  ")
    assert text == ""
    assert links == []


def test_clean_html_only_stripped_tags():
    html = """
    <html>
      <head>
        <script>alert(1);</script>
        <style>body { background: black; }</style>
      </head>
      <body>
        <nav><a href="/menu">Menu</a></nav>
        <svg><circle cx="5" cy="5" r="5"/></svg>
        <footer><p>Footer</p></footer>
      </body>
    </html>
    """
    text, links = clean_html_to_markdown(html)
    assert text.strip() == ""
    assert links == []


def test_clean_html_malformed():
    malformed_html = "<<<div<p>Valid text inside malformed tag<a href='https://keka.com/portal'>Apply</a>"
    text, links = clean_html_to_markdown(malformed_html)
    assert "Valid text inside malformed tag" in text
    assert any("keka.com" in link for link in links)


def test_company_seed_deduplication(tmp_path: Path):
    db_file = tmp_path / "dedup.db"
    db = DatabaseManager(db_path=db_file)
    import asyncio

    async def run_test():
        await db.init_db()
        seeds = [
            {"name": "Unique Co", "website": "https://u.com"},
            {"name": "Unique Co", "website": "https://u.com/duplicate"},
            {"name": "Unique Co", "website": "https://u.com/duplicate2"},
        ]
        # Should only insert 1 unique row
        inserted = await db.seed_companies(seeds)
        assert inserted == 1

        all_companies = await db.get_all_companies()
        assert len(all_companies) == 1

    asyncio.run(run_test())


@pytest.mark.asyncio
async def test_empty_database_export(tmp_path: Path):
    db_file = tmp_path / "empty.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()

    stats = await db.get_stats()
    assert stats["total_companies"] == 0
    assert stats["completed"] == 0
    assert stats["total_openings"] == 0

    md_out = tmp_path / "empty_digest.md"
    await db.export_markdown_digest(md_out)
    assert md_out.exists()
    content = md_out.read_text(encoding="utf-8")
    assert "No active openings identified yet." in content

    json_out = tmp_path / "empty_digest.json"
    await db.export_json_digest(json_out)
    assert json_out.exists()
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["companies"] == []


@pytest.mark.asyncio
async def test_job_with_empty_or_null_tech_stack(tmp_path: Path):
    db_file = tmp_path / "jobs_stack.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()

    seeds = [{"name": "Generic IT", "website": "https://generic.com"}]
    await db.seed_companies(seeds)

    intel = CompanyIntelligence(
        company_name="Generic IT",
        goa_office_locations=[],
        core_domain="IT Services",
        primary_tech_stack=[],
        hiring_status="Unknown",
        active_openings=[
            JobOpening(
                title="Support Technician",
                tech_stack=[],
                department="IT Support",
                experience_level="Entry",
                is_computer_eng_relevant=True,
            )
        ],
        summary_explanation="IT support services.",
    )
    await db.save_company_intelligence("Generic IT", intel)

    md_out = tmp_path / "generic_digest.md"
    await db.export_markdown_digest(md_out)
    content = md_out.read_text(encoding="utf-8")
    assert "Support Technician" in content
    assert "Goa (General)" in content
