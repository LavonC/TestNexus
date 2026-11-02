"""
FastAPI application for GoaIT - Goa Tech & Engineering Career Intelligence Platform.
Manages application lifespan, database connection, in-process APScheduler, and REST routers.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import config
from src.database import DatabaseManager
from src.gemini_agent import DatabaseQAAgent
from src.routers import admin, chat, companies, exports, jobs, stats
from src.scheduler import create_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("goait_app")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce IP-based sliding window rate limits (60 req/min for data, 10 req/min for chat)."""

    def __init__(self, app, chat_limit: int = 10, data_limit: int = 60, window_seconds: float = 60.0):
        super().__init__(app)
        self.chat_limit = chat_limit
        self.data_limit = data_limit
        self.window = window_seconds
        self.requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Exclude health check and non-API paths (keep-alive must never be throttled)
        if path == "/api/health" or not path.startswith("/api"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        is_chat = path.startswith("/api/chat")
        limit = self.chat_limit if is_chat else self.data_limit
        bucket_key = f"{client_ip}:{'chat' if is_chat else 'data'}"

        timestamps = [t for t in self.requests[bucket_key] if now - t < self.window]
        if len(timestamps) >= limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please wait a minute before sending more requests."},
            )

        timestamps.append(now)
        self.requests[bucket_key] = timestamps
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup (DB, seed data, scheduler) and clean shutdown."""
    logger.info("Initializing GoaIT application...")

    # 1. Initialize Database Manager (Turso LibSQL or local SQLite)
    db = DatabaseManager(
        turso_url=config.TURSO_DATABASE_URL,
        auth_token=config.TURSO_AUTH_TOKEN,
        db_path=config.DB_PATH,
    )
    await db.init_db()
    app.state.db = db

    # 2. Check and seed companies if database is fresh
    current_stats = await db.get_stats()
    if current_stats["total_companies"] == 0 and config.SEED_FILE_PATH.exists():
        try:
            seeds = json.loads(config.SEED_FILE_PATH.read_text(encoding="utf-8"))
            if isinstance(seeds, list) and seeds:
                logger.info("Fresh database detected. Seeding %d initial Goan companies...", len(seeds))
                await db.seed_companies(seeds, reset=False)
        except Exception as seed_err:
            logger.warning("Could not auto-seed database from %s: %s", config.SEED_FILE_PATH, seed_err)

    # 3. Initialize QA Agent for AI chat
    qa_agent = DatabaseQAAgent(db_manager=db)
    app.state.qa_agent = qa_agent

    # 4. Start background scraping scheduler
    scheduler = create_scheduler(db)
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("APScheduler background scraper started (runs every 6 hours).")

    yield

    # Shutdown sequence
    logger.info("Shutting down GoaIT application...")
    try:
        scheduler.shutdown(wait=False)
    except Exception as e:
        logger.debug("Error shutting down scheduler: %s", e)

    await db.close()
    logger.info("Database connection closed cleanly.")


def create_app() -> FastAPI:
    """Create and configure FastAPI application instance."""
    app = FastAPI(
        title="GoaIT - Goa Tech Career Intelligence API",
        description="Continuous career intelligence platform for 238+ Goan tech companies, engineering roles, and job market analytics.",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS configuration - whitelist frontend static site domains
    allowed_origins = [
        config.FRONTEND_URL,
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=r"https://.*\.onrender\.com",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # GZip compression for responses > 1000 bytes
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Rate limiting middleware (60 req/min for data, 10 req/min for chat)
    app.add_middleware(RateLimitMiddleware)

    # Include API Routers
    app.include_router(stats.router)
    app.include_router(companies.router)
    app.include_router(jobs.router)
    app.include_router(chat.router)
    app.include_router(exports.router)
    app.include_router(admin.router)

    # Health check endpoint for UptimeRobot keep-alive and Render
    @app.get("/api/health", tags=["Health"], summary="Health check endpoint for keep-alive monitoring")
    async def health_check() -> dict[str, Any]:
        """Keep-alive ping endpoint used by UptimeRobot (prevents Render 15-min idle spin-down)."""
        return {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "goait-api",
            "version": "2.0.0",
        }

    # Smart Search Auto-Suggestions
    @app.get("/api/search/suggest", tags=["Search"], summary="As-you-type search suggestions")
    async def search_suggestions(
        request: Request,
        q: str = Query("", description="Query prefix to suggest titles and companies for"),
        limit: int = Query(10, ge=1, le=25),
    ) -> list[str]:
        """Return search suggestions for autocomplete dropdowns."""
        db: DatabaseManager = request.app.state.db
        return await db.get_search_suggestions(query=q, limit=limit)

    @app.get("/", tags=["Root"])
    async def root() -> JSONResponse:
        """API landing page."""
        return JSONResponse({
            "name": "GoaIT Career Intelligence API",
            "version": "2.0.0",
            "health": "/api/health",
            "docs": "/docs",
            "stats": "/api/stats",
        })

    return app


app = create_app()
