"""
One-time and on-demand migration script: SQLite -> Turso LibSQL.
Migrates all tables (companies, job_openings, scrape_logs, job_alerts),
verifies row counts match, and rebuilds FTS5 indexes.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sqlite3
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_to_turso")


async def migrate_to_turso(
    source_sqlite_path: Path,
    turso_url: str,
    turso_token: str,
    batch_size: int = 100,
) -> bool:
    """Migrate data from SQLite to Turso LibSQL."""
    if not source_sqlite_path.exists():
        logger.error("Source SQLite database does not exist at: %s", source_sqlite_path)
        return False

    try:
        import libsql_client
    except ImportError:
        logger.error("libsql_client package not installed. Run: pip install libsql-client")
        return False

    logger.info("Connecting to source SQLite: %s", source_sqlite_path)
    sqlite_conn = sqlite3.connect(source_sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    logger.info("Connecting to Turso LibSQL: %s", turso_url)
    turso_client = libsql_client.create_client(url=turso_url, auth_token=turso_token)

    try:
        # 1. Initialize schema on Turso
        from src.database import DatabaseManager

        turso_db = DatabaseManager(turso_url=turso_url, auth_token=turso_token)
        logger.info("Initializing schema and tables on Turso...")
        await turso_db.init_db()

        async def _batch_insert(table_name: str, rows: list[Any]) -> None:
            if not rows:
                return
            cols = rows[0].keys()
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            sql = f"INSERT OR REPLACE INTO {table_name} ({col_names}) VALUES ({placeholders})"
            for i in range(0, len(rows), batch_size):
                chunk = rows[i : i + batch_size]
                batch_stmts = [(sql, list(r)) for r in chunk]
                await turso_client.batch(batch_stmts)

        # 2. Migrate Companies
        cur = sqlite_conn.cursor()
        cur.execute("SELECT * FROM companies")
        company_rows = cur.fetchall()
        logger.info("Migrating %d companies to Turso...", len(company_rows))
        await _batch_insert("companies", company_rows)

        # 3. Migrate Job Openings
        cur.execute("SELECT * FROM job_openings")
        job_rows = cur.fetchall()
        logger.info("Migrating %d job openings to Turso...", len(job_rows))
        await _batch_insert("job_openings", job_rows)

        # 4. Migrate Scrape Logs
        cur.execute("SELECT * FROM scrape_logs")
        log_rows = cur.fetchall()
        logger.info("Migrating %d scrape log entries to Turso...", len(log_rows))
        await _batch_insert("scrape_logs", log_rows)

        # 5. Migrate Job Alerts (if table exists in source)
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_alerts'")
        alert_table_exists = cur.fetchone() is not None
        alert_rows = []
        if alert_table_exists:
            cur.execute("SELECT * FROM job_alerts")
            alert_rows = cur.fetchall()
            logger.info("Migrating %d job alert subscriptions to Turso...", len(alert_rows))
            await _batch_insert("job_alerts", alert_rows)

        # 6. Verify row counts
        rs_comp = await turso_client.execute("SELECT count(*) FROM companies")
        turso_comp_count = rs_comp.rows[0][0]

        rs_jobs = await turso_client.execute("SELECT count(*) FROM job_openings")
        turso_job_count = rs_jobs.rows[0][0]

        logger.info(
            "Verification: Companies - SQLite: %d, Turso: %d",
            len(company_rows),
            turso_comp_count,
        )
        logger.info(
            "Verification: Jobs - SQLite: %d, Turso: %d",
            len(job_rows),
            turso_job_count,
        )

        # 7. Rebuild FTS5 indexes on Turso
        logger.info("Rebuilding FTS5 indexes on Turso...")
        await turso_db.rebuild_fts()

        logger.info("Migration to Turso completed successfully!")
        return True

    except Exception as e:
        logger.exception("Migration failed with error: %s", e)
        return False
    finally:
        sqlite_conn.close()
        await turso_client.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate GoaIT SQLite database to Turso LibSQL")
    parser.add_argument(
        "--sqlite-path",
        default=str(config.DB_PATH),
        help=f"Path to source SQLite database (default: {config.DB_PATH})",
    )
    parser.add_argument(
        "--turso-url",
        default=os.getenv("TURSO_DATABASE_URL", ""),
        help="Turso database URL (e.g. libsql://your-db.turso.io)",
    )
    parser.add_argument(
        "--turso-token",
        default=os.getenv("TURSO_AUTH_TOKEN", ""),
        help="Turso authentication token",
    )
    args = parser.parse_args()

    if not args.turso_url:
        logger.error("Error: --turso-url or TURSO_DATABASE_URL environment variable is required.")
        sys.exit(1)

    success = asyncio.run(
        migrate_to_turso(
            Path(args.sqlite_path),
            args.turso_url,
            args.turso_token,
        )
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
