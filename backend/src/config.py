"""
Configuration module for the Goa Tech & Engineering Career Intelligence Pipeline.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Resolve project root (parent of src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load environment variables from .env file if present
load_dotenv(PROJECT_ROOT / ".env")


def _resolve_data_path(subpath: str) -> Path:
    """Resolve file path checking PROJECT_ROOT, then parent directory (e.g. if rootDir=backend on Render)."""
    p1 = PROJECT_ROOT / subpath
    if p1.exists():
        return p1
    p2 = PROJECT_ROOT.parent / subpath
    if p2.exists():
        return p2
    return p1


class Config:
    """Application settings with environment variable overrides."""

    PROJECT_ROOT: Path = PROJECT_ROOT

    # Gemini API Settings
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    GEMINI_API_KEYS: list[str] = [
        k.strip()
        for k in os.getenv("GEMINI_API_KEYS", "").split(",")
        if k.strip()
    ]
    if not GEMINI_API_KEYS and GEMINI_API_KEY:
        GEMINI_API_KEYS = [GEMINI_API_KEY]

    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    GEMINI_GROUNDING_MODEL: str = os.getenv("GEMINI_GROUNDING_MODEL", "gemini-3.8-flash")
    GEMINI_FALLBACK_MODELS: list[str] = [
        m.strip()
        for m in os.getenv(
            "GEMINI_FALLBACK_MODELS",
            "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3-flash-preview,gemini-flash-lite-latest",
        ).split(",")
        if m.strip()
    ]

    # Search Grounding & Free-Tier Optimization
    ENABLE_SEARCH_GROUNDING: bool = os.getenv(
        "ENABLE_SEARCH_GROUNDING", "false"
    ).lower() in ("true", "1", "yes")
    RATE_LIMIT_RPM: float = float(os.getenv("RATE_LIMIT_RPM", "12.0"))
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "5"))

    # Turso / LibSQL Database Settings
    TURSO_DATABASE_URL: str = os.getenv("TURSO_DATABASE_URL", "")
    TURSO_AUTH_TOKEN: str = os.getenv("TURSO_AUTH_TOKEN", "")

    # Web & Admin Settings
    ADMIN_SECRET: str = os.getenv("ADMIN_SECRET", "goait-secret-key")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")

    # Email Alerts (Resend)
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    RESEND_FROM_EMAIL: str = os.getenv("RESEND_FROM_EMAIL", "alerts@goait.dev")

    # Local LLM Fallback (Ollama / OpenAI-compatible - disabled on Render)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")
    USE_LOCAL_LLM: bool = os.getenv("USE_LOCAL_LLM", "false").lower() in (
        "true",
        "1",
        "yes",
    )

    # Scraping & Concurrency Settings (throttled for Render 512MB free tier)
    MAX_CONCURRENT_SCRAPES: int = int(os.getenv("MAX_CONCURRENT_SCRAPES", "5"))
    HTTP_TIMEOUT_SECONDS: float = float(os.getenv("HTTP_TIMEOUT_SECONDS", "12.0"))
    RSS_TIMEOUT_SECONDS: float = float(os.getenv("RSS_TIMEOUT_SECONDS", "10.0"))
    PLAYWRIGHT_FALLBACK_ENABLED: bool = False
    PLAYWRIGHT_TIMEOUT_SECONDS: float = float(
        os.getenv("PLAYWRIGHT_TIMEOUT_SECONDS", "25.0")
    )

    # File & Database Paths
    DB_PATH: Path = _resolve_data_path(os.getenv("DB_PATH", "data/goa_companies.db"))
    SEED_FILE_PATH: Path = _resolve_data_path(
        os.getenv("SEED_FILE_PATH", "data/companies_seed.json")
    )
    EXPORTS_DIR: Path = _resolve_data_path(os.getenv("EXPORTS_DIR", "data/exports"))

    # HTTP Client Configuration
    USER_AGENT: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    )

    @classmethod
    def get_browser_headers(cls) -> dict[str, str]:
        """Return full standard browser headers to prevent 403 blocks by Cloudflare and WAFs."""
        return {
            "User-Agent": cls.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Not A(Brand";v="8", "Chromium";v="131", "Google Chrome";v="131"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
        }

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def ensure_directories(cls) -> None:
        """Ensure data and exports directories exist."""
        cls.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


config = Config()
