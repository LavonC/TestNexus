"""
Unit tests for the multi-layer scraper and HTML cleaner.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.models import CompanySeed
from src.scraper import (
    Scraper,
    clean_html_to_markdown,
    fetch_rss_feed,
    fetch_url_static,
)


def test_clean_html_to_markdown_strips_noise():
    raw_html = """
    <html>
      <head><style>.header { color: red; }</style></head>
      <body>
        <nav><a href="/home">Home</a></nav>
        <header><h1>Header Title</h1></header>
        <script>console.log("noisy script");</script>
        <svg><path d="M0 0"></path></svg>
        <div id="content">
          <h2>Careers at Acme Goa</h2>
          <p>We are seeking innovative Software Engineers in Panaji.</p>
          <p>Apply via our portal: <a href="https://acme.keka.com/careers">Keka Job Board</a></p>
          <p>Or write to <a href="mailto:jobs@acme.com">jobs@acme.com</a></p>
        </div>
        <footer><p>Copyright 2026 Acme Corp</p></footer>
      </body>
    </html>
    """

    markdown_text, links = clean_html_to_markdown(raw_html, base_url="https://acme.com")

    # Verify script, style, nav, svg, footer are stripped
    assert "noisy script" not in markdown_text
    assert "color: red" not in markdown_text
    assert "Copyright 2026" not in markdown_text
    assert "Home" not in markdown_text

    # Verify content preserved
    assert "Careers at Acme Goa" in markdown_text
    assert "Software Engineers in Panaji" in markdown_text

    # Verify ATS and mailto links extracted
    assert any("keka.com" in link for link in links)
    assert any("mailto:jobs@acme.com" in link for link in links)


def test_clean_html_truncation():
    long_html = "<html><body>" + "<p>A lot of text here. </p>" * 2000 + "</body></html>"
    text, links = clean_html_to_markdown(long_html, max_chars=500)
    assert len(text) <= 500


@pytest.mark.asyncio
async def test_fetch_url_static_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body><h1>Careers</h1><a href='https://jobs.lever.co/test'>Apply</a></body></html>"
    mock_resp.url = "https://example.com/careers"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = mock_resp

    text, links, status, raw_html = await fetch_url_static(
        mock_client, "https://example.com/careers"
    )

    assert status == 200
    assert "Careers" in text
    assert any("lever.co" in link for link in links)


@pytest.mark.asyncio
async def test_fetch_url_static_404():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"
    mock_resp.url = "https://example.com/bad"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = mock_resp

    text, links, status, raw_html = await fetch_url_static(
        mock_client, "https://example.com/bad"
    )

    assert status == 404
    assert "HTTP 404" in text
    assert links == []


@pytest.mark.asyncio
async def test_fetch_rss_feed():
    sample_rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Tech Blog</title>
        <item>
          <title>Expanding Our Goa Office</title>
          <pubDate>Mon, 15 Oct 2026 10:00:00 GMT</pubDate>
          <description>We just opened a new center in Verna.</description>
        </item>
      </channel>
    </rss>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_rss_xml

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = mock_resp

    summary = await fetch_rss_feed(mock_client, "https://example.com/feed")
    assert "Expanding Our Goa Office" in summary
    assert "Verna" in summary


@pytest.mark.asyncio
async def test_scraper_orchestration():
    scraper = Scraper(concurrency=2)
    company = CompanySeed(
        name="Mock Co",
        website="https://mock.com",
        careers="https://mock.com/careers",
        rss=None,
    )

    substantial_career_text = (
        "Careers at Mock Co. " * 30
    )  # > 300 chars to test static path
    with (
        patch("src.scraper.fetch_url_static") as mock_fetch,
        patch("src.scraper.fetch_rss_feed") as mock_rss,
    ):
        mock_fetch.side_effect = [
            ("Homepage content here", [], 200, "<html>home</html>"),
            (
                substantial_career_text,
                ["[Apply](https://keka.com/mock)"],
                200,
                "<html><div>careers</div></html>",
            ),
        ]
        mock_rss.return_value = "No RSS feed specified."

        scraped = await scraper.scrape_company(company)

        assert scraped.company_name == "Mock Co"
        assert "Homepage content" in scraped.homepage_text
        assert "Careers at Mock Co." in scraped.careers_page_text
        assert any("keka.com" in link for link in scraped.ats_links)
        assert scraped.used_playwright is False
        assert scraped.careers_fetch_failed is False


@pytest.mark.asyncio
async def test_scraper_handles_sparse_or_spa_statically():
    scraper = Scraper(concurrency=2)
    company = CompanySeed(
        name="SPA Co",
        website="https://spa.com",
        careers="https://spa.com/careers",
        rss=None,
    )

    with (
        patch("src.scraper.fetch_url_static") as mock_fetch,
        patch("src.scraper.fetch_rss_feed") as mock_rss,
    ):
        # Careers page returns sparse text and SPA marker <div id="root">
        mock_fetch.side_effect = [
            ("Home", [], 200, "<html>home</html>"),
            ("Loading...", ["[Apply](https://keka.com/spaco)"], 200, '<html><div id="root"></div></html>'),
        ]
        mock_rss.return_value = "No RSS."

        scraped = await scraper.scrape_company(company)

        # Statically processed with 0 Playwright usage
        assert scraped.used_playwright is False
        assert scraped.company_name == "SPA Co"
        assert any("keka.com/spaco" in link for link in scraped.ats_links)
        assert scraped.needs_search_grounding is True
