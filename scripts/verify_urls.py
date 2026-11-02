"""
CLI Script to verify website and careers URLs for all companies in the seed list.
Scans DNS validity, HTTP status codes, redirects, parked domains,
probes alternative careers pages, exports reports, and optionally updates the seed list and database.

Usage:
    .venv\\Scripts\\python scripts\\verify_urls.py
    .venv\\Scripts\\python scripts\\verify_urls.py --limit 10
    .venv\\Scripts\\python scripts\\verify_urls.py --apply --update-db
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import config
from src.database import DatabaseManager
from src.url_verifier import (
    apply_corrections_to_seed,
    export_reports,
    sync_database_with_reports,
    verify_all_companies,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("verify-urls")


async def main_async(args: argparse.Namespace) -> None:
    seed_path = Path(args.seed_file) if args.seed_file else config.SEED_FILE_PATH
    if not seed_path.exists():
        logger.error("Seed file not found at %s", seed_path)
        sys.exit(1)

    with open(seed_path, "r", encoding="utf-8") as f:
        seeds = json.load(f)

    if args.limit and args.limit > 0:
        seeds = seeds[: args.limit]
        logger.info("Scanning subset of %d companies", len(seeds))
    else:
        logger.info("Loaded %d companies from %s", len(seeds), seed_path)

    print("\n" + "=" * 70, flush=True)
    print("GOA TECH INTELLIGENCE - URL & DOMAIN HEALTH SCANNER", flush=True)
    print("=" * 70, flush=True)
    print(f"Target Seed File   : {seed_path}", flush=True)
    print(f"Total Companies    : {len(seeds)}", flush=True)
    print(f"Concurrency        : {args.concurrency}", flush=True)
    print(f"Timeout            : {args.timeout}s", flush=True)
    print(f"Probe Careers      : {not args.no_probe}", flush=True)
    print(f"Apply to Seed      : {args.apply}", flush=True)
    print(f"Update Database    : {args.update_db}", flush=True)
    print("=" * 70 + "\n", flush=True)

    def on_progress(done: int, total: int, rep) -> None:
        if done % 10 == 0 or done == total:
            status_tag = f"[{rep.classification}]"
            logger.info(
                "Progress: %d/%d (%d%%) - Last checked: %s %s",
                done,
                total,
                int(done * 100 / total),
                rep.company_name,
                status_tag,
            )

    reports, summary = await verify_all_companies(
        seeds=seeds,
        concurrency=args.concurrency,
        timeout=args.timeout,
        probe_careers=not args.no_probe,
        on_progress=on_progress,
    )

    # Export reports
    json_path = (
        Path(args.output_json)
        if args.output_json
        else config.EXPORTS_DIR / "url_health_report.json"
    )
    md_path = (
        Path(args.output_md)
        if args.output_md
        else config.EXPORTS_DIR / "url_health_report.md"
    )

    export_reports(reports, summary, json_path=json_path, md_path=md_path)

    print("\n" + "=" * 70)
    print("URL HEALTH AUDIT SUMMARY")
    print("=" * 70)
    print(f"Total Companies Monitored        : {summary['total_monitored']}")
    print(f"Active Reachable Companies       : {summary['active_companies']}")
    print(f"Redirected / Canonical Domains   : {summary['redirected_websites']}")
    print(f"Dead Domains (DNS Failure)       : {summary['dead_dns_domains']}")
    print(f"Unreachable Domains (HTTP/Timeout): {summary['dead_http_domains']}")
    print(f"Parked / Expired Domains         : {summary['parked_domains']}")
    print(f"Broken Careers URLs              : {summary['broken_careers_urls']}")
    print(f"Discovered Alternative Careers   : {summary['discovered_alternative_careers']}")
    print(f"Detailed JSON Report             : {json_path}")
    print(f"Detailed Markdown Report         : {md_path}")
    print("=" * 70 + "\n")

    # Optionally apply corrections to seed file
    if args.apply:
        updated = apply_corrections_to_seed(
            seeds=seeds, reports=reports, seed_path=seed_path, backup=True
        )
        print(f"[+] Applied canonical and discovered URLs to {updated} companies in {seed_path}")

    # Optionally update SQLite database
    if args.update_db:
        db = DatabaseManager(db_path=Path(args.db_path) if args.db_path else config.DB_PATH)
        await db.init_db()
        db_updated = await sync_database_with_reports(db, reports)
        print(f"[+] Synced {db_updated} company records to SQLite database at {db.db_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify URL validity, redirects, and dead domains for Goa tech companies."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of companies to check (useful for quick verification)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=20,
        help="Number of concurrent verification workers (default: 20)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP request timeout in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--seed-file",
        type=str,
        default=None,
        help="Path to companies_seed.json",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply canonical redirected URLs and discovered career pages to companies_seed.json",
    )
    parser.add_argument(
        "--update-db",
        action="store_true",
        help="Update the SQLite database with verified canonical URLs and dead flags",
    )
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="Disable probing alternative career paths (/careers, /jobs, etc.) when original 404s",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default=None,
        help="Output path for JSON health report",
    )
    parser.add_argument(
        "--output-md",
        type=str,
        default=None,
        help="Output path for Markdown health report",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
