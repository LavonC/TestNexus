"""
Async orchestrator and CLI entrypoint for the Goa Tech Career Intelligence Pipeline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx

from src.cli import run_interactive_cli, run_single_query
from src.config import config
from src.database import DatabaseManager
from src.gemini_agent import GeminiIntelligenceAgent
from src.models import ScrapedData
from src.scraper import Scraper

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("goa-job-intel")


class PipelineOrchestrator:
    """Manages end-to-end async scraping, Gemini extraction, and checkpoint commits."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        concurrency: int = 10,
        api_key: str | None = None,
        api_keys: list[str] | str | None = None,
        model_name: str | None = None,
        enable_grounding: bool = False,
        batch_size: int = 1,
        use_local_llm: bool = False,
        rate_limit_rpm: float | None = None,
        ollama_base_url: str | None = None,
        ollama_model: str | None = None,
        offline: bool | None = None,
    ):
        self.db = db_manager
        self.scraper = Scraper(concurrency=concurrency)
        self.enable_grounding = enable_grounding
        self.batch_size = batch_size
        self.concurrency = concurrency
        if offline is not None:
            self.offline = offline
        else:
            self.offline = not bool(
                api_key
                or api_keys
                or config.GEMINI_API_KEY
                or config.GEMINI_API_KEYS
                or use_local_llm
            )
        self.gemini = GeminiIntelligenceAgent(
            api_key=api_key,
            api_keys=api_keys,
            model_name=model_name,
            enable_search_grounding=enable_grounding,
            rate_limit_rpm=rate_limit_rpm,
            use_local_llm=use_local_llm,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
        )

    async def process_single_company(
        self,
        company_seed: dict[str, Any],
        http_client: httpx.AsyncClient,
    ) -> bool:
        """Process one company through scraping, intelligence analysis, and SQLite save."""
        name = company_seed["name"]
        logger.info("Starting processing for [%s]", name)

        try:
            await self.db.mark_in_progress(name)
            await self.db.log_step(
                name, "SCRAPE", "START", "Initiating multi-layer scrape"
            )

            # 1. Multi-layer scrape
            scraped_data = await self.scraper.scrape_company(
                company_seed, client=http_client
            )
            await self.db.log_step(
                name,
                "SCRAPE",
                "SUCCESS",
                f"Scraped {len(scraped_data.homepage_text)} chars home, {len(scraped_data.careers_page_text)} chars careers",
            )

            # 2. Intelligence extraction (offline heuristic check for dead sites or offline mode)
            from src.heuristic_extractor import build_offline_profile, is_site_unreachable

            if self.offline or (is_site_unreachable(scraped_data) and not self.enable_grounding):
                mode_desc = (
                    "Offline deterministic ingestion (0 Gemini calls)"
                    if self.offline
                    else "Site unreachable; local heuristic profile"
                )
                logger.info("[%s] %s", name, mode_desc)
                await self.db.log_step(
                    name,
                    "OFFLINE_EXTRACTION",
                    "SUCCESS",
                    mode_desc,
                )
                intel = build_offline_profile(name, scraped_data, seed=company_seed)
            else:
                await self.db.log_step(
                    name, "GEMINI", "START", f"Calling Gemini ({self.gemini.model_name})"
                )
                intel = await self.gemini.analyze_company(
                    scraped_data, force_grounding=self.enable_grounding
                )
                await self.db.log_step(
                    name,
                    "GEMINI",
                    "SUCCESS",
                    f"Extracted {len(intel.active_openings)} openings, domain: {intel.core_domain}",
                )

            # 3. Checkpoint commit
            await self.db.save_company_intelligence(name, intel, seed=company_seed)
            logger.info(
                "Successfully processed and saved [%s] -> %d openings",
                name,
                len(intel.active_openings),
            )
            return True

        except Exception as exc:
            error_msg = f"Error processing {name}: {exc}"
            logger.error(error_msg, exc_info=True)
            await self.db.mark_company_failed(name, str(exc))
            return False

    async def _process_company_batch(
        self,
        batch_seeds: list[dict[str, Any]],
        http_client: httpx.AsyncClient,
    ) -> list[bool]:
        """Scrape and evaluate a batch of companies together using bundled LLM extraction."""
        for seed in batch_seeds:
            cname = seed["name"]
            await self.db.mark_in_progress(cname)
            await self.db.log_step(cname, "SCRAPE", "START", "Scraping in batch mode")

        # 1. Concurrently scrape all companies in this batch
        scrape_tasks = [
            self.scraper.scrape_company(seed, client=http_client)
            for seed in batch_seeds
        ]
        scraped_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)

        batch_pairs: list[tuple[dict[str, Any], ScrapedData]] = []
        for i, seed in enumerate(batch_seeds):
            cname = seed["name"]
            res = scraped_results[i]
            if isinstance(res, Exception):
                logger.warning("Scrape error for %s: %s", cname, res)
                sdata = ScrapedData(
                    company_name=cname,
                    homepage_text=f"Failed to fetch {seed.get('website')}: {res}",
                    careers_page_text="",
                    careers_fetch_failed=True,
                )
            else:
                sdata = res
            await self.db.log_step(
                cname,
                "SCRAPE",
                "SUCCESS",
                f"Scraped {len(sdata.homepage_text)} chars home, {len(sdata.careers_page_text)} chars careers",
            )
            batch_pairs.append((seed, sdata))

        # 2. Extract intelligence in batch
        from src.heuristic_extractor import build_offline_profile

        if self.offline:
            analyzed_pairs = []
            for seed, sdata in batch_pairs:
                cname = seed["name"]
                await self.db.log_step(
                    cname,
                    "OFFLINE_EXTRACTION",
                    "SUCCESS",
                    "Offline deterministic ingestion (0 Gemini calls)",
                )
                intel = build_offline_profile(cname, sdata, seed=seed)
                analyzed_pairs.append((cname, intel))
        else:
            for seed in batch_seeds:
                await self.db.log_step(
                    seed["name"], "GEMINI", "START", f"Bundled extraction via {self.gemini.model_name}"
                )

            analyzed_pairs = await self.gemini.analyze_batch(
                batch_pairs, force_grounding=self.enable_grounding
            )

        # 3. Checkpoint commit for each company
        results: list[bool] = []
        analyzed_dict = {name: intel for name, intel in analyzed_pairs}

        for seed in batch_seeds:
            cname = seed["name"]
            intel = analyzed_dict.get(cname)
            if intel:
                try:
                    await self.db.save_company_intelligence(cname, intel, seed=seed)
                    step_type = "OFFLINE_EXTRACTION" if self.offline else "GEMINI"
                    await self.db.log_step(
                        cname,
                        step_type,
                        "SUCCESS",
                        f"Extracted {len(intel.active_openings)} openings, domain: {intel.core_domain}",
                    )
                    logger.info("Batch saved [%s] -> %d openings", cname, len(intel.active_openings))
                    results.append(True)
                except Exception as exc:
                    logger.error("Failed to save intelligence for %s: %s", cname, exc)
                    await self.db.mark_company_failed(cname, str(exc))
                    results.append(False)
            else:
                await self.db.mark_company_failed(cname, "No intelligence extracted in batch")
                results.append(False)

        return results

    async def run(
        self,
        limit: int | None = None,
        target_company: str | None = None,
        batch_size: int | None = None,
        stale_hours: float | None = 6.0,
    ) -> None:
        """Run pipeline across queued companies with controlled concurrency or batching."""
        effective_batch_size = (
            batch_size if batch_size is not None else self.batch_size
        )

        if target_company:
            pending = [
                c
                for c in await self.db.get_all_companies()
                if c["company_name"].lower() == target_company.lower()
            ]
            if not pending:
                logger.error(
                    "Target company '%s' not found in database.", target_company
                )
                return
            company_list = [
                {
                    "name": c["company_name"],
                    "website": c["website_url"],
                    "careers": c["careers_url"],
                    "rss": c["rss_url"],
                }
                for c in pending
            ]
        else:
            if stale_hours is not None:
                company_list = await self.db.get_stale_companies(
                    stale_hours=stale_hours, limit=limit
                )
            else:
                company_list = await self.db.get_pending_companies(limit=limit)

        total_pending = len(company_list)
        if total_pending == 0:
            logger.info("No pending or stale companies to process! All runs up to date.")
            return

        logger.info(
            "Found %d pending/stale companies to process (Batch size: %d, Concurrency: %d, Grounding: %s, Offline: %s)",
            total_pending,
            effective_batch_size,
            self.concurrency,
            self.enable_grounding,
            self.offline,
        )

        headers = config.get_browser_headers()
        semaphore = asyncio.Semaphore(self.concurrency)

        async with httpx.AsyncClient(
            headers=headers, verify=False, timeout=config.HTTP_TIMEOUT_SECONDS
        ) as http_client:

            if effective_batch_size > 1:
                # Batch evaluation mode
                chunked_batches = [
                    company_list[i : i + effective_batch_size]
                    for i in range(0, total_pending, effective_batch_size)
                ]
                results = []
                for chunk in chunked_batches:
                    chunk_res = await self._process_company_batch(chunk, http_client)
                    results.extend(chunk_res)
            else:
                # Single-company mode
                async def sem_worker(comp: dict[str, Any]) -> bool:
                    async with semaphore:
                        return await self.process_single_company(comp, http_client)

                tasks = [sem_worker(company) for company in company_list]
                results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for r in results if r is True)
        fail_count = total_pending - success_count
        logger.info(
            "Execution finished. Succeeded: %d, Failed: %d",
            success_count,
            fail_count,
        )



async def main_async(args: argparse.Namespace) -> None:
    """Async main routine."""
    config.ensure_directories()

    db_path = Path(args.db_path) if args.db_path else config.DB_PATH
    seed_path = Path(args.seed_file) if args.seed_file else config.SEED_FILE_PATH

    db = DatabaseManager(db_path=db_path)
    await db.init_db()

    # Interactive Q&A Mode
    if getattr(args, "interactive", False) or getattr(args, "chat", False):
        await run_interactive_cli(
            db_path=db_path,
            api_key=getattr(args, "api_key", None),
            api_keys=getattr(args, "api_keys", None),
            model_name=getattr(args, "model", None),
        )
        return

    # Single Question Q&A Mode
    if getattr(args, "query", None):
        await run_single_query(
            query=args.query,
            db=db,
            api_key=getattr(args, "api_key", None),
            api_keys=getattr(args, "api_keys", None),
            model_name=getattr(args, "model", None),
        )
        return

    # URL Verification Mode
    if getattr(args, "verify_links", False) or getattr(args, "verify_urls", False):
        from src.url_verifier import (
            apply_corrections_to_seed,
            export_reports,
            sync_database_with_reports,
            verify_all_companies,
        )

        if not seed_path.exists():
            logger.error("Seed file %s not found.", seed_path)
            return

        with open(seed_path, "r", encoding="utf-8") as f:
            seeds = json.load(f)

        if args.limit:
            seeds = seeds[: args.limit]

        logger.info("Starting automated URL health verification on %d companies...", len(seeds))
        reports, summary = await verify_all_companies(
            seeds,
            concurrency=args.concurrency or 15,
            timeout=10.0,
            probe_careers=True,
        )

        json_path = config.EXPORTS_DIR / "url_health_report.json"
        md_path = config.EXPORTS_DIR / "url_health_report.md"
        export_reports(reports, summary, json_path=json_path, md_path=md_path)

        if getattr(args, "apply_urls", False):
            applied = apply_corrections_to_seed(seeds, reports, seed_path=seed_path, backup=True)
            logger.info("Applied URL corrections to %d companies in seed file.", applied)

        if getattr(args, "update_db", False) or getattr(args, "verify_links", False):
            synced = await sync_database_with_reports(db, reports)
            logger.info("Synced URL health status for %d companies in SQLite database.", synced)

        logger.info("URL health audit finished. Report saved to %s", md_path)
        if getattr(args, "verify_only", False):
            return

    # Reset failed/in-progress runs if requested
    if getattr(args, "reset_failed", False):
        reset_count = await db.reset_failed(include_in_progress=True)
        logger.info("Reset %d failed/stuck runs back to PENDING.", reset_count)
        return

    if getattr(args, "retry_failed", False):
        reset_count = await db.reset_failed(include_in_progress=True)
        logger.info("Reset %d failed/stuck runs back to PENDING for re-processing.", reset_count)

    # Load and seed companies
    if seed_path.exists():
        logger.info("Loading company seed list from %s", seed_path)
        with open(seed_path, "r", encoding="utf-8") as f:
            seeds = json.load(f)
        seeded = await db.seed_companies(seeds, reset=args.reset)
        if args.reset:
            logger.info(
                "Reset database: %d companies re-initialized to PENDING", seeded
            )
        else:
            logger.info("Database checked: %d new companies added to queue", seeded)
    else:
        logger.warning(
            "Seed file %s not found. Proceeding with existing database records.",
            seed_path,
        )

    # Export only mode
    if args.export_only:
        logger.info("Export-only mode requested.")
        md_file = await db.export_markdown_digest()
        json_file = await db.export_json_digest()
        stats = await db.get_stats()
        print("\n" + "=" * 65)
        print("GOA CAREER INTELLIGENCE PIPELINE - EXPORT COMPLETE")
        print("=" * 65)
        print(f"Total Companies Monitored : {stats['total_companies']}")
        print(f"Completed Scrapes         : {stats['completed']}")
        print(f"Pending Scrapes           : {stats['pending']}")
        print(f"Failed Scrapes            : {stats['failed']}")
        print(f"Total Active Openings     : {stats['total_openings']}")
        print(f"CE Relevant Openings      : {stats['ce_relevant_openings']}")
        print(f"Markdown Digest Export    : {md_file}")
        print(f"JSON Digest Export        : {json_file}")
        print("=" * 65 + "\n")
        return

    # Check for GEMINI_API_KEY
    # Check for GEMINI credentials or local LLM
    has_gemini = bool(
        getattr(args, "api_key", None)
        or getattr(args, "api_keys", None)
        or config.GEMINI_API_KEY
        or config.GEMINI_API_KEYS
    )
    using_local = getattr(args, "local_llm", False) or config.USE_LOCAL_LLM
    offline_mode = getattr(args, "offline", True)
    if not offline_mode and not has_gemini and not using_local:
        logger.warning(
            "Online mode requested but GEMINI_API_KEY / GEMINI_API_KEYS is not set and --local-llm is not enabled. "
            "Falling back to offline deterministic ingestion."
        )
        offline_mode = True

    # Initialize and execute pipeline
    orchestrator = PipelineOrchestrator(
        db_manager=db,
        concurrency=args.concurrency or config.MAX_CONCURRENT_SCRAPES,
        api_key=getattr(args, "api_key", None),
        api_keys=getattr(args, "api_keys", None),
        model_name=getattr(args, "model", None),
        enable_grounding=getattr(args, "grounding", config.ENABLE_SEARCH_GROUNDING),
        batch_size=getattr(args, "batch_size", config.BATCH_SIZE),
        use_local_llm=using_local,
        rate_limit_rpm=getattr(args, "rate_limit", config.RATE_LIMIT_RPM),
        ollama_base_url=getattr(args, "ollama_url", config.OLLAMA_BASE_URL),
        ollama_model=getattr(args, "ollama_model", config.OLLAMA_MODEL),
        offline=offline_mode,
    )

    stale_hours = getattr(args, "stale_hours", 6.0)
    loop_active = getattr(args, "loop", False)

    while True:
        await orchestrator.run(
            limit=args.limit,
            target_company=args.company,
            batch_size=getattr(args, "batch_size", config.BATCH_SIZE),
            stale_hours=stale_hours,
        )

        # Generate fresh exports
        md_file = await db.export_markdown_digest()
        json_file = await db.export_json_digest()
        stats = await db.get_stats()

        print("\n" + "=" * 65)
        print("PIPELINE RUN SUMMARY")
        print("=" * 65)
        print(f"Monitored Companies       : {stats['total_companies']}")
        print(f"Completed Analysis        : {stats['completed']}")
        print(f"Pending in Queue          : {stats['pending']}")
        print(f"Failed Runs               : {stats['failed']}")
        print(f"Actively Hiring Companies : {stats['actively_hiring_companies']}")
        print(f"Total Active Roles        : {stats['total_openings']}")
        print(f"Total Historical Roles    : {stats.get('total_historical_openings', stats['total_openings'])}")
        print(f"Computer Eng Relevant     : {stats['ce_relevant_openings']}")
        print(f"Markdown Report           : {md_file}")
        print(f"JSON Report               : {json_file}")
        print("=" * 65 + "\n")

        if not loop_active:
            break

        sleep_seconds = (
            args.loop_interval
            if getattr(args, "loop_interval", None) is not None
            else (stale_hours * 3600)
        )
        logger.info(
            "Loop mode active: sleeping for %.1f seconds before next scrape cycle...",
            sleep_seconds,
        )
        try:
            await asyncio.sleep(sleep_seconds)
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("Loop interrupted. Shutting down gracefully.")
            break


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Goa Tech & Engineering Career Intelligence Pipeline (goa-job-intel)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of companies to scrape in this run",
    )
    parser.add_argument(
        "--company",
        type=str,
        default=None,
        help="Process a specific company by name (e.g. --company 'Spintly')",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Max concurrent scrapes (default: 10)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=config.BATCH_SIZE,
        help="Batch size for bundled LLM evaluation (default: 5, collapses requests)",
    )
    parser.add_argument(
        "--grounding",
        "--enable-grounding",
        dest="grounding",
        action="store_true",
        default=config.ENABLE_SEARCH_GROUNDING,
        help="Enable live Google Search Grounding (opt-in, default: False)",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=config.RATE_LIMIT_RPM,
        help="Max LLM requests per minute (default: 12.0 to stay within 15 RPM)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset all companies back to PENDING status and reseed",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Reset FAILED and stuck IN_PROGRESS companies to PENDING and process them",
    )
    parser.add_argument(
        "--reset-failed",
        action="store_true",
        help="Reset FAILED and stuck IN_PROGRESS companies to PENDING without running",
    )
    parser.add_argument(
        "--offline",
        dest="offline",
        action="store_true",
        default=True,
        help="Use deterministic offline heuristic extraction (0 Gemini calls, default: True)",
    )
    parser.add_argument(
        "--online",
        dest="offline",
        action="store_false",
        help="Enable online Gemini LLM extraction (requires GEMINI_API_KEY)",
    )
    parser.add_argument(
        "--stale-hours",
        type=float,
        default=6.0,
        help="Cadence window in hours to consider a company scrape stale (default: 6.0)",
    )
    parser.add_argument(
        "--loop",
        "--daemon",
        dest="loop",
        action="store_true",
        help="Run continuously in a background loop based on --stale-hours cadence",
    )
    parser.add_argument(
        "--loop-interval",
        type=float,
        default=None,
        help="Interval between loop cycles in seconds (default: stale-hours * 3600)",
    )
    parser.add_argument(
        "--verify-links",
        "--verify-urls",
        dest="verify_links",
        action="store_true",
        help="Run automated URL health verification across all companies in the seed list",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Run URL health verification audit and exit immediately without scraping",
    )
    parser.add_argument(
        "--apply-urls",
        action="store_true",
        help="When running --verify-urls, apply canonical fixes to the seed JSON file",
    )
    parser.add_argument(
        "--update-db",
        action="store_true",
        help="Update the SQLite database with verified canonical URLs and dead flags",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Generate Markdown and JSON digest reports without scraping",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--seed-file",
        type=str,
        default=None,
        help="Path to companies seed JSON file",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Launch the interactive terminal Q&A interface grounded in SQLite",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Alias for --interactive",
    )
    parser.add_argument(
        "--ask",
        "--query",
        "-q",
        type=str,
        default=None,
        dest="query",
        help="Ask a single question directly in the command line grounded in the database and exit",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=f"Gemini model override (default: {config.GEMINI_MODEL})",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Gemini API Key override",
    )
    parser.add_argument(
        "--api-keys",
        type=str,
        default=None,
        help="Comma-separated Gemini API Keys for multi-key rotation",
    )
    parser.add_argument(
        "--local-llm",
        "--ollama",
        dest="local_llm",
        action="store_true",
        default=config.USE_LOCAL_LLM,
        help="Use local Ollama LLM for 100%% offline free extraction",
    )

    parser.add_argument(
        "--ollama-model",
        type=str,
        default=config.OLLAMA_MODEL,
        help=f"Local Ollama model name (default: {config.OLLAMA_MODEL})",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default=config.OLLAMA_BASE_URL,
        help=f"Local Ollama base URL (default: {config.OLLAMA_BASE_URL})",
    )
    parsed = parser.parse_args()
    parsed.verify_urls = parsed.verify_links
    return parsed


def main() -> None:
    """CLI Entry point."""
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
