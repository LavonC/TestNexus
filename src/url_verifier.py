"""
URL Health & Verification module for Goa Tech & Engineering companies.
Asynchronously verifies DNS validity, HTTP status codes, redirects,
parked/dead domains, and probes alternative career paths.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx

from src.config import config
from src.database import DatabaseManager

logger = logging.getLogger(__name__)

# Known parked domain or domain-for-sale phrases
PARKED_DOMAIN_PHRASES = (
    "buy this domain",
    "domain is for sale",
    "is available for purchase",
    "hugedomains.com",
    "dan.com",
    "sedo.com",
    "parked free",
    "godaddy.com/domainsearch",
    "this domain has expired",
    "renew your domain",
    "domain parking",
    "under construction",
    "website is coming soon",
)

# Common careers endpoints to probe if seed careers URL 404s
CAREERS_PROBE_PATHS = (
    "/careers",
    "/careers/",
    "/career",
    "/career/",
    "/jobs",
    "/jobs/",
    "/join-us",
    "/work-with-us",
    "/about/careers",
    "/advertisements/",
    "/advertisements",
    "/recruitment/",
    "/recruitment",
    "/vacancies/",
    "/vacancies",
)


class UrlStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REDIRECTED = "REDIRECTED"
    PARKED = "PARKED"
    DEAD_DNS = "DEAD_DNS"
    DEAD_HTTP = "DEAD_HTTP"
    TIMEOUT = "TIMEOUT"
    PROTECTED_WAF = "PROTECTED_WAF"
    NOT_SPECIFIED = "NOT_SPECIFIED"
    ERROR = "ERROR"


@dataclass
class UrlCheckResult:
    url: str | None
    status: UrlStatus
    status_code: int = 0
    final_url: str | None = None
    error_message: str | None = None
    is_redirected: bool = False
    is_parked: bool = False


@dataclass
class CompanyUrlReport:
    company_name: str
    website: UrlCheckResult
    careers: UrlCheckResult
    rss: UrlCheckResult
    classification: str = "UNKNOWN"
    is_company_active: bool = False
    suggested_website: str | None = None
    suggested_careers: str | None = None
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["website"]["status"] = self.website.status.value
        data["careers"]["status"] = self.careers.status.value
        data["rss"]["status"] = self.rss.status.value
        return data


def _normalize_url(url: str | None) -> str:
    """Normalize URL by stripping whitespace, trailing slashes, and lowercasing scheme/host."""
    if not url:
        return ""
    url = url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if parsed.query:
        return f"{scheme}://{netloc}{path}?{parsed.query}"
    return f"{scheme}://{netloc}{path}"


def _is_parked_page(content: str) -> bool:
    """Check if page content indicates a parked, expired, or for-sale domain."""
    if not content:
        return False
    lower = content.lower()
    return any(phrase in lower for phrase in PARKED_DOMAIN_PHRASES)


async def check_dns(hostname: str) -> bool:
    """Check if domain resolves via DNS."""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, socket.gethostbyname, hostname)
        return True
    except (socket.gaierror, socket.herror, OSError):
        return False


async def verify_url(
    client: httpx.AsyncClient,
    url: str | None,
    timeout: float = 10.0,
    check_parked: bool = True,
) -> UrlCheckResult:
    """
    Asynchronously verify a URL's DNS, HTTP status, redirect chain, and content.
    """
    if not url or not url.strip():
        return UrlCheckResult(url=None, status=UrlStatus.NOT_SPECIFIED)

    clean_url = url.strip()
    parsed = urlparse(clean_url)
    hostname = parsed.hostname

    # 1. DNS Pre-check
    if hostname:
        dns_ok = await check_dns(hostname)
        if not dns_ok:
            return UrlCheckResult(
                url=clean_url,
                status=UrlStatus.DEAD_DNS,
                status_code=0,
                error_message=f"DNS resolution failed (getaddrinfo error for {hostname})",
            )

    # 2. HTTP Request with redirect tracking
    try:
        resp = await client.get(clean_url, follow_redirects=True, timeout=timeout)
        status_code = resp.status_code
        final_url = str(resp.url)
        content = resp.text[:10000] if check_parked else ""

        is_redirected = False
        norm_orig = _normalize_url(clean_url)
        norm_final = _normalize_url(final_url)
        if norm_orig != norm_final:
            is_redirected = True

        is_parked = check_parked and _is_parked_page(content)

        if is_parked:
            return UrlCheckResult(
                url=clean_url,
                status=UrlStatus.PARKED,
                status_code=status_code,
                final_url=final_url,
                is_redirected=is_redirected,
                is_parked=True,
                error_message="Domain appears to be parked or for sale",
            )

        if 200 <= status_code < 400:
            status = UrlStatus.REDIRECTED if is_redirected else UrlStatus.ACTIVE

            return UrlCheckResult(
                url=clean_url,
                status=status,
                status_code=status_code,
                final_url=final_url,
                is_redirected=is_redirected,
            )
        elif status_code in (401, 403):
            return UrlCheckResult(
                url=clean_url,
                status=UrlStatus.PROTECTED_WAF,
                status_code=status_code,
                final_url=final_url,
                is_redirected=is_redirected,
                error_message=f"HTTP {status_code} (Protected by WAF / Anti-Bot)",
            )
        else:
            return UrlCheckResult(
                url=clean_url,
                status=UrlStatus.DEAD_HTTP,
                status_code=status_code,
                final_url=final_url,
                error_message=f"HTTP {status_code}",
            )

    except httpx.TimeoutException:
        return UrlCheckResult(
            url=clean_url,
            status=UrlStatus.TIMEOUT,
            status_code=408,
            error_message=f"Connection timed out after {timeout}s",
        )
    except httpx.ConnectError as exc:
        err_str = str(exc)
        if "11001" in err_str or "getaddrinfo" in err_str or "Name or service not known" in err_str:
            return UrlCheckResult(
                url=clean_url,
                status=UrlStatus.DEAD_DNS,
                status_code=0,
                error_message=f"DNS resolution failed: {exc}",
            )
        return UrlCheckResult(
            url=clean_url,
            status=UrlStatus.DEAD_HTTP,
            status_code=0,
            error_message=f"Connection error: {exc}",
        )
    except Exception as exc:
        return UrlCheckResult(
            url=clean_url,
            status=UrlStatus.ERROR,
            status_code=0,
            error_message=str(exc),
        )


async def probe_careers_alternatives(
    client: httpx.AsyncClient,
    base_website_url: str,
    timeout: float = 6.0,
) -> str | None:
    """Probe standard career paths on the website to discover a working careers page."""
    norm_base = _normalize_url(base_website_url)
    if not norm_base:
        return None

    for path in CAREERS_PROBE_PATHS:
        candidate_url = urljoin(norm_base + "/", path.lstrip("/"))
        try:
            resp = await client.get(candidate_url, follow_redirects=True, timeout=timeout)
            if resp.status_code == 200 and len(resp.text.strip()) > 50:
                # Verify it didn't just redirect back to the home page root
                final_norm = _normalize_url(str(resp.url))
                if final_norm != norm_base and not _is_parked_page(resp.text[:5000]):
                    return str(resp.url)
        except Exception:
            continue
    return None


async def verify_company(
    client: httpx.AsyncClient,
    seed: dict[str, Any],
    timeout: float = 10.0,
    probe_careers: bool = True,
) -> CompanyUrlReport:
    """
    Verify all URLs for a single company seed and classify its domain health.
    """
    company_name = seed.get("name", "Unknown")
    website_url = seed.get("website")
    careers_url = seed.get("careers")
    rss_url = seed.get("rss")

    # 1. Run URL checks concurrently
    web_task = verify_url(client, website_url, timeout=timeout, check_parked=True)
    careers_task = verify_url(client, careers_url, timeout=timeout, check_parked=False)
    rss_task = verify_url(client, rss_url, timeout=timeout, check_parked=False)

    web_res, careers_res, rss_res = await asyncio.gather(
        web_task, careers_task, rss_task
    )

    details: list[str] = []
    suggested_website: str | None = None
    suggested_careers: str | None = None

    # Check website redirect suggestions
    if web_res.status in (UrlStatus.ACTIVE, UrlStatus.REDIRECTED) and web_res.final_url:
        norm_orig = _normalize_url(website_url)
        norm_final = _normalize_url(web_res.final_url)
        if norm_orig != norm_final:
            suggested_website = web_res.final_url
            details.append(f"Website redirects to canonical: {web_res.final_url}")

    # Check careers redirect or probe
    if careers_res.status in (UrlStatus.ACTIVE, UrlStatus.REDIRECTED) and careers_res.final_url:
        norm_orig_c = _normalize_url(careers_url)
        norm_final_c = _normalize_url(careers_res.final_url)
        if norm_orig_c != norm_final_c:
            suggested_careers = careers_res.final_url
            details.append(f"Careers URL redirects to: {careers_res.final_url}")
    elif (
        probe_careers
        and web_res.status in (UrlStatus.ACTIVE, UrlStatus.REDIRECTED)
        and (careers_res.status in (UrlStatus.DEAD_HTTP, UrlStatus.DEAD_DNS, UrlStatus.NOT_SPECIFIED))
    ):
        target_web = web_res.final_url or website_url or ""
        found_careers = await probe_careers_alternatives(client, target_web)
        if found_careers:
            suggested_careers = found_careers
            details.append(f"Probed alternative careers page found: {found_careers}")

    # Classification
    is_active = web_res.status in (UrlStatus.ACTIVE, UrlStatus.REDIRECTED, UrlStatus.PROTECTED_WAF)
    if web_res.status == UrlStatus.DEAD_DNS:
        classification = "DEAD_DNS"
        details.append(f"Dead domain (DNS failed): {web_res.error_message}")
    elif web_res.status == UrlStatus.PARKED:
        classification = "PARKED"
        details.append("Domain parked / for sale")
    elif web_res.status == UrlStatus.PROTECTED_WAF:
        classification = "PROTECTED_WAF"
        details.append(f"Site active but protected by WAF/anti-bot: {web_res.error_message}")
    elif web_res.status in (UrlStatus.DEAD_HTTP, UrlStatus.TIMEOUT):
        classification = "DEAD_HTTP"
        details.append(f"Website unreachable: {web_res.error_message}")
    elif is_active:
        if careers_res.status in (UrlStatus.DEAD_HTTP, UrlStatus.DEAD_DNS):
            classification = "BROKEN_CAREERS"
            details.append(f"Careers URL broken ({careers_res.error_message})")
        elif web_res.status == UrlStatus.REDIRECTED:
            classification = "REDIRECTED"
        else:
            classification = "ACTIVE"
    else:
        classification = "UNKNOWN"

    return CompanyUrlReport(
        company_name=company_name,
        website=web_res,
        careers=careers_res,
        rss=rss_res,
        classification=classification,
        is_company_active=is_active,
        suggested_website=suggested_website,
        suggested_careers=suggested_careers,
        details=details,
    )


async def verify_all_companies(
    seeds: list[dict[str, Any]],
    concurrency: int = 15,
    timeout: float = 10.0,
    probe_careers: bool = True,
    on_progress: Callable[[int, int, CompanyUrlReport], None] | None = None,
) -> tuple[list[CompanyUrlReport], dict[str, Any]]:
    """
    Verify all companies concurrently using a semaphore.
    """
    semaphore = asyncio.Semaphore(concurrency)
    headers = config.get_browser_headers()
    total = len(seeds)
    completed_count = 0

    reports: list[CompanyUrlReport] = []

    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=timeout
    ) as client:

        async def worker(seed: dict[str, Any]) -> CompanyUrlReport:
            nonlocal completed_count
            async with semaphore:
                report = await verify_company(
                    client, seed, timeout=timeout, probe_careers=probe_careers
                )
                completed_count += 1
                if on_progress:
                    on_progress(completed_count, total, report)
                return report

        tasks = [worker(seed) for seed in seeds]
        reports = await asyncio.gather(*tasks)

    # Compute summary statistics
    active_count = sum(1 for r in reports if r.is_company_active)
    redirected_count = sum(1 for r in reports if r.classification == "REDIRECTED" or r.suggested_website)
    dead_dns_count = sum(1 for r in reports if r.classification == "DEAD_DNS")
    dead_http_count = sum(1 for r in reports if r.classification == "DEAD_HTTP")
    parked_count = sum(1 for r in reports if r.classification == "PARKED")
    broken_careers_count = sum(
        1 for r in reports if r.is_company_active and r.careers.status in (UrlStatus.DEAD_HTTP, UrlStatus.DEAD_DNS)
    )
    corrected_careers_count = sum(1 for r in reports if r.suggested_careers)

    summary = {
        "total_monitored": total,
        "active_companies": active_count,
        "redirected_websites": redirected_count,
        "dead_dns_domains": dead_dns_count,
        "dead_http_domains": dead_http_count,
        "parked_domains": parked_count,
        "broken_careers_urls": broken_careers_count,
        "discovered_alternative_careers": corrected_careers_count,
    }

    return reports, summary


def export_reports(
    reports: list[CompanyUrlReport],
    summary: dict[str, Any],
    json_path: Path,
    md_path: Path,
) -> None:
    """Export URL health report to JSON and Markdown format."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Export JSON
    payload = {
        "summary": summary,
        "companies": [r.to_dict() for r in reports],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    # 2. Export Markdown
    lines = [
        "# Goa Tech Companies - URL & Domain Health Audit Report",
        "",
        "## Summary Metrics",
        f"- **Total Monitored Companies**: {summary['total_monitored']}",
        f"- **Active Reachable Domains**: {summary['active_companies']}",
        f"- **Redirected / Canonicalized Domains**: {summary['redirected_websites']}",
        f"- **Dead Domains (DNS Resolution Failure)**: {summary['dead_dns_domains']}",
        f"- **Unreachable Domains (HTTP/Timeout Failure)**: {summary['dead_http_domains']}",
        f"- **Parked / For Sale Domains**: {summary['parked_domains']}",
        f"- **Active Companies with Broken Careers URLs**: {summary['broken_careers_urls']}",
        f"- **Discovered Alternative Careers Pages**: {summary['discovered_alternative_careers']}",
        "",
        "---",
        "",
        "## Detailed Domain Classification",
        "",
        "| Company Name | Status | Website URL | Careers URL | Suggested Fix |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in sorted(reports, key=lambda x: (x.classification, x.company_name)):
        fix = []
        if r.suggested_website:
            fix.append(f"Web: {r.suggested_website}")
        if r.suggested_careers:
            fix.append(f"Careers: {r.suggested_careers}")
        fix_str = "<br>".join(fix) if fix else "—"
        web_str = r.website.url or "None"
        car_str = r.careers.url or "None"

        lines.append(
            f"| **{r.company_name}** | `{r.classification}` | [{web_str}]({web_str}) | [{car_str}]({car_str}) | {fix_str} |"
        )

    lines.append("")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def apply_corrections_to_seed(
    seeds: list[dict[str, Any]],
    reports: list[CompanyUrlReport],
    seed_path: Path,
    backup: bool = True,
) -> int:
    """
    Update company seeds with verified canonical and discovered careers URLs.
    Always reads the full master seed list from seed_path if it exists to ensure
    partial or limited runs (--limit N) never truncate or delete the remaining companies.
    Creates a .bak backup file if backup is True.
    """
    report_map = {r.company_name.strip().lower(): r for r in reports}
    updated_count = 0

    # Ensure we preserve all companies in seed_path even if a limited subset was verified
    if seed_path.exists():
        try:
            with open(seed_path, "r", encoding="utf-8") as f:
                master_seeds = json.load(f)
        except Exception:
            master_seeds = list(seeds)
    else:
        master_seeds = list(seeds)

    new_seeds = []
    for item in master_seeds:
        name_key = (item.get("name") or "").strip().lower()
        rep = report_map.get(name_key)
        new_item = dict(item)

        if rep:
            changed = False
            if rep.suggested_website and rep.suggested_website != item.get("website"):
                new_item["website"] = rep.suggested_website
                changed = True
            if rep.suggested_careers and rep.suggested_careers != item.get("careers"):
                new_item["careers"] = rep.suggested_careers
                changed = True

            if changed:
                updated_count += 1
        new_seeds.append(new_item)

    if backup and seed_path.exists():
        backup_path = seed_path.with_suffix(".json.bak")
        with open(backup_path, "w", encoding="utf-8") as bf:
            json.dump(master_seeds, bf, indent=2)
        logger.info("Saved seed backup to %s", backup_path)

    with open(seed_path, "w", encoding="utf-8") as f:
        json.dump(new_seeds, f, indent=2)

    logger.info("Updated %d companies in %s (total in file: %d)", updated_count, seed_path, len(new_seeds))
    return updated_count


async def sync_database_with_reports(
    db: DatabaseManager,
    reports: list[CompanyUrlReport],
) -> int:
    """
    Sync URL health findings to SQLite database:
    - Update canonical website and careers URLs.
    - Mark confirmed DEAD_DNS / PARKED domains as FAILED and set is_dead=1 (without overriding COMPLETED).
    - Mark active domains with is_dead=0.
    """
    updates_list: list[dict[str, Any]] = []
    for r in reports:
        web_fix = r.suggested_website
        car_fix = r.suggested_careers

        # Mark dead domains in database with informative error message and is_dead=1
        if not r.is_company_active:
            err = "; ".join(r.details) or f"Domain is {r.classification}"
            is_dead_val = 1 if r.classification in ("DEAD_DNS", "PARKED") else 0
            new_status = "FAILED" if r.classification in ("DEAD_DNS", "PARKED") else None
            updates_list.append({
                "company_name": r.company_name,
                "website": web_fix,
                "careers": car_fix,
                "status": new_status,
                "error_message": err,
                "is_dead": is_dead_val,
            })
        elif web_fix or car_fix or r.is_company_active:
            updates_list.append({
                "company_name": r.company_name,
                "website": web_fix,
                "careers": car_fix,
                "is_dead": 0,
            })

    if hasattr(db, "batch_update_company_urls"):
        return await db.batch_update_company_urls(updates_list)

    # Fallback to single updates if batch not supported
    updated_count = 0
    for u in updates_list:
        await db.update_company_urls(**u)
        updated_count += 1
    return updated_count
