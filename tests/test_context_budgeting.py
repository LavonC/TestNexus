"""
Unit tests for intelligent query layer, token budgeting, and FTS5 ranking.
"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite
import pytest

from src.database import DatabaseManager
from src.gemini_agent import DatabaseQAAgent


@pytest.fixture
async def bulk_jobs_db(tmp_path: Path):
    db_file = tmp_path / "test_bulk_jobs.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()

    # Seed 1 company
    async with aiosqlite.connect(db_file) as conn:
        await conn.execute(
            """
            INSERT INTO companies (company_name, status, hiring_status, goa_locations, tech_stack)
            VALUES ('Panaji Tech Labs', 'COMPLETED', 'Actively Hiring', '["Panaji"]', '["Python", "React"]')
            """
        )

        # Seed 100 jobs: 50 active Python jobs, 30 active Go jobs, 20 closed Python jobs
        for i in range(1, 51):
            await conn.execute(
                """
                INSERT INTO job_openings (
                    company_name, title, department, experience_level,
                    tech_stack, is_computer_eng_relevant, apply_url,
                    detected_at, first_seen_at, last_seen_at, is_active
                ) VALUES (?, ?, 'Engineering', '2-4 years', '["Python", "FastAPI"]', 1, 'https://example.com/apply', '2026-01-01', '2026-01-01', '2026-01-01', 1)
                """,
                ("Panaji Tech Labs", f"Active Python Developer #{i}"),
            )

        for i in range(1, 31):
            await conn.execute(
                """
                INSERT INTO job_openings (
                    company_name, title, department, experience_level,
                    tech_stack, is_computer_eng_relevant, apply_url,
                    detected_at, first_seen_at, last_seen_at, is_active
                ) VALUES (?, ?, 'Engineering', 'Fresher', '["Go", "Docker"]', 1, 'https://example.com/apply', '2026-01-01', '2026-01-01', '2026-01-01', 1)
                """,
                ("Panaji Tech Labs", f"Active Go Systems Engineer #{i}"),
            )

        for i in range(1, 21):
            await conn.execute(
                """
                INSERT INTO job_openings (
                    company_name, title, department, experience_level,
                    tech_stack, is_computer_eng_relevant, apply_url,
                    detected_at, first_seen_at, last_seen_at, is_active, closed_at
                ) VALUES (?, ?, 'Engineering', 'Senior', '["Python", "Django"]', 1, 'https://example.com/apply', '2025-01-01', '2025-01-01', '2025-06-01', 0, '2025-06-02')
                """,
                ("Panaji Tech Labs", f"Closed Python Architect #{i}"),
            )

        await conn.commit()

    return db


@pytest.mark.asyncio
async def test_search_job_openings_active_filter(bulk_jobs_db: DatabaseManager):
    # active_only=True should find only active Python jobs
    active_py = await bulk_jobs_db.search_job_openings(query="Python", active_only=True, limit=100)
    assert len(active_py) == 50
    assert all(j["is_active"] == 1 for j in active_py)

    # include_historical=True should find active + closed Python jobs (50 + 20 = 70)
    all_py = await bulk_jobs_db.search_job_openings(query="Python", include_historical=True, limit=100)
    assert len(all_py) == 70
    closed_count = sum(1 for j in all_py if j["is_active"] == 0)
    assert closed_count == 20


@pytest.mark.asyncio
async def test_qa_agent_tool_token_budget(bulk_jobs_db: DatabaseManager):
    agent = DatabaseQAAgent(db_manager=bulk_jobs_db, api_key="dummy_key")
    tools = {fn.__name__: fn for fn in agent.get_tools()}

    search_tool = tools["search_job_openings"]

    # Call tool without limit override (default is capped at 15)
    tool_results = await search_tool(query="Python")

    # Verify results are strictly capped at max 15 to respect token budget
    assert len(tool_results) <= 15
    assert len(tool_results) > 0

    # Test serialized payload size is well below 1,500 token bounds (~6,000 characters)
    json_payload = json.dumps(tool_results)
    assert len(json_payload) < 6000  # strictly within 1,500 tokens (1,500 tokens * 4 chars = ~6,000 chars)

    # Verify compact projections: fields should be compact
    sample = tool_results[0]
    expected_keys = {
        "id", "company_name", "title", "department", "experience_level",
        "tech_stack", "is_computer_eng_relevant", "is_active", "apply_url",
        "last_seen_at", "source_type"
    }
    assert expected_keys.issubset(set(sample.keys()))
    assert sample["is_active"] == 1
