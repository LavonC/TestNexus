"""
Unit tests for URL Health & Verification module.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.url_verifier import (
    CompanyUrlReport,
    UrlCheckResult,
    UrlStatus,
    _is_parked_page,
    _normalize_url,
    apply_corrections_to_seed,
    check_dns,
    export_reports,
    verify_company,
    verify_url,
)


def test_normalize_url():
    assert _normalize_url("https://www.example.com/") == "https://www.example.com"
    assert _normalize_url("http://example.com/careers/") == "http://example.com/careers"
    assert _normalize_url("example.com") == "https://example.com"
    assert _normalize_url("") == ""
    assert _normalize_url(None) == ""


def test_is_parked_page():
    assert _is_parked_page("Welcome! This domain is for sale. Buy it on HugeDomains.") is True
    assert _is_parked_page("Welcome to our engineering company in Verna, Goa.") is False
    assert _is_parked_page("") is False


@pytest.mark.asyncio
async def test_check_dns_mock():
    with patch("socket.gethostbyname", return_value="1.2.3.4"):
        assert await check_dns("valid-domain.com") is True

    import socket
    with patch("socket.gethostbyname", side_effect=socket.gaierror(-2, "Name or service not known")):
        assert await check_dns("invalid-dead-domain.fake") is False


@pytest.mark.asyncio
async def test_verify_url_active():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = httpx.URL("https://acme.com")
    mock_resp.text = "<html><body>Welcome to Acme Tech Goa</body></html>"
    mock_client.get.return_value = mock_resp

    with patch("src.url_verifier.check_dns", return_value=True):
        res = await verify_url(mock_client, "https://acme.com")
        assert res.status == UrlStatus.ACTIVE
        assert res.status_code == 200
        assert res.is_redirected is False


@pytest.mark.asyncio
async def test_verify_url_redirected():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = httpx.URL("https://intuio.io/")
    mock_resp.text = "<html><body>Welcome to Intuio Labs</body></html>"
    mock_client.get.return_value = mock_resp

    with patch("src.url_verifier.check_dns", return_value=True):
        res = await verify_url(mock_client, "https://www.intuio.io")
        assert res.status == UrlStatus.REDIRECTED
        assert res.is_redirected is True
        assert res.final_url == "https://intuio.io/"


@pytest.mark.asyncio
async def test_verify_url_dead_dns():
    with patch("src.url_verifier.check_dns", return_value=False):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        res = await verify_url(mock_client, "https://nonexistent-goa-tech-12345.com")
        assert res.status == UrlStatus.DEAD_DNS
        assert res.status_code == 0
        assert "DNS resolution failed" in res.error_message


@pytest.mark.asyncio
async def test_verify_url_http_404():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.url = httpx.URL("https://acme.com/careers")
    mock_resp.text = "Not Found"
    mock_client.get.return_value = mock_resp

    with patch("src.url_verifier.check_dns", return_value=True):
        res = await verify_url(mock_client, "https://acme.com/careers")
        assert res.status == UrlStatus.DEAD_HTTP
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_verify_url_timeout():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = httpx.TimeoutException("Timeout")

    with patch("src.url_verifier.check_dns", return_value=True):
        res = await verify_url(mock_client, "https://slowsite.com")
        assert res.status == UrlStatus.TIMEOUT
        assert res.status_code == 408


@pytest.mark.asyncio
async def test_verify_company_classification_and_probe():
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    # Homepage returns 200, careers returns 404
    async def mock_get(url, *args, **kwargs):
        url_str = str(url)
        mock_resp = MagicMock()
        if "acme.com/careers" in url_str:
            mock_resp.status_code = 404
            mock_resp.url = httpx.URL(url_str)
            mock_resp.text = "404 Not Found"
        elif "acme.com/jobs" in url_str:
            mock_resp.status_code = 200
            mock_resp.url = httpx.URL("https://acme.com/jobs")
            mock_resp.text = "<html><body>Join our engineering team in Goa! We are hiring.</body></html>"
        else:
            mock_resp.status_code = 200
            mock_resp.url = httpx.URL("https://acme.com")
            mock_resp.text = "<html><body>Acme Tech Goa Official Homepage</body></html>"
        return mock_resp

    mock_client.get.side_effect = mock_get

    with patch("src.url_verifier.check_dns", return_value=True):
        seed = {
            "name": "Acme Technologies",
            "website": "https://acme.com",
            "careers": "https://acme.com/careers",
            "rss": None,
        }
        report = await verify_company(mock_client, seed, probe_careers=True)

        assert report.company_name == "Acme Technologies"
        assert report.is_company_active is True
        # Probing should discover /jobs as working alternative
        assert report.suggested_careers == "https://acme.com/jobs"


def test_apply_corrections_to_seed(tmp_path):
    seed_file = tmp_path / "companies_seed.json"
    initial_seeds = [
        {"name": "Intuio", "website": "https://www.intuio.io", "careers": "https://www.intuio.io/careers", "rss": None},
        {"name": "Acme", "website": "https://acme.com", "careers": "https://acme.com/broken", "rss": None},
    ]
    with open(seed_file, "w", encoding="utf-8") as f:
        json.dump(initial_seeds, f)

    reports = [
        CompanyUrlReport(
            company_name="Intuio",
            website=UrlCheckResult(url="https://www.intuio.io", status=UrlStatus.REDIRECTED, final_url="https://intuio.io/"),
            careers=UrlCheckResult(url="https://www.intuio.io/careers", status=UrlStatus.DEAD_HTTP),
            rss=UrlCheckResult(url=None, status=UrlStatus.NOT_SPECIFIED),
            suggested_website="https://intuio.io/",
            is_company_active=True,
        ),
        CompanyUrlReport(
            company_name="Acme",
            website=UrlCheckResult(url="https://acme.com", status=UrlStatus.ACTIVE, final_url="https://acme.com"),
            careers=UrlCheckResult(url="https://acme.com/broken", status=UrlStatus.DEAD_HTTP),
            rss=UrlCheckResult(url=None, status=UrlStatus.NOT_SPECIFIED),
            suggested_careers="https://acme.com/careers-new",
            is_company_active=True,
        ),
    ]

    applied = apply_corrections_to_seed(initial_seeds, reports, seed_path=seed_file, backup=True)
    assert applied == 2

    # Check updated content
    with open(seed_file, "r", encoding="utf-8") as f:
        updated = json.load(f)

    assert updated[0]["website"] == "https://intuio.io/"
    assert updated[1]["careers"] == "https://acme.com/careers-new"

    # Check backup file created
    backup_file = seed_file.with_suffix(".json.bak")
    assert backup_file.exists()


def test_export_reports(tmp_path):
    json_path = tmp_path / "report.json"
    md_path = tmp_path / "report.md"

    reports = [
        CompanyUrlReport(
            company_name="Test Co",
            website=UrlCheckResult(url="https://test.com", status=UrlStatus.ACTIVE),
            careers=UrlCheckResult(url="https://test.com/careers", status=UrlStatus.ACTIVE),
            rss=UrlCheckResult(url=None, status=UrlStatus.NOT_SPECIFIED),
            classification="ACTIVE",
            is_company_active=True,
        )
    ]
    summary = {
        "total_monitored": 1,
        "active_companies": 1,
        "redirected_websites": 0,
        "dead_dns_domains": 0,
        "dead_http_domains": 0,
        "parked_domains": 0,
        "broken_careers_urls": 0,
        "discovered_alternative_careers": 0,
    }

    export_reports(reports, summary, json_path=json_path, md_path=md_path)
    assert json_path.exists()
    assert md_path.exists()
    assert "Test Co" in md_path.read_text(encoding="utf-8")


def test_apply_corrections_partial_preserves_unscanned_companies(tmp_path):
    """Verify that when --limit was used and apply_corrections_to_seed is called,
    it updates only scanned companies and does NOT delete unscanned companies from the seed file."""
    seed_file = tmp_path / "companies_seed.json"
    master_seeds = [
        {"name": "Co 1", "website": "https://www.co1.com", "careers": None, "rss": None},
        {"name": "Co 2", "website": "https://co2.com", "careers": None, "rss": None},
        {"name": "Co 3", "website": "https://co3.com", "careers": None, "rss": None},
    ]
    with open(seed_file, "w", encoding="utf-8") as f:
        json.dump(master_seeds, f, indent=2)

    # Simulate --limit 1 run: only Co 1 was scanned
    sliced_seeds = [master_seeds[0]]
    reports = [
        CompanyUrlReport(
            company_name="Co 1",
            website=UrlCheckResult(url="https://www.co1.com", status=UrlStatus.REDIRECTED, final_url="https://co1.com/"),
            careers=UrlCheckResult(url=None, status=UrlStatus.NOT_SPECIFIED),
            rss=UrlCheckResult(url=None, status=UrlStatus.NOT_SPECIFIED),
            suggested_website="https://co1.com/",
            is_company_active=True,
        )
    ]

    applied = apply_corrections_to_seed(sliced_seeds, reports, seed_path=seed_file, backup=True)
    assert applied == 1

    with open(seed_file, "r", encoding="utf-8") as f:
        result_seeds = json.load(f)

    # CRITICAL: All 3 companies MUST still exist!
    assert len(result_seeds) == 3
    assert result_seeds[0]["name"] == "Co 1"
    assert result_seeds[0]["website"] == "https://co1.com/"
    assert result_seeds[1]["name"] == "Co 2"
    assert result_seeds[2]["name"] == "Co 3"


@pytest.mark.asyncio
async def test_verify_url_http_403_protected_waf():
    """Verify that HTTP 403 Forbidden is classified as PROTECTED_WAF and active."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.url = httpx.URL("https://adreso.in")
    mock_resp.text = "<html><body>403 Forbidden - Cloudflare</body></html>"
    mock_client.get.return_value = mock_resp

    with patch("src.url_verifier.check_dns", return_value=True):
        res = await verify_url(mock_client, "https://adreso.in")
        assert res.status == UrlStatus.PROTECTED_WAF
        assert res.status_code == 403

        # In verify_company
        seed = {"name": "Adreso", "website": "https://adreso.in", "careers": None, "rss": None}
        report = await verify_company(mock_client, seed, probe_careers=False)
        assert report.classification == "PROTECTED_WAF"
        assert report.is_company_active is True
