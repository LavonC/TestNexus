"""
SQLite database management with asynchronous CRUD and checkpointing.
Tracks scraping state, company intelligence, and detected job openings.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from src.config import config
from src.models import CompanyIntelligence

logger = logging.getLogger(__name__)


def get_utc_now() -> str:
    """Return ISO formatted current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def normalize_job_title(title: str) -> str:
    """Normalize job title for deduplication and stateful matching."""
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


class TursoRow:
    """Compatibility wrapper providing dict-like and index-like access for Turso rows."""

    def __init__(self, cols: tuple[str, ...], vals: tuple[Any, ...]):
        self._mapping = dict(zip(cols, vals))
        self._lower_mapping = {c.lower(): v for c, v in zip(cols, vals)}
        self._vals = vals
        self._cols = cols

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._vals[key]
        if key in self._mapping:
            return self._mapping[key]
        lower_k = key.lower()
        if lower_k in self._lower_mapping:
            return self._lower_mapping[lower_k]
        raise KeyError(key)

    def keys(self):
        return self._mapping.keys()

    def values(self):
        return self._mapping.values()

    def items(self):
        return self._mapping.items()

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._mapping:
            return self._mapping[key]
        return self._lower_mapping.get(key.lower(), default)

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def __repr__(self):
        return f"<TursoRow {self._mapping!r}>"


class TursoCursor:
    """Cursor emulation for LibSQL / Turso query result sets."""

    def __init__(self, rs: Any, row_factory: Any = None):
        self._rs = rs
        self._row_factory = row_factory
        self.columns = tuple(rs.columns) if hasattr(rs, "columns") else ()
        self.description = [(c, None, None, None, None, None, None) for c in self.columns]
        self.lastrowid = getattr(rs, "last_insert_rowid", None)
        self.rowcount = getattr(rs, "rows_affected", len(getattr(rs, "rows", [])))
        self._idx = 0

    def _make_row(self, raw_row: Any) -> Any:
        row_tuple = tuple(raw_row)
        if self._row_factory is not None:
            return TursoRow(self.columns, row_tuple)
        return row_tuple

    async def fetchall(self) -> list[Any]:
        if not hasattr(self._rs, "rows"):
            return []
        return [self._make_row(r) for r in self._rs.rows]

    async def fetchone(self) -> Any | None:
        if not hasattr(self._rs, "rows") or not self._rs.rows:
            return None
        if self._idx < len(self._rs.rows):
            row = self._make_row(self._rs.rows[self._idx])
            self._idx += 1
            return row
        return None

    def __iter__(self):
        if not hasattr(self._rs, "rows"):
            return iter(())
        return iter([self._make_row(r) for r in self._rs.rows])

    def __aiter__(self):
        return self

    async def __anext__(self):
        row = await self.fetchone()
        if row is None:
            raise StopAsyncIteration
        return row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TursoQueryManager:
    """Context manager and awaitable wrapper for Turso queries."""

    def __init__(self, coro: Any):
        self._coro = coro

    def __await__(self):
        return self._coro.__await__()

    async def __aenter__(self) -> TursoCursor:
        return await self._coro

    async def __aexit__(self, exc_type, exc, tb) -> None:
        pass


class TursoConn:
    """Connection abstraction over Turso LibSQL client."""

    def __init__(self, client: Any):
        self.client = client
        self.row_factory: Any = None

    def execute(self, sql: str, params: Any = None) -> TursoQueryManager:
        p = list(params) if params is not None else []

        async def _exec() -> TursoCursor:
            rs = await self.client.execute(sql, p)
            return TursoCursor(rs, row_factory=self.row_factory)

        return TursoQueryManager(_exec())

    def executemany(self, sql: str, seq_of_params: Any = None) -> TursoQueryManager:
        async def _exec() -> TursoCursor:
            last_rs = None
            if seq_of_params:
                for p in seq_of_params:
                    last_rs = await self.client.execute(sql, list(p))
            return TursoCursor(last_rs, row_factory=self.row_factory)

        return TursoQueryManager(_exec())

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class DatabaseManager:
    """Asynchronous SQLite and Turso LibSQL manager for company intelligence pipeline."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        turso_url: str | None = None,
        auth_token: str | None = None,
    ):
        if turso_url is not None:
            self.turso_url = turso_url
        elif db_path is not None:
            self.turso_url = None
        else:
            self.turso_url = config.TURSO_DATABASE_URL

        self.auth_token = auth_token if auth_token is not None else config.TURSO_AUTH_TOKEN
        self.is_turso = bool(self.turso_url and self.turso_url.strip())
        self._turso_client: Any = None
        self.db_path = Path(db_path) if db_path else config.DB_PATH
        if not self.is_turso:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def _get_connection(self):
        """Yield an async connection to Turso LibSQL or local SQLite (aiosqlite)."""
        if self.is_turso:
            if self._turso_client is None:
                try:
                    import libsql_client
                    effective_url = self.turso_url.strip()
                    if effective_url.startswith("libsql://"):
                        effective_url = "https://" + effective_url[9:]
                    self._turso_client = libsql_client.create_client(
                        url=effective_url, auth_token=self.auth_token
                    )
                except Exception as exc:
                    logger.error("Failed to connect to Turso LibSQL: %s", exc)
                    raise
            conn = TursoConn(self._turso_client)
            yield conn
        else:
            async with aiosqlite.connect(self.db_path) as db:
                yield db

    async def close(self) -> None:
        """Close Turso client if active."""
        if self._turso_client is not None:
            try:
                await self._turso_client.close()
            except Exception:
                pass
            self._turso_client = None

    async def init_db(self) -> None:
        """Create database tables, indexes, and FTS5 virtual tables if they do not exist."""
        async with self._get_connection() as db:
            if not self.is_turso:
                await db.execute("PRAGMA journal_mode = WAL;")
            await db.execute("PRAGMA foreign_keys = ON;")

            # 1. Companies master table with checkpoint status
            await db.execute("""
                CREATE TABLE IF NOT EXISTS companies (
                    company_name TEXT PRIMARY KEY,
                    website_url TEXT,
                    careers_url TEXT,
                    rss_url TEXT,
                    core_domain TEXT,
                    hiring_status TEXT DEFAULT 'Unknown',
                    careers_email TEXT,
                    goa_locations TEXT,
                    tech_stack TEXT,
                    summary_explanation TEXT,
                    recent_news_summary TEXT,
                    status TEXT DEFAULT 'PENDING',
                    last_scraped_at TEXT,
                    error_message TEXT,
                    is_dead INTEGER DEFAULT 0
                )
            """)

            # 2. Discrete job openings table with historical tracking
            await db.execute("""
                CREATE TABLE IF NOT EXISTS job_openings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    department TEXT,
                    experience_level TEXT,
                    tech_stack TEXT,
                    is_computer_eng_relevant INTEGER DEFAULT 1,
                    apply_url TEXT,
                    detected_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL DEFAULT '',
                    last_seen_at TEXT NOT NULL DEFAULT '',
                    is_active INTEGER DEFAULT 1,
                    closed_at TEXT,
                    source_type TEXT DEFAULT 'WEB',
                    source_url TEXT,
                    application_deadline TEXT,
                    is_government INTEGER DEFAULT 0,
                    FOREIGN KEY(company_name) REFERENCES companies(company_name) ON DELETE CASCADE
                )
            """)

            # 3. Scrape run logs for auditability
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scrape_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT,
                    step TEXT,
                    status TEXT,
                    message TEXT,
                    timestamp TEXT NOT NULL
                )
            """)

            # 4. Job Alerts table for email alerts
            await db.execute("""
                CREATE TABLE IF NOT EXISTS job_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    tech_filter TEXT,
                    location_filter TEXT,
                    experience_filter TEXT,
                    ce_only INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    unsubscribe_token TEXT NOT NULL
                )
            """)

            # Migration: Add any missing columns to existing databases
            async with db.execute("PRAGMA table_info(companies)") as cursor:
                existing_company_cols = {row[1] for row in await cursor.fetchall()}
            if "is_dead" not in existing_company_cols:
                await db.execute(
                    "ALTER TABLE companies ADD COLUMN is_dead INTEGER DEFAULT 0"
                )

            async with db.execute("PRAGMA table_info(job_openings)") as cursor:
                existing_cols = {row[1] for row in await cursor.fetchall()}

            if "first_seen_at" not in existing_cols:
                await db.execute(
                    "ALTER TABLE job_openings ADD COLUMN first_seen_at TEXT NOT NULL DEFAULT ''"
                )
            if "last_seen_at" not in existing_cols:
                await db.execute(
                    "ALTER TABLE job_openings ADD COLUMN last_seen_at TEXT NOT NULL DEFAULT ''"
                )
            if "is_active" not in existing_cols:
                await db.execute(
                    "ALTER TABLE job_openings ADD COLUMN is_active INTEGER DEFAULT 1"
                )
            if "closed_at" not in existing_cols:
                await db.execute(
                    "ALTER TABLE job_openings ADD COLUMN closed_at TEXT"
                )
            if "source_type" not in existing_cols:
                await db.execute(
                    "ALTER TABLE job_openings ADD COLUMN source_type TEXT DEFAULT 'WEB'"
                )
            if "source_url" not in existing_cols:
                await db.execute(
                    "ALTER TABLE job_openings ADD COLUMN source_url TEXT"
                )
            if "application_deadline" not in existing_cols:
                await db.execute(
                    "ALTER TABLE job_openings ADD COLUMN application_deadline TEXT"
                )
            if "is_government" not in existing_cols:
                await db.execute(
                    "ALTER TABLE job_openings ADD COLUMN is_government INTEGER DEFAULT 0"
                )

            # Backfill existing jobs with detected_at timestamp if first_seen_at is empty
            await db.execute(
                "UPDATE job_openings SET first_seen_at = detected_at WHERE first_seen_at = '' OR first_seen_at IS NULL"
            )
            await db.execute(
                "UPDATE job_openings SET last_seen_at = detected_at WHERE last_seen_at = '' OR last_seen_at IS NULL"
            )

            # Indexes for fast querying & digest generation
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_companies_is_dead ON companies(is_dead);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_companies_last_scraped ON companies(last_scraped_at);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_company ON job_openings(company_name);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_ce_relevant ON job_openings(is_computer_eng_relevant);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_company_active ON job_openings(company_name, is_active);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_ce_active ON job_openings(is_computer_eng_relevant, is_active);"
            )

            # FTS5 Virtual Tables and Sync Triggers
            try:
                await db.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS job_openings_fts USING fts5(
                        title, department, tech_stack, company_name,
                        content='job_openings', content_rowid='id'
                    )
                """)
                await db.execute("""
                    CREATE TRIGGER IF NOT EXISTS job_openings_ai AFTER INSERT ON job_openings BEGIN
                      INSERT INTO job_openings_fts(rowid, title, department, tech_stack, company_name)
                      VALUES (new.id, new.title, new.department, new.tech_stack, new.company_name);
                    END
                """)
                await db.execute("""
                    CREATE TRIGGER IF NOT EXISTS job_openings_ad AFTER DELETE ON job_openings BEGIN
                      INSERT INTO job_openings_fts(job_openings_fts, rowid, title, department, tech_stack, company_name)
                      VALUES('delete', old.id, old.title, old.department, old.tech_stack, old.company_name);
                    END
                """)
                await db.execute("""
                    CREATE TRIGGER IF NOT EXISTS job_openings_au AFTER UPDATE ON job_openings BEGIN
                      INSERT INTO job_openings_fts(job_openings_fts, rowid, title, department, tech_stack, company_name)
                      VALUES('delete', old.id, old.title, old.department, old.tech_stack, old.company_name);
                      INSERT INTO job_openings_fts(rowid, title, department, tech_stack, company_name)
                      VALUES (new.id, new.title, new.department, new.tech_stack, new.company_name);
                    END
                """)

                await db.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS companies_fts USING fts5(
                        company_name, core_domain, summary_explanation, tech_stack,
                        content='companies', content_rowid='rowid'
                    )
                """)
                await db.execute("""
                    CREATE TRIGGER IF NOT EXISTS companies_ai AFTER INSERT ON companies BEGIN
                      INSERT INTO companies_fts(rowid, company_name, core_domain, summary_explanation, tech_stack)
                      VALUES (new.rowid, new.company_name, new.core_domain, new.summary_explanation, new.tech_stack);
                    END
                """)
                await db.execute("""
                    CREATE TRIGGER IF NOT EXISTS companies_ad AFTER DELETE ON companies BEGIN
                      INSERT INTO companies_fts(companies_fts, rowid, company_name, core_domain, summary_explanation, tech_stack)
                      VALUES('delete', old.rowid, old.company_name, old.core_domain, old.summary_explanation, old.tech_stack);
                    END
                """)
                await db.execute("""
                    CREATE TRIGGER IF NOT EXISTS companies_au AFTER UPDATE ON companies BEGIN
                      INSERT INTO companies_fts(companies_fts, rowid, company_name, core_domain, summary_explanation, tech_stack)
                      VALUES('delete', old.rowid, old.company_name, old.core_domain, old.summary_explanation, old.tech_stack);
                      INSERT INTO companies_fts(rowid, company_name, core_domain, summary_explanation, tech_stack)
                      VALUES (new.rowid, new.company_name, new.core_domain, new.summary_explanation, new.tech_stack);
                    END
                """)
                # Rebuild FTS indexes on initialization to ensure external content tables stay in sync
                await db.execute("INSERT INTO job_openings_fts(job_openings_fts) VALUES('rebuild');")
                await db.execute("INSERT INTO companies_fts(companies_fts) VALUES('rebuild');")
            except Exception as fts_exc:
                logger.warning("FTS5 table initialization skipped or rebuild failed: %s", fts_exc)

            await db.commit()
            logger.info("Database initialized successfully at %s", self.db_path)

    async def rebuild_fts(self) -> None:
        """Rebuild FTS5 external content indexes to prevent desynchronization."""
        async with self._get_connection() as db:
            try:
                await db.execute("INSERT INTO job_openings_fts(job_openings_fts) VALUES('rebuild');")
                await db.execute("INSERT INTO companies_fts(companies_fts) VALUES('rebuild');")
                await db.commit()
                logger.info("Successfully rebuilt FTS5 indexes")
            except Exception as e:
                logger.warning("FTS5 rebuild failed: %s", e)

    async def seed_companies(
        self, seeds: list[dict[str, Any]], reset: bool = False
    ) -> int:
        """
        Seed database with companies from the seed list.
        If reset=False, existing companies and their statuses are preserved.
        """
        inserted_count = 0
        async with self._get_connection() as db:
            for item in seeds:
                name = item["name"].strip()
                website = item.get("website")
                careers = item.get("careers")
                rss = item.get("rss")

                if reset:
                    await db.execute(
                        """
                        INSERT OR REPLACE INTO companies (
                            company_name, website_url, careers_url, rss_url, status
                        ) VALUES (?, ?, ?, ?, 'PENDING')
                    """,
                        (name, website, careers, rss),
                    )
                    inserted_count += 1
                else:
                    cursor = await db.execute(
                        """
                        INSERT OR IGNORE INTO companies (
                            company_name, website_url, careers_url, rss_url, status
                        ) VALUES (?, ?, ?, ?, 'PENDING')
                    """,
                        (name, website, careers, rss),
                    )
                    if cursor.rowcount > 0:
                        inserted_count += 1

            await db.commit()
        return inserted_count

    async def reset_failed(self, include_in_progress: bool = True) -> int:
        """
        Reset all companies in FAILED (and optionally IN_PROGRESS) status back to PENDING,
        clearing their error_message so they can be cleanly reprocessed.
        Returns the number of companies updated.
        """
        async with self._get_connection() as db:
            if include_in_progress:
                cursor = await db.execute(
                    """
                    UPDATE companies
                    SET status = 'PENDING', error_message = NULL
                    WHERE status IN ('FAILED', 'IN_PROGRESS')
                    """
                )
            else:
                cursor = await db.execute(
                    """
                    UPDATE companies
                    SET status = 'PENDING', error_message = NULL
                    WHERE status = 'FAILED'
                    """
                )
            count = cursor.rowcount
            await db.commit()
            return count

    async def update_company_urls(
        self,
        company_name: str,
        website: str | None = None,
        careers: str | None = None,
        status: str | None = None,
        error_message: str | None = None,
        is_dead: int | None = None,
    ) -> None:
        """Update company website and/or careers URLs, status, error_message, and is_dead flag."""
        async with self._get_connection() as db:
            updates = []
            params: list[Any] = []
            if website is not None:
                updates.append("website_url = ?")
                params.append(website)
            if careers is not None:
                updates.append("careers_url = ?")
                params.append(careers)
            if status is not None:
                if status != "COMPLETED":
                    updates.append("status = CASE WHEN status = 'COMPLETED' THEN status ELSE ? END")
                else:
                    updates.append("status = ?")
                params.append(status)
            if error_message is not None:
                updates.append("error_message = ?")
                params.append(error_message)
            if is_dead is not None:
                updates.append("is_dead = ?")
                params.append(is_dead)

            if updates:
                params.append(company_name)
                await db.execute(
                    f"UPDATE companies SET {', '.join(updates)} WHERE company_name = ?",
                    tuple(params),
                )
                await db.commit()

    async def batch_update_company_urls(
        self,
        updates_list: list[dict[str, Any]],
    ) -> int:
        """Batch update company URLs, status, error_message, and is_dead in a single transaction."""
        if not updates_list:
            return 0
        updated_count = 0
        async with self._get_connection() as db:
            for item in updates_list:
                company_name = item.get("company_name")
                if not company_name:
                    continue
                updates = []
                params: list[Any] = []
                if item.get("website") is not None:
                    updates.append("website_url = ?")
                    params.append(item["website"])
                if item.get("careers") is not None:
                    updates.append("careers_url = ?")
                    params.append(item["careers"])
                if item.get("status") is not None:
                    status = item["status"]
                    if status != "COMPLETED":
                        updates.append("status = CASE WHEN status = 'COMPLETED' THEN status ELSE ? END")
                    else:
                        updates.append("status = ?")
                    params.append(status)
                if item.get("error_message") is not None:
                    updates.append("error_message = ?")
                    params.append(item["error_message"])
                if item.get("is_dead") is not None:
                    updates.append("is_dead = ?")
                    params.append(item["is_dead"])

                if updates:
                    params.append(company_name)
                    await db.execute(
                        f"UPDATE companies SET {', '.join(updates)} WHERE company_name = ?",
                        tuple(params),
                    )
                    updated_count += 1
            await db.commit()
        return updated_count

    async def get_pending_companies(
        self, limit: int | None = None, include_failed: bool = True
    ) -> list[dict[str, Any]]:
        """Retrieve companies that are PENDING, FAILED, or stuck IN_PROGRESS (excluding dead domains)."""
        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row
            status_filter = (
                "('PENDING', 'FAILED', 'IN_PROGRESS')"
                if include_failed
                else "('PENDING', 'IN_PROGRESS')"
            )
            query = f"""
                SELECT company_name, website_url, careers_url, rss_url, status
                FROM companies
                WHERE status IN {status_filter}
                  AND (is_dead = 0 OR is_dead IS NULL)
                ORDER BY CASE status WHEN 'PENDING' THEN 1 WHEN 'IN_PROGRESS' THEN 2 ELSE 3 END, company_name ASC
            """
            if limit and limit > 0:
                query += f" LIMIT {int(limit)}"

            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "name": row["company_name"],
                        "website": row["website_url"],
                        "careers": row["careers_url"],
                        "rss": row["rss_url"],
                        "status": row["status"],
                    }
                    for row in rows
                ]

    async def get_stale_companies(
        self, stale_hours: float = 6.0, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Retrieve companies due for incremental rescraping:
        - (is_dead = 0 OR is_dead IS NULL)
        - status != 'COMPLETED' (PENDING, FAILED, IN_PROGRESS)
        - OR last_scraped_at IS NULL
        - OR last_scraped_at older than `stale_hours` ago.
        Ordered with unscraped/pending first, then oldest scrape timestamps.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=stale_hours)).isoformat()
        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row
            query = """
                SELECT company_name, website_url, careers_url, rss_url, status, last_scraped_at
                FROM companies
                WHERE (is_dead = 0 OR is_dead IS NULL)
                  AND (
                       status != 'COMPLETED'
                    OR last_scraped_at IS NULL
                    OR last_scraped_at < ?
                  )
                ORDER BY
                    CASE status WHEN 'PENDING' THEN 1 WHEN 'IN_PROGRESS' THEN 2 WHEN 'FAILED' THEN 3 ELSE 4 END,
                    CASE WHEN last_scraped_at IS NULL THEN 0 ELSE 1 END,
                    last_scraped_at ASC,
                    company_name ASC
            """
            params: list[Any] = [cutoff]
            if limit and limit > 0:
                query += f" LIMIT {int(limit)}"

            async with db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "name": row["company_name"],
                        "website": row["website_url"],
                        "careers": row["careers_url"],
                        "rss": row["rss_url"],
                        "status": row["status"],
                        "last_scraped_at": row["last_scraped_at"],
                    }
                    for row in rows
                ]

    async def get_all_companies(self) -> list[dict[str, Any]]:
        """Retrieve all companies from the database."""
        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM companies ORDER BY company_name ASC"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def mark_in_progress(self, company_name: str) -> None:
        """Mark a company as IN_PROGRESS during scraping."""
        async with self._get_connection() as db:
            await db.execute(
                "UPDATE companies SET status = 'IN_PROGRESS' WHERE company_name = ?",
                (company_name,),
            )
            await db.commit()

    async def save_company_intelligence_stateful(
        self,
        company_name: str,
        intel: CompanyIntelligence,
        seed: dict[str, Any] | None = None,
    ) -> None:
        """
        Atomically save extracted intelligence, update company checkpoint to COMPLETED,
        and statefully track job openings (updating active, closing vanished, never deleting).
        """
        now = get_utc_now()
        seed = seed or {}
        website = seed.get("website")
        careers = seed.get("careers")
        rss = seed.get("rss")

        goa_locs_json = json.dumps(intel.goa_office_locations)
        tech_stack_json = json.dumps(intel.primary_tech_stack)

        async with self._get_connection() as db:
            # 1. Update company record
            await db.execute(
                """
                UPDATE companies
                SET
                    website_url = COALESCE(?, website_url),
                    careers_url = COALESCE(?, careers_url),
                    rss_url = COALESCE(?, rss_url),
                    core_domain = ?,
                    hiring_status = ?,
                    careers_email = ?,
                    goa_locations = ?,
                    tech_stack = ?,
                    summary_explanation = ?,
                    recent_news_summary = ?,
                    status = 'COMPLETED',
                    last_scraped_at = ?,
                    error_message = NULL
                WHERE company_name = ?
            """,
                (
                    website,
                    careers,
                    rss,
                    intel.core_domain,
                    intel.hiring_status,
                    intel.application_contact_email,
                    goa_locs_json,
                    tech_stack_json,
                    intel.summary_explanation,
                    intel.recent_news_summary,
                    now,
                    company_name,
                ),
            )

            # 2. Stateful reconciliation of job openings (never delete historical openings)
            async with db.execute(
                """
                SELECT id, title, department, experience_level, tech_stack, is_computer_eng_relevant, apply_url
                FROM job_openings
                WHERE company_name = ? AND is_active = 1
                """,
                (company_name,),
            ) as cursor:
                existing_active_rows = await cursor.fetchall()

            existing_by_norm = {
                normalize_job_title(row[1]): {
                    "id": row[0],
                    "title": row[1],
                    "department": row[2],
                    "experience_level": row[3],
                    "tech_stack": row[4],
                    "is_computer_eng_relevant": row[5],
                    "apply_url": row[6],
                }
                for row in existing_active_rows
            }
            matched_existing_ids: set[int] = set()

            for job in intel.active_openings:
                norm_title = normalize_job_title(job.title)
                source_type = getattr(job, "source_type", "WEB") or "WEB"
                source_url = getattr(job, "source_url", None)
                deadline = getattr(job, "application_deadline", None)
                is_govt = 1 if (
                    getattr(job, "is_government", False)
                    or "gov" in company_name.lower()
                    or "gpsc" in company_name.lower()
                    or "cbes" in company_name.lower()
                ) else 0

                if norm_title in existing_by_norm:
                    # Match found: update existing active opening's last_seen_at
                    matched_id = existing_by_norm[norm_title]["id"]
                    matched_existing_ids.add(matched_id)
                    await db.execute(
                        """
                        UPDATE job_openings
                        SET
                            last_seen_at = ?,
                            department = COALESCE(?, department),
                            experience_level = COALESCE(?, experience_level),
                            tech_stack = ?,
                            is_computer_eng_relevant = ?,
                            apply_url = COALESCE(?, apply_url),
                            source_type = COALESCE(?, source_type),
                            source_url = COALESCE(?, source_url),
                            application_deadline = COALESCE(?, application_deadline),
                            is_government = MAX(?, is_government),
                            is_active = 1,
                            closed_at = NULL
                        WHERE id = ?
                        """,
                        (
                            now,
                            job.department,
                            job.experience_level,
                            json.dumps(job.tech_stack),
                            1 if job.is_computer_eng_relevant else 0,
                            job.apply_url,
                            source_type,
                            source_url,
                            deadline,
                            is_govt,
                            matched_id,
                        ),
                    )
                else:
                    # New opening: insert with first_seen_at = now, last_seen_at = now, is_active = 1
                    await db.execute(
                        """
                        INSERT INTO job_openings (
                            company_name, title, department, experience_level,
                            tech_stack, is_computer_eng_relevant, apply_url,
                            detected_at, first_seen_at, last_seen_at, is_active,
                            closed_at, source_type, source_url, application_deadline, is_government
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, ?, ?, ?, ?)
                        """,
                        (
                            company_name,
                            job.title,
                            job.department,
                            job.experience_level,
                            json.dumps(job.tech_stack),
                            1 if job.is_computer_eng_relevant else 0,
                            job.apply_url,
                            now,
                            now,
                            now,
                            source_type,
                            source_url,
                            deadline,
                            is_govt,
                        ),
                    )

            # Mark active jobs that were not detected in current scrape as closed
            for norm_title, existing_info in existing_by_norm.items():
                if existing_info["id"] not in matched_existing_ids:
                    await db.execute(
                        """
                        UPDATE job_openings
                        SET is_active = 0, closed_at = ?
                        WHERE id = ?
                        """,
                        (now, existing_info["id"]),
                    )

            # 3. Log success
            await db.execute(
                """
                INSERT INTO scrape_logs (company_name, step, status, message, timestamp)
                VALUES (?, 'EXTRACTION', 'SUCCESS', ?, ?)
            """,
                (
                    company_name,
                    f"Processed with {len(intel.active_openings)} openings (Stateful)",
                    now,
                ),
            )

            await db.commit()

    # Alias for backwards compatibility
    save_company_intelligence = save_company_intelligence_stateful

    async def mark_company_failed(self, company_name: str, error_message: str) -> None:
        """Mark a company as FAILED and record the categorized error message."""
        now = get_utc_now()
        err_lower = (error_message or "").lower()
        if "timeout" in err_lower or "408" in err_lower:
            category = "Timeout"
        elif "ssl" in err_lower or "certificate" in err_lower:
            category = "SSL"
        elif "dns" in err_lower or "getaddrinfo" in err_lower or "connecterror" in err_lower or "name resolution" in err_lower:
            category = "DNS"
        elif "404" in err_lower or "403" in err_lower or "401" in err_lower or "4xx" in err_lower:
            category = "HTTP 4xx"
        elif "500" in err_lower or "502" in err_lower or "503" in err_lower or "5xx" in err_lower:
            category = "HTTP 5xx"
        elif "parked" in err_lower:
            category = "Parked"
        else:
            category = "General"

        categorized_step = f"SCRAPE_ERROR:{category}"
        formatted_msg = error_message if error_message.startswith("[") else f"[{category}] {error_message}"

        async with self._get_connection() as db:
            await db.execute(
                """
                UPDATE companies
                SET status = 'FAILED', error_message = ?, last_scraped_at = ?
                WHERE company_name = ?
            """,
                (formatted_msg, now, company_name),
            )

            await db.execute(
                """
                INSERT INTO scrape_logs (company_name, step, status, message, timestamp)
                VALUES (?, ?, 'FAILED', ?, ?)
            """,
                (company_name, categorized_step, formatted_msg[:500], now),
            )

            await db.commit()

    async def log_step(
        self, company_name: str, step: str, status: str, message: str
    ) -> None:
        """Log a specific pipeline step for debugging and audit."""
        now = get_utc_now()
        async with self._get_connection() as db:
            await db.execute(
                """
                INSERT INTO scrape_logs (company_name, step, status, message, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """,
                (company_name, step, status, message[:500], now),
            )
            await db.commit()

    async def get_stats(self) -> dict[str, Any]:
        """Compute aggregate statistics for the database, distinguishing active and historical jobs."""
        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                "SELECT status, COUNT(*) as count FROM companies GROUP BY status"
            )
            status_counts = {
                row["status"]: row["count"] for row in await cursor.fetchall()
            }

            cursor = await db.execute(
                "SELECT COUNT(*) as active_jobs FROM job_openings WHERE is_active = 1"
            )
            active_jobs = (await cursor.fetchone())["active_jobs"]

            cursor = await db.execute(
                "SELECT COUNT(*) as total_jobs FROM job_openings"
            )
            total_historical_jobs = (await cursor.fetchone())["total_jobs"]

            cursor = await db.execute(
                "SELECT COUNT(*) as ce_jobs FROM job_openings WHERE is_computer_eng_relevant = 1 AND is_active = 1"
            )
            ce_jobs = (await cursor.fetchone())["ce_jobs"]

            cursor = await db.execute("""
                SELECT COUNT(*) as actively_hiring
                FROM companies
                WHERE hiring_status = 'Actively Hiring'
            """)
            actively_hiring = (await cursor.fetchone())["actively_hiring"]

            cursor = await db.execute("""
                SELECT COUNT(*) as dead_count
                FROM companies
                WHERE is_dead = 1
            """)
            dead_count = (await cursor.fetchone())["dead_count"]

            return {
                "total_companies": sum(status_counts.values()),
                "completed": status_counts.get("COMPLETED", 0),
                "pending": status_counts.get("PENDING", 0),
                "failed": status_counts.get("FAILED", 0),
                "in_progress": status_counts.get("IN_PROGRESS", 0),
                "dead_domains": dead_count,
                "actively_hiring_companies": actively_hiring,
                "total_openings": active_jobs,
                "ce_relevant_openings": ce_jobs,
                "total_historical_openings": total_historical_jobs,
            }

    async def search_companies(
        self,
        query: str = "",
        company_name: str = "",
        name: str = "",
        location: str = "",
        tech: str = "",
        hiring_status: str = "",
        status: str = "",
        limit: int | str = 25,
    ) -> list[dict[str, Any]]:
        """
        Search companies matching free-text query, company name, location, tech stack, hiring status, or pipeline status.
        Returns company records with deserialized JSON fields and opening counts.
        """
        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row
            conditions = []
            params: list[Any] = []

            if query:
                pattern = f"%{query.strip()}%"
                conditions.append(
                    "(c.company_name LIKE ? OR c.core_domain LIKE ? OR c.summary_explanation LIKE ? OR c.tech_stack LIKE ? OR c.goa_locations LIKE ?)"
                )
                params.extend([pattern, pattern, pattern, pattern, pattern])

            effective_name = company_name or name
            if effective_name:
                conditions.append("c.company_name LIKE ?")
                params.append(f"%{effective_name.strip()}%")

            if location:
                conditions.append("c.goa_locations LIKE ?")
                params.append(f"%{location.strip()}%")

            if tech:
                conditions.append("c.tech_stack LIKE ?")
                params.append(f"%{tech.strip()}%")

            if hiring_status:
                conditions.append("c.hiring_status LIKE ?")
                params.append(f"%{hiring_status.strip()}%")

            if status:
                conditions.append("c.status = ?")
                params.append(status.strip().upper())

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            sql = f"""
                SELECT c.*, COUNT(j.id) as opening_count
                FROM companies c
                LEFT JOIN job_openings j ON c.company_name = j.company_name AND j.is_active = 1
                {where_clause}
                GROUP BY c.company_name
                ORDER BY
                    CASE c.status WHEN 'COMPLETED' THEN 1 WHEN 'IN_PROGRESS' THEN 2 ELSE 3 END,
                    opening_count DESC,
                    c.company_name ASC
                LIMIT ?
            """
            try:
                int_limit = max(1, min(int(str(limit).strip()), 100))
            except (ValueError, TypeError):
                int_limit = 25
            params.append(int_limit)

            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    item = dict(row)
                    for f in ("goa_locations", "tech_stack"):
                        if item.get(f):
                            try:
                                item[f] = json.loads(item[f])
                            except Exception:
                                pass
                    results.append(item)
                return results

    async def get_company_profile(
        self, company_name: str, active_only: bool | str = True
    ) -> dict[str, Any] | None:
        """
        Retrieve full intelligence profile and discrete active job openings for a company.
        Supports case-insensitive exact or substring match.
        """
        target = str(company_name or "").strip()
        if not target:
            return None
        parsed_active = (
            active_only is True
            or str(active_only).strip().lower() in ("true", "1", "yes", "t")
        )

        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row

            # 1. Exact match (case-insensitive)
            async with db.execute(
                "SELECT * FROM companies WHERE LOWER(company_name) = LOWER(?)", (target,)
            ) as cursor:
                row = await cursor.fetchone()

            # 2. Substring match fallback
            if not row:
                async with db.execute(
                    "SELECT * FROM companies WHERE LOWER(company_name) LIKE LOWER(?) ORDER BY LENGTH(company_name) ASC LIMIT 1",
                    (f"%{target}%",),
                ) as cursor:
                    row = await cursor.fetchone()

            if not row:
                return None

            company = dict(row)
            for f in ("goa_locations", "tech_stack"):
                if company.get(f):
                    try:
                        company[f] = json.loads(company[f])
                    except Exception:
                        pass

            # Fetch discrete openings (active only by default)
            active_clause = "AND is_active = 1" if parsed_active else ""
            async with db.execute(
                f"SELECT * FROM job_openings WHERE company_name = ? {active_clause} ORDER BY id ASC",
                (company["company_name"],),
            ) as cursor:
                job_rows = await cursor.fetchall()
                jobs = []
                for jr in job_rows:
                    jd = dict(jr)
                    if jd.get("tech_stack"):
                        try:
                            jd["tech_stack"] = json.loads(jd["tech_stack"])
                        except Exception:
                            pass
                    jobs.append(jd)
                company["active_openings"] = jobs

            return company

    async def search_job_openings(
        self,
        query: str = "",
        title: str = "",
        tech: str = "",
        company_name: str = "",
        experience_level: str = "",
        location: str = "",
        only_ce_relevant: bool | str = False,
        active_only: bool | str = True,
        include_historical: bool | str = False,
        time_range: str = "",
        since: str = "",
        days: int | str | None = None,
        limit: int | str = 25,
    ) -> list[dict[str, Any]]:
        """
        Search job openings joined with company context.
        By default searches active openings (active_only=True).
        Supports FTS5 BM25 ranking, experience level synonym expansion,
        and date/time range filtering (e.g. 'this month', 'today', 'this week', days=30).
        """
        parsed_ce = (
            only_ce_relevant is True
            or str(only_ce_relevant).strip().lower() in ("true", "1", "yes", "t")
        )
        parsed_active = (
            active_only is True
            or str(active_only).strip().lower() in ("true", "1", "yes", "t")
        )
        parsed_hist = (
            include_historical is True
            or str(include_historical).strip().lower() in ("true", "1", "yes", "t")
        )
        parsed_days: int | None = None
        if days is not None:
            try:
                d = int(str(days).strip())
                if d > 0:
                    parsed_days = d
            except (ValueError, TypeError):
                parsed_days = None

        try:
            parsed_limit = max(1, min(int(str(limit).strip()), 100))
        except (ValueError, TypeError):
            parsed_limit = 25

        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row
            conditions = []
            params: list[Any] = []

            # Historical / Active filter
            if parsed_active and not parsed_hist:
                conditions.append("j.is_active = 1")

            # Time range / Date filtering
            now_utc = datetime.now(timezone.utc)
            cutoff_date: str | None = None

            if parsed_days and parsed_days > 0:
                cutoff_date = (now_utc - timedelta(days=parsed_days)).isoformat()
            elif time_range:
                tr = str(time_range).strip().lower()
                m_days = re.search(r"(\d+)\s*(?:day|days)", tr)
                m_weeks = re.search(r"(\d+)\s*(?:week|weeks)", tr)
                m_months = re.search(r"(\d+)\s*(?:month|months)", tr)
                if m_days:
                    cutoff_date = (now_utc - timedelta(days=int(m_days.group(1)))).isoformat()
                elif m_weeks:
                    cutoff_date = (now_utc - timedelta(days=int(m_weeks.group(1)) * 7)).isoformat()
                elif m_months:
                    cutoff_date = (now_utc - timedelta(days=int(m_months.group(1)) * 30)).isoformat()
                elif "today" in tr:
                    cutoff_date = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                elif "week" in tr:
                    cutoff_date = (now_utc - timedelta(days=7)).isoformat()
                elif "month" in tr:
                    cutoff_date = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
                elif "year" in tr:
                    cutoff_date = now_utc.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
                elif "recent" in tr:
                    cutoff_date = (now_utc - timedelta(days=30)).isoformat()
            elif since:
                cutoff_date = str(since).strip()

            if cutoff_date:
                conditions.append(
                    "(j.detected_at >= ? OR j.last_seen_at >= ? OR j.first_seen_at >= ?)"
                )
                params.extend([cutoff_date, cutoff_date, cutoff_date])

            fts_matched_ids: list[int] = []
            if query:
                # Attempt FTS5 token search if FTS table is available
                clean_q = re.sub(r"[^\w\s]", " ", query).strip()
                if clean_q:
                    fts_tokens = [f'"{tok}"' for tok in clean_q.split() if tok]
                    if fts_tokens:
                        fts_expr = " AND ".join(fts_tokens)
                        try:
                            async with db.execute(
                                "SELECT rowid FROM job_openings_fts WHERE job_openings_fts MATCH ? ORDER BY bm25(job_openings_fts) LIMIT ?",
                                (fts_expr, max(parsed_limit, 100)),
                            ) as fts_cur:
                                fts_matched_ids = [r[0] for r in await fts_cur.fetchall()]
                        except Exception:
                            fts_matched_ids = []

                q_pat = f"%{query.strip()}%"
                q_lower = query.lower().strip()
                fresher_synonyms = (
                    "fresher",
                    "freshers",
                    "entry",
                    "entry-level",
                    "entry level",
                    "intern",
                    "interns",
                    "internship",
                    "trainee",
                    "trainees",
                    "junior",
                    "graduate",
                )
                is_fresher_query = any(s in q_lower for s in fresher_synonyms)

                if fts_matched_ids:
                    placeholders = ",".join("?" for _ in fts_matched_ids)
                    if is_fresher_query:
                        conditions.append(
                            f"(j.id IN ({placeholders}) OR LOWER(j.experience_level) LIKE ? OR LOWER(j.title) LIKE ?)"
                        )
                        params.extend(fts_matched_ids)
                        params.extend([q_pat.lower(), q_pat.lower()])
                    else:
                        conditions.append(
                            f"(j.id IN ({placeholders}) OR LOWER(j.experience_level) LIKE ?)"
                        )
                        params.extend(fts_matched_ids)
                        params.append(q_pat.lower())
                else:
                    if is_fresher_query:
                        conditions.append(
                            "(j.title LIKE ? OR j.department LIKE ? OR j.tech_stack LIKE ? OR j.company_name LIKE ? OR "
                            "j.experience_level LIKE ? OR "
                            "(LOWER(j.title) LIKE '%intern%' AND LOWER(j.title) NOT LIKE '%international%' AND LOWER(j.title) NOT LIKE '%internal%') OR "
                            "j.title LIKE '%trainee%' OR j.title LIKE '%fresher%' OR j.title LIKE '%junior%' OR j.experience_level LIKE '%Fresher%')"
                        )
                        params.extend([q_pat, q_pat, q_pat, q_pat, q_pat])
                    else:
                        conditions.append(
                            "(j.title LIKE ? OR j.department LIKE ? OR j.tech_stack LIKE ? OR j.company_name LIKE ? OR j.experience_level LIKE ?)"
                        )
                        params.extend([q_pat, q_pat, q_pat, q_pat, q_pat])

            if title:
                conditions.append("(j.title LIKE ? OR j.department LIKE ?)")
                params.extend([f"%{title.strip()}%", f"%{title.strip()}%"])

            if tech:
                conditions.append("j.tech_stack LIKE ?")
                params.append(f"%{tech.strip()}%")

            if company_name:
                conditions.append("j.company_name LIKE ?")
                params.append(f"%{company_name.strip()}%")

            if experience_level:
                exp_lower = str(experience_level).lower().strip()
                fresher_synonyms = (
                    "fresher",
                    "freshers",
                    "entry",
                    "entry-level",
                    "entry level",
                    "intern",
                    "interns",
                    "internship",
                    "trainee",
                    "trainees",
                    "graduate",
                    "junior",
                    "0-1",
                    "0-2",
                    "0 years",
                )
                if any(syn in exp_lower for syn in fresher_synonyms):
                    conditions.append(
                        "(LOWER(j.experience_level) LIKE '%fresher%' OR "
                        "LOWER(j.experience_level) LIKE '%intern%' OR "
                        "LOWER(j.experience_level) LIKE '%entry%' OR "
                        "LOWER(j.experience_level) LIKE '%trainee%' OR "
                        "LOWER(j.experience_level) LIKE '%junior%' OR "
                        "LOWER(j.title) LIKE '%fresher%' OR "
                        "(LOWER(j.title) LIKE '%intern%' AND LOWER(j.title) NOT LIKE '%international%' AND LOWER(j.title) NOT LIKE '%internal%') OR "
                        "LOWER(j.title) LIKE '%trainee%' OR "
                        "LOWER(j.title) LIKE '%junior%' OR "
                        "LOWER(j.title) LIKE '%graduate%' OR "
                        "LOWER(j.title) LIKE '%entry level%' OR "
                        "LOWER(j.title) LIKE '%entry-level%')"
                    )
                else:
                    conditions.append("j.experience_level LIKE ?")
                    params.append(f"%{experience_level.strip()}%")

            if location:
                conditions.append("c.goa_locations LIKE ?")
                params.append(f"%{location.strip()}%")

            if parsed_ce:
                conditions.append("j.is_computer_eng_relevant = 1")

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            sql = f"""
                SELECT j.*, c.goa_locations, c.website_url, c.careers_url, c.careers_email, c.core_domain
                FROM job_openings j
                JOIN companies c ON j.company_name = c.company_name
                {where_clause}
                ORDER BY j.id DESC
                LIMIT ?
            """
            params.append(parsed_limit)

            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    item = dict(row)
                    for f in ("tech_stack", "goa_locations"):
                        if item.get(f):
                            try:
                                item[f] = json.loads(item[f])
                            except Exception:
                                pass
                    results.append(item)
                return results

    async def execute_read_only_query(
        self, sql_query: str, limit: int | str = 50
    ) -> list[dict[str, Any]]:
        """
        Safely execute a read-only SELECT query against the SQLite database.
        Strictly forbids mutation queries or statements altering tables/schema.
        """
        cleaned = str(sql_query or "").strip()
        if not cleaned:
            return []

        # 1. Strip markdown code fences if present (e.g. ```sql ... ```)
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        # 2. Strip comments and string literals to inspect SQL syntax and keywords safely
        syntax_probe = re.sub(r"--[^\n]*", " ", cleaned)
        syntax_probe = re.sub(r"/\*.*?\*/", " ", syntax_probe, flags=re.DOTALL)
        syntax_probe = re.sub(r"'(''|[^'])*'", "''", syntax_probe)
        syntax_probe = re.sub(r'"(""|[^"])*"', '""', syntax_probe)

        # Clean trailing semicolons and whitespace from both
        syntax_probe = re.sub(r";+\s*$", "", syntax_probe).strip()
        cleaned = re.sub(r";+\s*(--[^\n]*|/\*.*?\*/)?\s*$", "", cleaned, flags=re.DOTALL).strip()
        cleaned = re.sub(r";+\s*$", "", cleaned).strip()

        if ";" in syntax_probe:
            raise ValueError("Multiple SQL statements are not permitted.")

        tokens = syntax_probe.split()
        first_token = tokens[0].lstrip("(").upper() if tokens else ""
        if first_token not in ("SELECT", "WITH"):
            raise ValueError("Only read-only SELECT or WITH statements are allowed.")

        forbidden = [
            "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
            r"REPLACE\s+INTO", "TRUNCATE", "ATTACH", "DETACH", "PRAGMA", "VACUUM", "EXEC"
        ]
        pattern = r"\b(" + "|".join(forbidden) + r")\b"
        if re.search(pattern, syntax_probe, re.IGNORECASE):
            raise ValueError("Modifying or administrative SQL statements are forbidden.")

        try:
            int_limit = max(1, min(int(str(limit).strip()), 100))
        except (ValueError, TypeError):
            int_limit = 50

        if not re.search(r"\bLIMIT\b", syntax_probe, re.IGNORECASE):
            cleaned += f"\nLIMIT {int_limit}"

        try:
            db_uri = f"file:{self.db_path.resolve().as_posix()}?mode=ro"
            conn_context = aiosqlite.connect(db_uri, uri=True)
        except Exception:
            conn_context = self._get_connection()

        async with conn_context as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(cleaned) as cursor:
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    d = dict(row)
                    for k, v in d.items():
                        if isinstance(v, str) and (v.startswith("[") or v.startswith("{")):
                            try:
                                d[k] = json.loads(v)
                            except Exception:
                                pass
                    results.append(d)
                return results

    async def get_context_summary(self) -> dict[str, Any]:
        """Generate high-level context summary for Gemini reasoning and prompt grounding."""
        stats = await self.get_stats()
        companies = await self.get_all_companies()
        completed = [c for c in companies if c.get("status") == "COMPLETED"]
        actively_hiring = [
            c["company_name"] for c in completed if c.get("hiring_status") == "Actively Hiring"
        ]

        locations_set: set[str] = set()
        tech_set: set[str] = set()
        for c in completed:
            if c.get("goa_locations"):
                try:
                    locs = json.loads(c["goa_locations"]) if isinstance(c["goa_locations"], str) else c["goa_locations"]
                    for loc in locs:
                        locations_set.add(str(loc))
                except Exception:
                    pass
            if c.get("tech_stack"):
                try:
                    techs = json.loads(c["tech_stack"]) if isinstance(c["tech_stack"], str) else c["tech_stack"]
                    for t in techs:
                        tech_set.add(str(t))
                except Exception:
                    pass

        return {
            "statistics": stats,
            "total_monitored_companies": len(companies),
            "completed_companies_count": len(completed),
            "actively_hiring_companies": actively_hiring[:20],
            "known_goa_locations": sorted(list(locations_set))[:20],
            "popular_tech_stacks": sorted(list(tech_set))[:30],
        }

    async def export_markdown_digest(self, output_path: Path | None = None) -> Path:
        """
        Generate a comprehensive, human-readable markdown digest (goa_tech_digest.md)
        grouping active Computer Engineering roles by tech stack and location.
        """
        out_file = output_path or (config.EXPORTS_DIR / "goa_tech_digest.md")
        out_file.parent.mkdir(parents=True, exist_ok=True)

        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row

            # Fetch companies
            async with db.execute("""
                SELECT * FROM companies WHERE status = 'COMPLETED' ORDER BY company_name ASC
            """) as cursor:
                companies = [dict(r) for r in await cursor.fetchall()]

            # Fetch CE-relevant active jobs
            async with db.execute("""
                SELECT j.*, c.goa_locations, c.website_url, c.careers_email
                FROM job_openings j
                JOIN companies c ON j.company_name = c.company_name
                WHERE j.is_computer_eng_relevant = 1 AND j.is_active = 1
                ORDER BY j.company_name ASC, j.title ASC
            """) as cursor:
                jobs = [dict(r) for r in await cursor.fetchall()]

        stats = await self.get_stats()

        # Grouping jobs by location
        location_jobs = defaultdict(list)
        # Grouping jobs by tech stack keyword
        tech_jobs = defaultdict(list)

        for job in jobs:
            # Parse locations
            loc_raw = job.get("goa_locations")
            locations = json.loads(loc_raw) if loc_raw else ["Goa (General)"]
            if not locations:
                locations = ["Goa (General)"]
            for loc in locations:
                location_jobs[loc.strip().title()].append(job)

            # Parse tech stack
            stack_raw = job.get("tech_stack")
            stack = json.loads(stack_raw) if stack_raw else []
            if not stack:
                tech_jobs["General Software / Not Specified"].append(job)
            else:
                for tech in stack:
                    tech_clean = tech.strip()
                    tech_jobs[tech_clean].append(job)

        # Build Markdown content
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            "# Goa Tech & Engineering Career Intelligence Digest",
            f"*Generated on: {now_str}*",
            "",
            "## 1. Executive Summary & Pipeline Metrics",
            "",
            "| Metric | Count |",
            "| :--- | :--- |",
            f"| **Total Companies Monitored** | {stats['total_companies']} |",
            f"| **Scraped & Analyzed (Completed)** | {stats['completed']} |",
            f"| **Pending / Queue** | {stats['pending']} |",
            f"| **Failed (Needs Review)** | {stats['failed']} |",
            f"| **Actively Hiring Companies** | {stats['actively_hiring_companies']} |",
            f"| **Total Active Openings** | {stats['total_openings']} |",
            f"| **Computer Engineering Relevant Roles** | {stats['ce_relevant_openings']} |",
            "",
            "---",
            "",
            "## 2. Active Roles by Goa Office Location",
            "",
        ]

        if not location_jobs:
            lines.append("*No active openings identified yet.*")
        else:
            for loc in sorted(location_jobs.keys()):
                loc_list = location_jobs[loc]
                lines.append(f"### 📍 {loc} ({len(loc_list)} Openings)")
                lines.append("")
                lines.append(
                    "| Company | Role Title | Experience | Tech Stack | Apply |"
                )
                lines.append("| :--- | :--- | :--- | :--- | :--- |")
                for j in loc_list:
                    stack_list = (
                        json.loads(j["tech_stack"]) if j.get("tech_stack") else []
                    )
                    stack_str = ", ".join(stack_list[:4])
                    apply_link = (
                        f"[Apply Here]({j['apply_url']})"
                        if j.get("apply_url")
                        else (j.get("careers_email") or "Via Careers Page")
                    )
                    lines.append(
                        f"| **{j['company_name']}** | {j['title']} | {j.get('experience_level', 'Unknown')} | {stack_str} | {apply_link} |"
                    )
                lines.append("")

        lines.extend(
            [
                "---",
                "",
                "## 3. Active Roles by Primary Tech Stack",
                "",
            ]
        )

        if not tech_jobs:
            lines.append("*No technology tags detected yet.*")
        else:
            # Sort tech by popularity
            sorted_tech = sorted(
                tech_jobs.items(), key=lambda x: len(x[1]), reverse=True
            )
            for tech, t_jobs in sorted_tech[:25]:  # Top 25 tech categories
                lines.append(f"### 💻 {tech} ({len(t_jobs)} Roles)")
                lines.append("")
                for j in t_jobs:
                    apply_info = (
                        f"[Link]({j['apply_url']})"
                        if j.get("apply_url")
                        else (j.get("careers_email") or "Direct")
                    )
                    lines.append(
                        f"- **{j['company_name']}**: {j['title']} ({j.get('experience_level', 'N/A')}) — {apply_info}"
                    )
                lines.append("")

        lines.extend(
            [
                "---",
                "",
                "## 4. Comprehensive Goan Companies Intelligence Directory",
                "",
            ]
        )

        for c in companies:
            locs = json.loads(c["goa_locations"]) if c.get("goa_locations") else []
            locs_str = ", ".join(locs) if locs else "Goa"
            stack = json.loads(c["tech_stack"]) if c.get("tech_stack") else []
            stack_str = ", ".join(stack) if stack else "Various"

            lines.append(
                f"### {c['company_name']} (`{c.get('hiring_status', 'Unknown')}`)"
            )
            lines.append(f"- **Domain**: {c.get('core_domain', 'Technology')}")
            lines.append(f"- **Goa Hub(s)**: {locs_str}")
            lines.append(f"- **Tech Stack**: {stack_str}")
            if c.get("website_url"):
                lines.append(f"- **Website**: [{c['website_url']}]({c['website_url']})")
            if c.get("careers_url"):
                lines.append(
                    f"- **Careers Page**: [{c['careers_url']}]({c['careers_url']})"
                )
            if c.get("careers_email"):
                lines.append(
                    f"- **Contact / Resume Submission**: `{c['careers_email']}`"
                )
            if c.get("summary_explanation"):
                lines.append(f"- **Engineering Fit**: {c['summary_explanation']}")
            if c.get("recent_news_summary"):
                lines.append(f"- **Recent Developments**: {c['recent_news_summary']}")

            # List company jobs
            comp_jobs = [j for j in jobs if j["company_name"] == c["company_name"]]
            if comp_jobs:
                lines.append("- **Active Openings**:")
                for j in comp_jobs:
                    lines.append(
                        f"  * **{j['title']}** ({j.get('experience_level', 'Unknown')})"
                    )
            lines.append("")

        out_file.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Exported markdown digest to %s", out_file)
        return out_file

    async def export_json_digest(self, output_path: Path | None = None) -> Path:
        """Export all companies and openings into a structured JSON file."""
        out_file = output_path or (config.EXPORTS_DIR / "goa_tech_digest.json")
        out_file.parent.mkdir(parents=True, exist_ok=True)

        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM companies ORDER BY company_name ASC"
            ) as cursor:
                companies = [dict(r) for r in await cursor.fetchall()]

            async with db.execute(
                "SELECT * FROM job_openings ORDER BY company_name ASC"
            ) as cursor:
                jobs = [dict(r) for r in await cursor.fetchall()]

        # Attach jobs to companies
        active_jobs_by_company = defaultdict(list)
        all_jobs_by_company = defaultdict(list)
        for j in jobs:
            if j.get("tech_stack"):
                try:
                    j["tech_stack"] = json.loads(j["tech_stack"])
                except Exception:
                    pass
            all_jobs_by_company[j["company_name"]].append(j)
            if j.get("is_active", 1):
                active_jobs_by_company[j["company_name"]].append(j)

        for c in companies:
            for field in ("goa_locations", "tech_stack"):
                if c.get(field):
                    try:
                        c[field] = json.loads(c[field])
                    except Exception:
                        pass
            c["active_openings"] = active_jobs_by_company.get(c["company_name"], [])
            c["historical_openings"] = all_jobs_by_company.get(c["company_name"], [])

        stats = await self.get_stats()
        payload = {
            "metadata": {
                "generated_at": get_utc_now(),
                "statistics": stats,
            },
            "companies": companies,
        }

        out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Exported JSON digest to %s", out_file)
        return out_file

    async def create_job_alert(
        self,
        email: str,
        tech_filter: list[str] | None = None,
        location_filter: list[str] | None = None,
        experience_filter: str | None = None,
        ce_only: bool = False,
    ) -> dict[str, Any]:
        """Create a job alert subscription with a unique unsubscribe token."""
        import secrets

        token = secrets.token_urlsafe(24)
        now = get_utc_now()
        tech_json = json.dumps(tech_filter or [])
        loc_json = json.dumps(location_filter or [])

        async with self._get_connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO job_alerts (
                    email, tech_filter, location_filter, experience_filter,
                    ce_only, created_at, is_active, unsubscribe_token
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    email.strip().lower(),
                    tech_json,
                    loc_json,
                    experience_filter,
                    1 if ce_only else 0,
                    now,
                    token,
                ),
            )
            alert_id = getattr(cursor, "lastrowid", 1)
            await db.commit()
            return {
                "id": alert_id,
                "email": email.strip().lower(),
                "unsubscribe_token": token,
                "message": "Subscribed to job alerts successfully.",
            }

    async def get_active_alerts(self) -> list[dict[str, Any]]:
        """Retrieve all currently active job alerts for notification processing."""
        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM job_alerts WHERE is_active = 1"
            ) as cursor:
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    d = dict(row)
                    for k in ("tech_filter", "location_filter"):
                        if d.get(k):
                            try:
                                d[k] = json.loads(d[k])
                            except Exception:
                                d[k] = []
                    results.append(d)
                return results

    async def unsubscribe_alert(self, token: str) -> bool:
        """Deactivate a job alert subscription via its unsubscribe token."""
        if not token or not token.strip():
            return False
        async with self._get_connection() as db:
            cursor = await db.execute(
                "UPDATE job_alerts SET is_active = 0 WHERE unsubscribe_token = ?",
                (token.strip(),),
            )
            await db.commit()
            return getattr(cursor, "rowcount", 0) > 0 if hasattr(cursor, "rowcount") else True

    async def get_government_jobs(self, upcoming: bool = True) -> list[dict[str, Any]]:
        """Retrieve government/PSU jobs with deadline status and parsed attachments."""
        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row
            sql = """
                SELECT j.*, c.website_url, c.goa_locations
                FROM job_openings j
                JOIN companies c ON j.company_name = c.company_name
                WHERE (j.is_government = 1 OR j.source_type = 'PDF'
                       OR LOWER(j.company_name) LIKE '%gov%'
                       OR LOWER(j.company_name) LIKE '%gpsc%'
                       OR LOWER(j.company_name) LIKE '%cbes%'
                       OR LOWER(j.company_name) LIKE '%autonomous%'
                       OR LOWER(j.company_name) LIKE '%directorate%')
                  AND j.is_active = 1
                ORDER BY
                    CASE WHEN j.application_deadline IS NOT NULL AND j.application_deadline != '' THEN 0 ELSE 1 END,
                    j.application_deadline ASC,
                    j.first_seen_at DESC
            """
            async with db.execute(sql) as cursor:
                rows = await cursor.fetchall()
                results = []
                for r in rows:
                    d = dict(r)
                    for k in ("tech_stack", "goa_locations"):
                        if d.get(k):
                            try:
                                d[k] = json.loads(d[k])
                            except Exception:
                                pass
                    results.append(d)
                return results

    async def get_hiring_trends(self) -> dict[str, Any]:
        """Aggregate hiring trends across active/closed jobs, tech stacks, and locations."""
        async with self._get_connection() as db:
            db.row_factory = aiosqlite.Row

            # 1. Weekly job openings (last 12 weeks)
            async with db.execute("""
                SELECT substr(first_seen_at, 1, 10) as day_date, count(*) as count
                FROM job_openings
                WHERE first_seen_at != '' AND first_seen_at IS NOT NULL
                GROUP BY day_date
                ORDER BY day_date DESC
                LIMIT 60
            """) as cursor:
                date_rows = await cursor.fetchall()

            weekly_map: dict[str, int] = defaultdict(int)
            for r in date_rows:
                day_val = r["day_date"] if isinstance(r, (dict, aiosqlite.Row, TursoRow)) else r[0]
                cnt_val = r["count"] if isinstance(r, (dict, aiosqlite.Row, TursoRow)) else r[1]
                try:
                    dt = datetime.fromisoformat(str(day_val))
                    week_label = f"W{dt.isocalendar()[1]} ({dt.strftime('%b %Y')})"
                    weekly_map[week_label] += cnt_val
                except Exception:
                    weekly_map[str(day_val)] += cnt_val

            # 2. Top 10 hiring companies
            async with db.execute("""
                SELECT company_name, count(*) as count
                FROM job_openings
                WHERE is_active = 1
                GROUP BY company_name
                ORDER BY count DESC
                LIMIT 10
            """) as cursor:
                top_companies = [dict(r) for r in await cursor.fetchall()]

            # 3. Active vs Closed jobs
            async with db.execute("""
                SELECT is_active, count(*) as count
                FROM job_openings
                GROUP BY is_active
            """) as cursor:
                active_closed_rows = await cursor.fetchall()
                active_count = sum(r["count"] for r in active_closed_rows if r["is_active"] == 1)
                closed_count = sum(r["count"] for r in active_closed_rows if r["is_active"] == 0)

            # 4. Government vs Private
            async with db.execute("""
                SELECT is_government, count(*) as count
                FROM job_openings
                WHERE is_active = 1
                GROUP BY is_government
            """) as cursor:
                govt_rows = await cursor.fetchall()
                govt_count = sum(r["count"] for r in govt_rows if r["is_government"] == 1)
                private_count = sum(r["count"] for r in govt_rows if r["is_government"] == 0)

            # 5. Tech stack frequency across active jobs
            async with db.execute("SELECT tech_stack FROM job_openings WHERE is_active = 1") as cursor:
                tech_rows = await cursor.fetchall()
                tech_counts: dict[str, int] = defaultdict(int)
                for r in tech_rows:
                    raw = r["tech_stack"] if isinstance(r, (dict, aiosqlite.Row, TursoRow)) else r[0]
                    if raw:
                        try:
                            stack = json.loads(raw) if isinstance(raw, str) else raw
                            for item in stack:
                                tech_counts[item.strip()] += 1
                        except Exception:
                            pass
                top_tech = sorted(
                    [{"name": k, "count": v} for k, v in tech_counts.items()],
                    key=lambda x: x["count"],
                    reverse=True
                )[:15]

            # 6. Jobs by location
            async with db.execute("""
                SELECT c.goa_locations, count(j.id) as count
                FROM companies c
                JOIN job_openings j ON c.company_name = j.company_name
                WHERE j.is_active = 1
                GROUP BY c.company_name
            """) as cursor:
                loc_rows = await cursor.fetchall()
                loc_counts: dict[str, int] = defaultdict(int)
                for r in loc_rows:
                    raw = r["goa_locations"] if isinstance(r, (dict, aiosqlite.Row, TursoRow)) else r[0]
                    cnt = r["count"] if isinstance(r, (dict, aiosqlite.Row, TursoRow)) else r[1]
                    if raw:
                        try:
                            locs = json.loads(raw) if isinstance(raw, str) else raw
                            for loc in locs:
                                loc_counts[loc.strip()] += cnt
                        except Exception:
                            pass
                top_locations = sorted(
                    [{"name": k, "count": v} for k, v in loc_counts.items()],
                    key=lambda x: x["count"],
                    reverse=True
                )[:10]

            return {
                "weekly_trends": [{"week": k, "jobs": v} for k, v in list(weekly_map.items())[:12]],
                "top_companies": top_companies,
                "top_tech_stack": top_tech,
                "jobs_by_location": top_locations,
                "active_vs_closed": {"active": active_count, "closed": closed_count},
                "govt_vs_private": {"government": govt_count, "private": private_count},
            }

    async def compare_companies(self, names: list[str]) -> list[dict[str, Any]]:
        """Retrieve comparative side-by-side metrics for given company names."""
        results = []
        for name in names:
            prof = await self.get_company_profile(name, active_only=False)
            if prof:
                results.append(prof)
        return results

    async def get_search_suggestions(self, query: str, limit: int = 10) -> list[str]:
        """Return quick auto-suggestions for job titles, tech keywords, and company names."""
        q = (query or "").strip().lower()
        if not q:
            return []

        suggestions: list[str] = []
        seen: set[str] = set()

        async with self._get_connection() as db:
            # 1. Company names
            async with db.execute(
                "SELECT company_name FROM companies WHERE LOWER(company_name) LIKE ? LIMIT ?",
                (f"{q}%", limit)
            ) as cur:
                for r in await cur.fetchall():
                    val = r[0] if isinstance(r, (list, tuple)) else r["company_name"]
                    if val and val.lower() not in seen:
                        seen.add(val.lower())
                        suggestions.append(val)

            # 2. Job titles
            if len(suggestions) < limit:
                async with db.execute(
                    "SELECT DISTINCT title FROM job_openings WHERE LOWER(title) LIKE ? LIMIT ?",
                    (f"%{q}%", limit - len(suggestions))
                ) as cur:
                    for r in await cur.fetchall():
                        val = r[0] if isinstance(r, (list, tuple)) else r["title"]
                        if val and val.lower() not in seen:
                            seen.add(val.lower())
                            suggestions.append(val)

            return suggestions[:limit]

    async def export_jobs_csv(self, output_path: Path | None = None) -> str:
        """Generate CSV string of active job openings and optionally write to file."""
        import csv
        import io

        jobs = await self.search_job_openings(limit=1000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID", "Company", "Title", "Department", "Experience Level",
            "Tech Stack", "CE Relevant", "Apply URL", "Source Type",
            "Source URL", "First Seen At", "Application Deadline", "Is Government"
        ])
        for j in jobs:
            stack = ", ".join(j.get("tech_stack", [])) if isinstance(j.get("tech_stack"), list) else str(j.get("tech_stack") or "")
            writer.writerow([
                j.get("id"),
                j.get("company_name"),
                j.get("title"),
                j.get("department"),
                j.get("experience_level"),
                stack,
                j.get("is_computer_eng_relevant"),
                j.get("apply_url"),
                j.get("source_type"),
                j.get("source_url"),
                j.get("first_seen_at"),
                j.get("application_deadline"),
                j.get("is_government"),
            ])
        csv_text = output.getvalue()
        if output_path:
            out_p = Path(output_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(csv_text, encoding="utf-8")
        return csv_text

    async def export_companies_csv(self, output_path: Path | None = None) -> str:
        """Generate CSV string of all monitored companies and optionally write to file."""
        import csv
        import io

        comps = await self.get_all_companies()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Company Name", "Website", "Careers URL", "Core Domain",
            "Hiring Status", "Goa Locations", "Tech Stack", "Contact Email",
            "Status", "Last Scraped At", "Is Dead"
        ])
        for c in comps:
            locs = ", ".join(c.get("goa_locations", [])) if isinstance(c.get("goa_locations"), list) else str(c.get("goa_locations") or "")
            tech = ", ".join(c.get("tech_stack", [])) if isinstance(c.get("tech_stack"), list) else str(c.get("tech_stack") or "")
            writer.writerow([
                c.get("company_name"),
                c.get("website_url"),
                c.get("careers_url"),
                c.get("core_domain"),
                c.get("hiring_status"),
                locs,
                tech,
                c.get("careers_email"),
                c.get("status"),
                c.get("last_scraped_at"),
                c.get("is_dead"),
            ])
        csv_text = output.getvalue()
        if output_path:
            out_p = Path(output_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(csv_text, encoding="utf-8")
        return csv_text

    async def get_latest_jobs_for_feed(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve latest active job openings formatted for RSS/Atom feed."""
        return await self.search_job_openings(limit=limit)
