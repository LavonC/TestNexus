"""
goa_career_intel.py - Standalone Core Pipeline Script

Implements the 2-pass pipeline:
1. Concurrently scrapes website, career page, and RSS feed.
2. Web Search Grounding via Gemini 3.8 Flash + Google Search tool.
3. Structured Pydantic extraction into SQLite storage.
"""

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

import feedparser
import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from pydantic import BaseModel, Field


# ==========================================
# 1. PYDANTIC SCHEMAS FOR GEMINI OUTPUT
# ==========================================
class JobOpening(BaseModel):
    title: str = Field(description="Job title, e.g., Software Engineer, Embedded C++ Developer")
    experience_level: str = Field(description="e.g., Fresher/Intern, 1-3 years, Senior, Unknown")
    tech_stack: List[str] = Field(description="Skills mentioned for this role")
    is_computer_eng_relevant: bool = Field(description="True if relevant to CS/Computer Engineering")


class CompanyIntelligence(BaseModel):
    company_name: str
    goa_locations: List[str] = Field(description="Goa office areas like Verna, Panaji, Margao, Porvorim")
    core_domain: str = Field(description="What the company builds or does")
    primary_tech_stack: List[str] = Field(description="Overall technologies used by the company")
    hiring_status: Literal["Actively Hiring", "Open Applications Only", "Open Applications / Email Resume", "No Listed Openings", "Unknown"]
    careers_email: Optional[str] = Field(description="HR or careers email if found on page")
    active_openings: List[JobOpening]
    summary_explanation: str = Field(
        description="A concise 2-3 sentence explanation of what this company does in Goa and how a Computer Engineer fits in."
    )


# ==========================================
# 2. SQLITE STORAGE SETUP
# ==========================================
def init_db(db_path: str = "goa_companies.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS company_intel (
            company_name TEXT PRIMARY KEY,
            website_url TEXT,
            careers_url TEXT,
            rss_url TEXT,
            core_domain TEXT,
            hiring_status TEXT,
            careers_email TEXT,
            goa_locations TEXT,
            tech_stack TEXT,
            active_openings_json TEXT,
            summary_explanation TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()
    return conn


def save_to_db(conn: sqlite3.Connection, seed: dict, intel: CompanyIntelligence) -> None:
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO company_intel VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        intel.company_name,
        seed.get("website"),
        seed.get("careers"),
        seed.get("rss"),
        intel.core_domain,
        intel.hiring_status,
        intel.careers_email,
        json.dumps(intel.goa_locations),
        json.dumps(intel.primary_tech_stack),
        json.dumps([job.model_dump() for job in intel.active_openings]),
        intel.summary_explanation,
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()


# ==========================================
# 3. WEB & RSS SCRAPER FUNCTIONS
# ==========================================
def clean_html_to_text(html: str, max_chars: int = 12000) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "footer"]):
        tag.decompose()

    # Extract useful links (like external ATS portals or mailto:)
    links_info = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(k in href.lower() for k in ["career", "job", "keka", "zoho", "workday", "mailto:", "lever", "greenhouse"]):
            links_info.append(f"[{a.get_text(strip=True)}]({href})")

    text = soup.get_text(separator=" ", strip=True)
    combined = f"{text[:max_chars]}\n\nRelevant Links Found:\n" + "\n".join(set(links_info[:30]))
    return combined


async def fetch_url_text(client: httpx.AsyncClient, url: Optional[str]) -> str:
    if not url:
        return "Not provided."
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15.0)
        if resp.status_code == 200:
            return clean_html_to_text(resp.text)
        return f"HTTP Status {resp.status_code}"
    except Exception as e:
        return f"Scrape failed: {str(e)}"


async def fetch_rss_summary(client: httpx.AsyncClient, rss_url: Optional[str]) -> str:
    if not rss_url:
        return "No RSS feed."
    try:
        resp = await client.get(rss_url, follow_redirects=True, timeout=10.0)
        if resp.status_code != 200:
            return "RSS unreachable."
        feed = feedparser.parse(resp.text)
        entries = []
        for entry in feed.entries[:5]:
            entries.append(f"- {entry.get('title', 'No Title')} ({entry.get('published', 'Unknown Date')})")
        return "\n".join(entries) if entries else "Empty RSS feed."
    except Exception as e:
        return f"RSS error: {str(e)}"


# ==========================================
# 4. GEMINI INTELLIGENCE PIPELINE (WITH TIER CASCADING & RATE LIMITING)
# ==========================================
from src.heuristic_extractor import build_offline_profile, clean_json_text, is_site_unreachable
from src.key_rotator import KeyRotator
from src.models import ScrapedData
from src.rate_limiter import AsyncRateLimiter

_RATE_LIMITER = AsyncRateLimiter(requests_per_minute=12.0)
_CASCADING_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-3.8-flash"]


async def analyze_company(
    gemini_client: genai.Client,
    http_client: httpx.AsyncClient,
    company_seed: dict,
    enable_grounding: bool = False,
    key_rotator: Optional[KeyRotator] = None,
) -> CompanyIntelligence:
    name = company_seed["name"]
    print(f"[*] Scraping {name}...")

    # 1. Scrape Website, Careers Page, and RSS concurrently
    home_text, careers_text, rss_text = await asyncio.gather(
        fetch_url_text(http_client, company_seed.get("website")),
        fetch_url_text(http_client, company_seed.get("careers")),
        fetch_rss_summary(http_client, company_seed.get("rss")),
    )

    scraped_obj = ScrapedData(
        company_name=name,
        homepage_text=home_text,
        careers_page_text=careers_text,
        rss_summary=rss_text,
    )

    # Fast offline check: if site is dead/unreachable, do not waste scarce LLM quota
    if is_site_unreachable(scraped_obj) and not enable_grounding:
        print(f"[*] Site unreachable for {name}. Using fast local heuristic profile...")
        return build_offline_profile(name, scraped_obj, seed=company_seed)

    # 2. Live Web Search Grounding (opt-in / conditional)
    web_search_notes = "Search grounding skipped."
    if enable_grounding:
        print(f"[*] Running web search grounding for {name}...")
        search_prompt = (
            f"Search the web for the company '{name}' in Goa, India. "
            f"Find what products/services they work on, their office location in Goa, "
            f"their tech stack, and any current job openings or external career portals "
            f"(like Keka, Zoho Recruit, LinkedIn) for Computer Engineers or Software Developers."
        )

        for model in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.8-flash"]:
            grounding_done = False
            max_grounding_attempts = max(2, (key_rotator.total_keys if key_rotator else 1) + 1)
            for attempt in range(max_grounding_attempts):
                try:
                    await _RATE_LIMITER.acquire()
                    search_response = await gemini_client.aio.models.generate_content(
                        model=model,
                        contents=search_prompt,
                        config=types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearch())],
                            temperature=0.2,
                        ),
                    )
                    web_search_notes = search_response.text or ""
                    grounding_done = True
                    break
                except Exception as e:
                    err_msg = str(e).lower()
                    print(f"[!] Grounding attempt on {model} failed: {e}")
                    if "429" in err_msg or "resource_exhausted" in err_msg or "quota" in err_msg:
                        await _RATE_LIMITER.backoff(delay=1.0)
                        if key_rotator and key_rotator.total_keys > 1 and key_rotator.has_available_keys(model=model):
                            k = key_rotator.get_current_key(model=model)
                            next_key = key_rotator.mark_key_exhausted(k or "", reason=f"429 on {model}", model=model)
                            if next_key:
                                gemini_client = genai.Client(api_key=next_key)
                                continue
                        break
                    if attempt == 0:
                        await asyncio.sleep(1.0)
                    else:
                        break
            if grounding_done:
                break

    # 3. Synthesize & Structure with Tier Cascading
    print(f"[*] Extracting structured intelligence for {name}...")
    extraction_prompt = f"""
    Analyze the following scraped data and live web search intelligence for the Goan company: {name}.

    --- HOMEPAGE SCRAPE ---
    {home_text}

    --- CAREERS PAGE SCRAPE ---
    {careers_text}

    --- RSS FEED POSTS ---
    {rss_text}

    --- LIVE WEB SEARCH INTELLIGENCE ---
    {web_search_notes}

    Extract accurate structured information tailored for a Computer Engineering candidate looking for roles in Goa.
    """

    for model in _CASCADING_MODELS:
        max_extract_attempts = max(2, (key_rotator.total_keys if key_rotator else 1) + 1)
        for attempt in range(max_extract_attempts):
            try:
                await _RATE_LIMITER.acquire()
                structured_response = await gemini_client.aio.models.generate_content(
                    model=model,
                    contents=extraction_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=CompanyIntelligence,
                        temperature=0.1,
                    ),
                )
                cleaned_output = clean_json_text(structured_response.text or "{}")
                return CompanyIntelligence.model_validate_json(cleaned_output)
            except Exception as e:
                err_msg = str(e).lower()
                if "429" in err_msg or "resource_exhausted" in err_msg or "quota" in err_msg:
                    await _RATE_LIMITER.backoff(delay=1.0)
                    if key_rotator and key_rotator.total_keys > 1 and key_rotator.has_available_keys(model=model):
                        k = key_rotator.get_current_key(model=model)
                        next_key = key_rotator.mark_key_exhausted(k or "", reason=f"429 on {model}", model=model)
                        if next_key:
                            gemini_client = genai.Client(api_key=next_key)
                            continue
                    print(f"[!] Quota limit on {model}; cascading to next model tier...")
                    break
                print(f"[!] Extraction on {model} failed: {e}")
                if attempt == 0:
                    await asyncio.sleep(1.0)
                else:
                    break

    print(f"[!] Falling back to local heuristic profile for {name}")
    return build_offline_profile(name, scraped_obj, seed=company_seed)



# ==========================================
# 5. MAIN EXECUTION LOOP
# ==========================================
SEED_COMPANIES = [
    {
        "name": "Spintly",
        "website": "https://spintly.com",
        "careers": "https://spintly.com/careers/",
        "rss": "https://spintly.com/feed/",
    },
    {
        "name": "Teknorix Systems",
        "website": "https://www.teknorix.com",
        "careers": "https://www.teknorix.com/careers/",
        "rss": "https://www.teknorix.com/feed/",
    },
    {
        "name": "Numino Labs",
        "website": "https://www.numinolabs.com",
        "careers": "https://www.numinolabs.com/careers/",
        "rss": "https://www.numinolabs.com/feed/",
    },
]


async def main():
    import sys
    if any(arg in sys.argv for arg in ("--ask", "--query", "-q", "--interactive", "-i", "--chat", "-h", "--help")):
        from src.cli import parse_cli_args, run_interactive_cli, run_single_query
        from src.config import config
        from src.database import DatabaseManager
        cli_args = parse_cli_args()
        db_path = Path(cli_args.db_path) if cli_args.db_path else config.DB_PATH
        if cli_args.query:
            db = DatabaseManager(db_path=db_path)
            await db.init_db()
            await run_single_query(
                query=cli_args.query,
                db=db,
                api_key=cli_args.api_key,
                model_name=cli_args.model,
            )
        else:
            await run_interactive_cli(
                db_path=db_path,
                api_key=cli_args.api_key,
                model_name=cli_args.model,
            )
        return

    seed_file = Path("data/companies_seed.json")
    if seed_file.exists():
        with open(seed_file, "r", encoding="utf-8") as f:
            companies_to_run = json.load(f)[:5]  # Run first 5 by default
    else:
        companies_to_run = SEED_COMPANIES

    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")
    api_keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
    if api_key and api_key not in api_keys:
        api_keys.insert(0, api_key)

    key_rotator = KeyRotator(api_keys) if api_keys else None
    active_key = key_rotator.get_current_key() if key_rotator else None

    if not active_key:
        print("\n[!] NOTICE: GEMINI_API_KEY / GEMINI_API_KEYS is not set.")
        print("[!] Generating offline heuristic profiles for Goan companies without external LLM calls.\n")
        gemini_client = None
    else:
        gemini_client = genai.Client(api_key=active_key)

    db_conn = init_db("goa_companies.db")

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with httpx.AsyncClient(headers=headers, verify=False) as http_client:
        for company in companies_to_run:
            try:
                if gemini_client is None:
                    home_text, careers_text, rss_text = await asyncio.gather(
                        fetch_url_text(http_client, company.get("website")),
                        fetch_url_text(http_client, company.get("careers")),
                        fetch_rss_summary(http_client, company.get("rss")),
                    )
                    scraped_obj = ScrapedData(
                        company_name=company["name"],
                        homepage_text=home_text,
                        careers_page_text=careers_text,
                        rss_summary=rss_text,
                    )
                    intel = build_offline_profile(company["name"], scraped_obj, seed=company)
                else:
                    intel = await analyze_company(
                        gemini_client,
                        http_client,
                        company,
                        enable_grounding=os.getenv("ENABLE_SEARCH_GROUNDING", "false").lower() in ("true", "1", "yes"),
                        key_rotator=key_rotator,
                    )
                save_to_db(db_conn, company, intel)

                # Print human-readable explanation
                print("\n" + "=" * 60)
                print(f"COMPANY: {intel.company_name} ({', '.join(intel.goa_locations)})")
                print(f"DOMAIN : {intel.core_domain}")
                print(f"STATUS : {intel.hiring_status} | Contact: {intel.careers_email}")
                print(f"STACK  : {', '.join(intel.primary_tech_stack)}")
                print(f"SUMMARY: {intel.summary_explanation}")
                if intel.active_openings:
                    print("OPENINGS:")
                    for job in intel.active_openings:
                        print(f"  - {job.title} ({job.experience_level}) -> Stack: {', '.join(job.tech_stack)}")
                print("=" * 60 + "\n")

            except Exception as e:
                print(f"[!] Error processing {company['name']}: {e}")

    db_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
