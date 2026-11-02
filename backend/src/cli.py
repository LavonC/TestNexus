"""
Interactive CLI interface for querying Goa Tech Career Intelligence.
Enables asking direct questions to the Gemini model grounded in the SQLite database.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import config
from src.database import DatabaseManager
from src.gemini_agent import DatabaseQAAgent

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def print_banner(stats: dict[str, Any], model_name: str, db_path: Path) -> None:
    """Print welcome banner with database overview."""
    try:
        term_width = min(80, os.get_terminal_size().columns)
    except (OSError, ValueError):
        term_width = 80
    divider = "=" * term_width
    subdivider = "-" * term_width

    print("\n" + divider)
    print(" [GoaIT] GOA TECH & ENGINEERING CAREER INTELLIGENCE - TERMINAL Q&A")
    print(divider)
    print(f" Grounded in SQLite Database : {db_path.name} ({stats.get('total_companies', 0)} companies)")
    print(f" Monitored Companies         : {stats.get('total_companies', 0)} ({stats.get('completed', 0)} analyzed, {stats.get('pending', 0)} pending)")
    print(f" Active Discrete Openings    : {stats.get('total_openings', 0)} ({stats.get('ce_relevant_openings', 0)} Computer Eng relevant)")
    print(f" Actively Hiring Companies   : {stats.get('actively_hiring_companies', 0)}")
    print(f" Powered by Gemini Model     : {model_name}")
    print(subdivider)
    print(" Ask any question directly, or type 'help' for examples and built-in commands.")
    print(" Type 'exit' or 'quit' to leave.")
    print(divider + "\n")


def print_help() -> None:
    """Print help information and sample queries."""
    print("\n" + "=" * 65)
    print("GOA CAREER INTEL - COMMAND & QUERY GUIDE")
    print("=" * 65)
    print("Built-in Local Commands:")
    print("  help              Show this guide")
    print("  stats             Display database metrics and pipeline status")
    print("  companies [query] Search & list companies in the local database")
    print("  jobs [query]      Search & list active job openings in the database")
    print("  company <name>    View full profile and openings for a company")
    print("  reset             Clear conversation history and start fresh")
    print("  clear             Clear the terminal screen")
    print("  exit / quit / q   Exit the interactive interface")
    print("\nSample Questions to Ask the Gemini Model:")
    print("  * 'Which companies have offices in Verna or Panaji?'")
    print("  * 'What companies are working on IoT, SaaS, or Embedded Systems?'")
    print("  * 'Are there any openings for Python or C++ developers?'")
    print("  * 'Show me entry-level or fresher roles for Computer Engineers'")
    print("  * 'What does Spintly do, what is their stack, and are they hiring?'")
    print("  * 'Which companies are currently actively hiring in Goa?'")
    print("  * 'Who can I email my resume to for IT companies in Goa?'")
    print("=" * 65 + "\n")


async def handle_local_commands(
    user_input: str,
    db: DatabaseManager,
    qa_agent: DatabaseQAAgent,
) -> bool:
    """
    Handle built-in offline commands locally without calling Gemini.
    Returns True if a command was handled, False if it should be sent to Gemini.
    """
    cmd = user_input.strip()
    cmd_lower = cmd.lower()

    if cmd_lower in ("help", "?", "/help"):
        print_help()
        return True

    if cmd_lower in ("stats", "status", "/stats"):
        stats = await db.get_stats()
        print("\n" + "-" * 45)
        print("[STATS] CURRENT DATABASE METRICS")
        print("-" * 45)
        print(f"Total Companies Monitored : {stats.get('total_companies', 0)}")
        print(f"Completed Intelligence    : {stats.get('completed', 0)}")
        print(f"Pending Scrapes           : {stats.get('pending', 0)}")
        print(f"Failed Scrapes            : {stats.get('failed', 0)}")
        print(f"Actively Hiring Companies : {stats.get('actively_hiring_companies', 0)}")
        print(f"Total Job Openings        : {stats.get('total_openings', 0)}")
        print(f"Computer Eng Relevant     : {stats.get('ce_relevant_openings', 0)}")
        print("-" * 45 + "\n")
        return True

    if cmd_lower.startswith("companies") or cmd_lower.startswith("/companies"):
        parts = cmd.split(maxsplit=1)
        q = parts[1].strip() if len(parts) > 1 else ""
        results = await db.search_companies(query=q, limit=20)
        print(f"\n[COMPANIES] Found ({len(results)} shown):")
        if not results:
            print(f"  No companies found matching '{q}'.\n" if q else "  No companies found in database.\n")
        else:
            for c in results:
                locs = ", ".join(c.get("goa_locations") or []) or "Goa"
                jobs_count = c.get("opening_count", 0)
                status_tag = f"[{c.get('status', 'PENDING')}]"
                hiring_tag = f"({c.get('hiring_status', 'Unknown')})" if c.get("hiring_status") else ""
                print(f"  * {c['company_name']} {status_tag} {hiring_tag} - {locs} | Jobs: {jobs_count}")
                if c.get("core_domain"):
                    print(f"    Domain: {c['core_domain']}")
            print()
        return True

    if cmd_lower.startswith("jobs") or cmd_lower.startswith("/jobs"):
        parts = cmd.split(maxsplit=2)
        include_hist = False
        q = ""
        if len(parts) > 1 and parts[1].lower() in ("--all", "-a", "--historical", "-h"):
            include_hist = True
            q = parts[2].strip() if len(parts) > 2 else ""
        else:
            q = cmd.split(maxsplit=1)[1].strip() if len(cmd.split(maxsplit=1)) > 1 else ""

        results = await db.search_job_openings(
            query=q, limit=21, active_only=not include_hist, include_historical=include_hist
        )
        label = "Historical & Active" if include_hist else "Active"
        has_more = len(results) > 20
        shown_jobs = results[:20]
        if has_more:
            print(f"\n[JOBS] {label} Openings (top 20 shown; additional matches exist in database):")
        else:
            print(f"\n[JOBS] {label} Openings ({len(shown_jobs)} shown):")

        if not shown_jobs:
            print(f"  No job openings found matching '{q}'.\n" if q else "  No job openings found in database.\n")
        else:
            for j in shown_jobs:
                stack = ", ".join(j.get("tech_stack") or []) or "General"
                status_str = "[ACTIVE]" if j.get("is_active", 1) else f"[CLOSED on {str(j.get('closed_at') or 'Past')[:10]}]"
                print(f"  * {status_str} {j['company_name']}: {j['title']} ({j.get('experience_level', 'N/A')})")
                print(f"    Tech: {stack} | Apply: {j.get('apply_url') or j.get('careers_email') or 'Careers Page'}")
            if has_more:
                print("  --> Tip: Filter by specific skill (e.g. 'jobs Python') or company to narrow results.")
            print()
        return True

    if cmd_lower in ("company", "/company") or cmd_lower.startswith("company ") or cmd_lower.startswith("/company "):
        parts = cmd.split(maxsplit=1)
        name = parts[1].strip() if len(parts) > 1 else ""
        if not name:
            print("\nUsage: company <name> (e.g. 'company Spintly')\n")
            return True
        comp = await db.get_company_profile(name)
        if not comp:
            print(f"\n[!] Company '{name}' not found in database.\n")
            return True
        print("\n" + "=" * 60)
        print(f"[COMPANY] {comp['company_name']} [{comp.get('status', 'PENDING')}]")
        print("=" * 60)
        print(f"Domain         : {comp.get('core_domain', 'Not specified')}")
        print(f"Hiring Status  : {comp.get('hiring_status', 'Unknown')}")
        locs = ", ".join(comp.get("goa_locations") or []) or "Goa"
        print(f"Goa Locations  : {locs}")
        tech = ", ".join(comp.get("tech_stack") or []) or "Not specified"
        print(f"Tech Stack     : {tech}")
        print(f"Website        : {comp.get('website_url', 'N/A')}")
        print(f"Careers Page   : {comp.get('careers_url', 'N/A')}")
        print(f"Contact Email  : {comp.get('careers_email', 'N/A')}")
        if comp.get("summary_explanation"):
            print(f"Overview       : {comp['summary_explanation']}")
        openings = comp.get("active_openings", [])
        print(f"\nActive Openings ({len(openings)}):")
        if not openings:
            print("  None listed in database.")
        for o in openings:
            ostack = ", ".join(o.get("tech_stack") or [])
            print(f"  * {o['title']} ({o.get('experience_level', 'Unknown')}) - Stack: {ostack}")
        print("=" * 60 + "\n")
        return True

    if cmd_lower in ("reset", "clear-history", "/reset"):
        qa_agent.reset_chat()
        print("\n[OK] Conversation history cleared. Started fresh chat session.\n")
        return True

    if cmd_lower in ("clear", "cls", "/clear"):
        os.system("cls" if os.name == "nt" else "clear")
        return True

    return False


async def run_single_query(
    query: str,
    db: DatabaseManager,
    api_key: str | None = None,
    api_keys: list[str] | str | None = None,
    model_name: str | None = None,
) -> None:
    """Execute a single question against the database Q&A agent and print the answer."""
    qa_agent = DatabaseQAAgent(
        db_manager=db,
        api_key=api_key or config.GEMINI_API_KEY,
        api_keys=api_keys or config.GEMINI_API_KEYS,
        model_name=model_name or config.GEMINI_MODEL,
    )

    # Check for local offline commands first (e.g. 'stats', 'companies', 'jobs', 'company <name>')
    handled = await handle_local_commands(query, db, qa_agent)
    if handled:
        return

    print(f"\n[?] Question: {query}\n")
    print(f"[*] Consulting database & Gemini [{qa_agent.model_name}]...")
    response = await qa_agent.ask(query)
    print("\n" + "=" * 65)
    print(f"GEMINI ANSWER (Grounded in SQLite via {qa_agent.active_model}):")
    print("=" * 65)
    print(response.strip())
    print("=" * 65 + "\n")


async def run_interactive_cli(
    db_path: Path | None = None,
    api_key: str | None = None,
    api_keys: list[str] | str | None = None,
    model_name: str | None = None,
) -> None:
    """Run the interactive command line Q&A interface."""
    resolved_db_path = db_path or config.DB_PATH
    db = DatabaseManager(db_path=resolved_db_path)
    await db.init_db()

    effective_model = model_name or config.GEMINI_MODEL
    effective_key = api_key or config.GEMINI_API_KEY

    qa_agent = DatabaseQAAgent(
        db_manager=db,
        api_key=effective_key,
        api_keys=api_keys or config.GEMINI_API_KEYS,
        model_name=effective_model,
    )

    stats = await db.get_stats()
    print_banner(stats, effective_model, resolved_db_path)

    if not effective_key:
        print("[!] NOTICE: GEMINI_API_KEY is not set.")
        print("    Built-in commands ('stats', 'companies', 'jobs', 'company <name>') work offline.")
        print("    To ask natural language questions with Gemini, configure GEMINI_API_KEY in .env or pass --api-key.\n")

    prompt_label = f"GoaIT [{effective_model}]> "

    while True:
        try:
            user_input = input(prompt_label).strip()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q", "/exit", "/quit", ":q"):
                print("\nGoodbye! Happy job hunting in Goa.\n")
                break

            # Check for local commands first
            handled = await handle_local_commands(user_input, db, qa_agent)
            if handled:
                continue

            # Query the Gemini agent grounded in database
            print(f"\n[*] Consulting database & Gemini [{qa_agent.active_model}]...")
            answer = await qa_agent.ask(user_input)
            print("\n" + answer.strip() + "\n")

        except KeyboardInterrupt:
            print("\n(Use 'exit' or Ctrl+D to quit)")
            continue
        except EOFError:
            print("\nGoodbye!\n")
            break
        except Exception as exc:
            print(f"\n[!] Error: {exc}\n")


def parse_cli_args() -> argparse.Namespace:
    """Parse command-line arguments for the CLI Q&A tool."""
    parser = argparse.ArgumentParser(
        description="Goa Tech Career Intelligence - Command Line Q&A Interface"
    )
    parser.add_argument(
        "-q",
        "--query",
        "--ask",
        type=str,
        default=None,
        help="Ask a single question directly in the command line and exit",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Launch the interactive terminal Q&A interface",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Alias for --interactive",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database file (default: data/goa_companies.db)",
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
    return parser.parse_args()


async def async_main() -> None:
    """Asynchronous entrypoint for CLI interface."""
    args = parse_cli_args()
    db_path = Path(args.db_path) if args.db_path else config.DB_PATH

    db = DatabaseManager(db_path=db_path)
    await db.init_db()

    if args.query:
        await run_single_query(
            query=args.query,
            db=db,
            api_key=args.api_key,
            api_keys=getattr(args, "api_keys", None),
            model_name=args.model,
        )
    else:
        await run_interactive_cli(
            db_path=db_path,
            api_key=args.api_key,
            api_keys=getattr(args, "api_keys", None),
            model_name=args.model,
        )


def main() -> None:
    """Main CLI entrypoint."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
