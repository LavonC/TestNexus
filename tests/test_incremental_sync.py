"""
Unit tests for 6-hour incremental sync and stale company queuing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

from src.database import DatabaseManager


@pytest.fixture
async def cadence_db(tmp_path: Path):
    db_file = tmp_path / "test_cadence.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()

    now = datetime.now(timezone.utc)
    scraped_3h_ago = (now - timedelta(hours=3)).isoformat()
    scraped_7h_ago = (now - timedelta(hours=7)).isoformat()

    # Seed test companies directly with controlled timestamps
    async with aiosqlite.connect(db_file) as conn:
        # 1. Fresh completed company (3 hours ago -> NOT stale)
        await conn.execute(
            """
            INSERT INTO companies (company_name, status, last_scraped_at)
            VALUES ('Fresh Tech', 'COMPLETED', ?)
            """,
            (scraped_3h_ago,),
        )
        # 2. Stale completed company (7 hours ago -> STALE)
        await conn.execute(
            """
            INSERT INTO companies (company_name, status, last_scraped_at)
            VALUES ('Old Tech', 'COMPLETED', ?)
            """,
            (scraped_7h_ago,),
        )
        # 3. Pending company (never scraped -> STALE)
        await conn.execute(
            """
            INSERT INTO companies (company_name, status, last_scraped_at)
            VALUES ('New Pending Tech', 'PENDING', NULL)
            """
        )
        # 4. Failed company (needs retry -> STALE)
        await conn.execute(
            """
            INSERT INTO companies (company_name, status, last_scraped_at, error_message)
            VALUES ('Failed Tech', 'FAILED', ?, 'Timeout')
            """,
            (scraped_3h_ago,),
        )
        await conn.commit()

    return db


@pytest.mark.asyncio
async def test_get_stale_companies_cadence(cadence_db: DatabaseManager):
    # With stale_hours = 6.0:
    # 'Fresh Tech' (3h ago) must NOT be returned.
    # 'Old Tech' (7h ago), 'New Pending Tech' (PENDING), 'Failed Tech' (FAILED) must be returned.
    stale = await cadence_db.get_stale_companies(stale_hours=6.0)
    stale_names = [c["name"] for c in stale]

    assert "Fresh Tech" not in stale_names
    assert "Old Tech" in stale_names
    assert "New Pending Tech" in stale_names
    assert "Failed Tech" in stale_names

    # Check ordering: PENDING should come before COMPLETED
    pending_idx = next(i for i, c in enumerate(stale) if c["name"] == "New Pending Tech")
    old_idx = next(i for i, c in enumerate(stale) if c["name"] == "Old Tech")
    assert pending_idx < old_idx


@pytest.mark.asyncio
async def test_get_stale_companies_custom_hours(cadence_db: DatabaseManager):
    # With stale_hours = 2.0:
    # Both 3h and 7h are stale!
    stale_2h = await cadence_db.get_stale_companies(stale_hours=2.0)
    stale_names_2h = [c["name"] for c in stale_2h]
    assert "Fresh Tech" in stale_names_2h
    assert "Old Tech" in stale_names_2h

    # With stale_hours = 10.0:
    # Only PENDING and FAILED should be returned (both 3h and 7h are still fresh)
    stale_10h = await cadence_db.get_stale_companies(stale_hours=10.0)
    stale_names_10h = [c["name"] for c in stale_10h]
    assert "Fresh Tech" not in stale_names_10h
    assert "Old Tech" not in stale_names_10h
    assert "New Pending Tech" in stale_names_10h
    assert "Failed Tech" in stale_names_10h


@pytest.mark.asyncio
async def test_get_stale_companies_skips_dead_domains(cadence_db: DatabaseManager):
    """Verify that confirmed dead domains (is_dead=1) are skipped from incremental sync."""
    # Mark 'Failed Tech' as dead (e.g. DNS failure)
    await cadence_db.update_company_urls(
        company_name="Failed Tech",
        is_dead=1,
    )

    stale = await cadence_db.get_stale_companies(stale_hours=6.0)
    stale_names = [c["name"] for c in stale]
    assert "Failed Tech" not in stale_names
    assert "Old Tech" in stale_names
    assert "New Pending Tech" in stale_names

    # Check that get_pending_companies also skips dead domains
    pending = await cadence_db.get_pending_companies()
    pending_names = [c["name"] for c in pending]
    assert "Failed Tech" not in pending_names
