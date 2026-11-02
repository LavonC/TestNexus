"""
Multi-layer scraper combining httpx, BeautifulSoup, feedparser, and Playwright fallback.
Extracts clean Markdown and ATS portal links from Goan company sites.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from src.config import config
from src.models import CompanySeed, JobOpening, ScrapedData
from src.pdf_extractor import extract_text_from_pdf_bytes, parse_government_job_pdf

logger = logging.getLogger(__name__)
# Suppress fontTools noisy warnings for corrupt PDF fonts
logging.getLogger("fontTools").setLevel(logging.ERROR)

# ATS and career-related URL substrings
ATS_KEYWORDS = [
    "keka.com",
    "zohorecruit.com",
    "zoho.com",
    "workday",
    "myworkdayjobs.com",
    "lever.co",
    "greenhouse.io",
    "linkedin.com/jobs",
    "naukri.com",
    "indeed.com",
    "freshteam.com",
    "bamboohr.com",
    "smartrecruiters.com",
    "recruitee.com",
    "careers",
    "job",
    "opening",
    "advertisement",
    "vacancy",
    ".pdf",
    "mailto:",
]

# SPA markers indicating client-side rendering
SPA_MARKERS = [
    'id="root"',
    'id="app"',
    'id="__next"',
    "<app-root>",
    'id="main-app"',
    'id="react-root"',
]


def clean_html_to_markdown(
    html: str, base_url: str | None = None, max_chars: int = 15000
) -> tuple[str, list[str]]:
    """
    Clean HTML by stripping non-content tags, extract ATS/job links,
    and convert to compact Markdown.
    """
    if not html or not html.strip():
        return "", []

    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content tags
    for tag in soup(["script", "style", "nav", "svg", "noscript", "footer", "iframe"]):
        tag.decompose()

    # Extract all relevant job/career and ATS links
    found_links = set()
    for a in soup.find_all("a", href=True):
        raw_href = a["href"].strip()
        if not raw_href or raw_href.startswith(("#", "javascript:", "tel:")):
            continue

        full_url = urljoin(base_url, raw_href) if base_url else raw_href
        lower_url = full_url.lower()

        if any(keyword in lower_url for keyword in ATS_KEYWORDS):
            link_text = a.get_text(strip=True) or "Link"
            found_links.add(f"[{link_text}]({full_url})")

    # Convert cleaned body to markdown
    body = soup.body or soup
    markdown_text = md(str(body), heading_style="ATX", strip=["img"])

    # Condense consecutive blank lines
    markdown_text = re.sub(r"\n{3,}", "\n\n", markdown_text).strip()
    truncated_text = markdown_text[:max_chars]

    return truncated_text, list(found_links)


def extract_pdf_links(html: str, base_url: str | None = None) -> list[str]:
    """Extract links pointing to PDF files from HTML content, prioritized by recruitment relevance."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    scored_links: list[tuple[int, str]] = []
    seen = set()
    recruitment_keywords = (
        "advt", "advertisement", "recruitment", "vacancy", "vacancies",
        "job", "opening", "circular", "notice", "post", "career", "notification"
    )
    for a in soup.find_all("a", href=True):
        raw_href = a["href"].strip()
        if not raw_href or raw_href.startswith(("#", "javascript:", "tel:", "mailto:")):
            continue
        full_url = urljoin(base_url, raw_href) if base_url else raw_href
        lower_url = full_url.lower()
        link_text = (a.get_text() or "").lower()
        if ".pdf" in lower_url:
            if full_url not in seen:
                seen.add(full_url)
                is_recruit = any(k in lower_url or k in link_text for k in recruitment_keywords)
                scored_links.append((0 if is_recruit else 1, full_url))
    scored_links.sort(key=lambda x: x[0])
    return [url for _, url in scored_links]


async def fetch_url_static(
    client: httpx.AsyncClient,
    url: str | None,
    timeout: float = 15.0,
) -> tuple[str, list[str], int, str]:
    """
    Fetch a URL using httpx and convert to cleaned Markdown.
    Includes smart SSL & non-www fallback.
    Returns: (text, ats_links, status_code, raw_html)
    """
    if not url:
        return "No URL provided.", [], 0, ""

    urls_to_try = [url]
    # If https://www., add https:// (non-www) fallback
    if url.startswith("https://www."):
        urls_to_try.append("https://" + url[12:])
    elif url.startswith("http://www."):
        urls_to_try.append("http://" + url[11:])
    # Add http:// fallback if https fails due to SSL errors
    if url.startswith("https://"):
        urls_to_try.append("http://" + url[8:])

    last_exc = None
    for attempt_url in urls_to_try:
        try:
            response = await client.get(attempt_url, follow_redirects=True, timeout=timeout)
            status_code = response.status_code
            raw_html = response.text

            if status_code == 200:
                cleaned_text, links = clean_html_to_markdown(
                    raw_html, base_url=str(response.url)
                )
                return cleaned_text, links, status_code, raw_html
            if status_code not in (404, 403, 500, 502, 503, 521, 522):
                return (
                    f"HTTP {status_code} Error while fetching {attempt_url}",
                    [],
                    status_code,
                    raw_html,
                )
        except httpx.TimeoutException as exc:
            last_exc = exc
            continue
        except Exception as exc:
            last_exc = exc
            continue

    if isinstance(last_exc, httpx.TimeoutException):
        logger.warning("Timeout fetching %s", url)
        return f"Timeout fetching {url}", [], 408, ""
    if last_exc:
        logger.warning("Error fetching %s: %s", url, last_exc)
        return f"Failed to fetch {url}: {last_exc}", [], 500, ""
    return f"HTTP 404 Error while fetching {url}", [], 404, ""


async def fetch_rss_feed(client: httpx.AsyncClient, rss_url: str | None) -> str:
    """Fetch and parse RSS feed, extracting top 5 recent posts."""
    if not rss_url:
        return "No RSS feed specified."

    try:
        response = await client.get(
            rss_url, follow_redirects=True, timeout=config.RSS_TIMEOUT_SECONDS
        )
        if response.status_code != 200:
            return f"RSS feed returned HTTP {response.status_code}."

        feed = feedparser.parse(response.text)
        if not feed.entries:
            return "RSS feed contains no entries."

        entries = []
        for entry in feed.entries[:5]:
            title = entry.get("title", "No Title").strip()
            date = entry.get("published", entry.get("updated", "Unknown Date")).strip()
            summary = entry.get("summary", "").strip()
            # Clean summary tags if any
            clean_sum = BeautifulSoup(summary, "html.parser").get_text(
                separator=" ", strip=True
            )[:250]
            entries.append(f"- **{title}** ({date})\n  {clean_sum}")

        return "\n".join(entries)
    except Exception as exc:
        logger.warning("Error parsing RSS %s: %s", rss_url, exc)
        return f"RSS parsing error: {exc}"


class Scraper:
    """Orchestrator for multi-layer concurrent scraping."""

    def __init__(self, concurrency: int = 10):
        self.semaphore = asyncio.Semaphore(concurrency)
        self.headers = config.get_browser_headers()

    async def scrape_company(
        self,
        company: CompanySeed | dict,
        client: httpx.AsyncClient | None = None,
    ) -> ScrapedData:
        """
        Scrape homepage, career page, and RSS feed concurrently for a given company.
        Applies Playwright headless rendering if career page appears to be a JS SPA.
        """
        seed = (
            company
            if isinstance(company, CompanySeed)
            else CompanySeed.model_validate(company)
        )
        name = seed.name

        async with self.semaphore:
            logger.info("Scraping static content for %s", name)

            # Use provided client or create a temporary one
            owns_client = client is None
            http_client = client or httpx.AsyncClient(
                headers=self.headers, verify=False
            )

            try:
                # 1. Fetch homepage, careers page, and RSS concurrently
                home_task = fetch_url_static(
                    http_client, seed.website, timeout=config.HTTP_TIMEOUT_SECONDS
                )
                careers_task = fetch_url_static(
                    http_client, seed.careers, timeout=config.HTTP_TIMEOUT_SECONDS
                )
                rss_task = fetch_rss_feed(http_client, seed.rss)

                (
                    (home_text, home_links, home_status, _),
                    (careers_text, careers_links, careers_status, careers_html),
                    rss_summary,
                ) = await asyncio.gather(home_task, careers_task, rss_task)

                all_ats_links = list(set(home_links + careers_links))
                used_playwright = False
                careers_failed = careers_status not in (200, 301, 302)

                # Auto-recovery: If seed careers URL 404s/fails, check if homepage links contains an alternative career URL
                if careers_failed and home_links:
                    candidate_career_urls = []
                    for link_md in home_links:
                        m_u = re.search(r"\]\((https?://[^\s\)]+)\)", link_md)
                        if m_u:
                            u_cand = m_u.group(1)
                            u_lower = u_cand.lower()
                            if any(
                                k in u_lower
                                for k in [
                                    "career", "job", "join", "work", "vacanc",
                                    "keka", "zoho", "lever", "greenhouse", "apply"
                                ]
                            ):
                                candidate_career_urls.append(u_cand)
                    for cand_url in candidate_career_urls[:3]:
                        c_text, c_links, c_status, c_html = await fetch_url_static(
                            http_client, cand_url, timeout=config.HTTP_TIMEOUT_SECONDS
                        )
                        if c_status == 200 and len(c_text.strip()) > 50:
                            logger.info(
                                "Auto-discovered working careers URL for %s: %s",
                                name,
                                cand_url,
                            )
                            careers_text = c_text
                            careers_status = c_status
                            careers_html = c_html
                            all_ats_links = list(set(all_ats_links + c_links))
                            careers_failed = False
                            break

                # 2. Detect and parse linked recruitment PDFs (e.g. GPSC or govt / PSU advertisements)
                pdf_openings: list[JobOpening] = []
                detected_pdf_urls = extract_pdf_links(
                    careers_html, base_url=str(seed.careers or seed.website)
                )
                if detected_pdf_urls:
                    logger.info(
                        "Found %d PDF recruitment links for %s", len(detected_pdf_urls), name
                    )
                    for pdf_url in detected_pdf_urls[:3]:
                        try:
                            # Stream with size limit (max 15MB) and dedicated timeout
                            async with http_client.stream(
                                "GET", pdf_url, follow_redirects=True, timeout=12.0
                            ) as pdf_stream:
                                if pdf_stream.status_code == 200:
                                    content_len = pdf_stream.headers.get("content-length")
                                    if content_len and int(content_len) > 15 * 1024 * 1024:
                                        logger.warning("PDF %s exceeds 15MB limit, skipping.", pdf_url)
                                        continue
                                    pdf_content = await pdf_stream.aread()
                                    if len(pdf_content) > 15 * 1024 * 1024:
                                        logger.warning("PDF %s payload exceeds 15MB, skipping.", pdf_url)
                                        continue
                                    if pdf_content:
                                        pdf_text = extract_text_from_pdf_bytes(pdf_content)
                                        if pdf_text and len(pdf_text.strip()) >= 50:
                                            logger.info(
                                                "Extracted %d chars from PDF: %s",
                                                len(pdf_text),
                                                pdf_url,
                                            )
                                            careers_text += (
                                                f"\n\n### Official PDF Advertisement ({pdf_url})\n{pdf_text[:8000]}"
                                            )
                                            parsed_jobs = parse_government_job_pdf(
                                                pdf_text, pdf_url=pdf_url
                                            )
                                            if parsed_jobs:
                                                pdf_openings.extend(parsed_jobs)
                                            all_ats_links.append(f"[PDF Circular]({pdf_url})")
                                        else:
                                            logger.info(
                                                "PDF %s yielded < 50 chars (scanned PDF, OCR needed) - skipping gracefully",
                                                pdf_url,
                                            )
                        except Exception as pdf_err:
                            logger.debug(
                                "Failed to fetch/parse PDF %s: %s", pdf_url, pdf_err
                            )

                # 4. Determine if Google Search Grounding is recommended
                needs_grounding = (
                    careers_failed
                    or not seed.careers
                    or len(careers_text.strip()) < 250
                    or (not all_ats_links and "no opening" in careers_text.lower())
                )

                return ScrapedData(
                    company_name=name,
                    homepage_text=home_text,
                    careers_page_text=careers_text,
                    rss_summary=rss_summary,
                    ats_links=all_ats_links,
                    careers_fetch_failed=careers_failed,
                    used_playwright=used_playwright,
                    needs_search_grounding=needs_grounding,
                    pdf_openings=pdf_openings,
                )
            finally:
                if owns_client:
                    await http_client.aclose()
