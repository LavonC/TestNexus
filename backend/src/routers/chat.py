"""
AI Q&A chat API router with 3-tier strategy.
Tier 1: User-supplied Gemini API key (unlimited server quota).
Tier 2: Server-side Gemini API key (rate-limited, with model cascading).
Tier 3: 100% offline database search fallback (zero API key needed).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from src.database import DatabaseManager
from src.gemini_agent import DatabaseQAAgent
from src.models import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["AI Chat"])


@router.post("", response_model=ChatResponse, summary="Ask natural language question grounded in GoaIT database")
async def chat_qa(
    request: Request,
    payload: ChatRequest,
) -> ChatResponse:
    """
    Answer career intelligence questions using database grounding and tool calling.
    Accepts an optional user-supplied Gemini API key to shift quota to the user.
    """
    db: DatabaseManager = request.app.state.db
    question = payload.question.strip()
    if not question:
        return ChatResponse(
            answer="Please enter a question to ask the career intelligence assistant.",
            source="system",
        )

    # Initialize agent instance with database manager
    agent: DatabaseQAAgent = getattr(request.app.state, "qa_agent", None)
    if agent is None:
        agent = DatabaseQAAgent(db_manager=db)

    user_key = (payload.api_key or "").strip() or None
    chosen_model = (payload.model or "").strip() or None

    try:
        answer = await agent.ask(
            question=question,
            user_api_key=user_key,
            model=chosen_model,
        )

        source = "gemini_user" if user_key else "gemini_server"
        if "AI analysis unavailable" in answer:
            source = "offline_db"

        return ChatResponse(
            answer=answer,
            source=source,
            model=chosen_model or getattr(agent, "model_name", "gemini-3.8-flash"),
        )
    except Exception as exc:
        logger.warning("Chat endpoint error: %s. Falling back to offline QA.", exc)
        fallback_answer = await agent._offline_fallback_qa(question)
        return ChatResponse(
            answer=fallback_answer,
            source="offline_db",
            model="offline",
        )
