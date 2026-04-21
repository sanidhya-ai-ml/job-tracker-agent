from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from extractor import extract_job_application
from models import (
    ApplicationStatus,
    ExtractionRequest,
    ExtractionResponse,
    FunnelStats,
    N8nWebhookPayload,
)
from notion_client import get_notion_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        raise RuntimeError("DB pool not initialised — lifespan error")
    return _pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    await _bootstrap_schema(_pool)
    logger.info("Database pool ready")
    yield
    await _pool.close()
    logger.info("Database pool closed")


async def _bootstrap_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_applications (
                id              SERIAL PRIMARY KEY,
                company_name    TEXT NOT NULL,
                job_title       TEXT NOT NULL,
                status          TEXT NOT NULL,
                date_applied    DATE,
                next_action     TEXT,
                recruiter_name  TEXT,
                salary_range    TEXT,
                confidence      REAL NOT NULL DEFAULT 0,
                source_email_id TEXT UNIQUE,
                notion_page_id  TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS n8n_events (
                id           SERIAL PRIMARY KEY,
                workflow_id  TEXT,
                execution_id TEXT,
                event        TEXT NOT NULL,
                data         JSONB,
                received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )


app = FastAPI(
    title="Job Tracker Agent API",
    description="Backend for AI-powered job application tracking via n8n + OpenAI + Notion",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/extract", response_model=ExtractionResponse, status_code=status.HTTP_200_OK)
async def extract(req: ExtractionRequest) -> ExtractionResponse:
    """Receive a raw email, run LLM extraction, upsert to Notion, persist to DB."""
    try:
        application = await extract_job_application(
            email_id=req.email_id,
            subject=req.subject,
            sender=req.sender,
            body=req.body,
        )
    except Exception as exc:
        logger.exception("Extraction failed for email %s", req.email_id)
        raise HTTPException(status_code=502, detail=f"LLM extraction error: {exc}") from exc

    notion = get_notion_client()
    routed_to_review = application.status == ApplicationStatus.needs_review

    try:
        if routed_to_review:
            await notion.route_to_manual_review(application, reason="Low confidence or ambiguous email")
        else:
            page_id = await notion.upsert_application(application)
            application.notion_page_id = page_id
    except Exception as exc:
        logger.exception("Notion sync failed for email %s", req.email_id)
        # Don't fail the whole request — return result but surface the warning
        return ExtractionResponse(
            success=False,
            application=application,
            error=f"Notion sync failed: {exc}",
            routed_to_review=routed_to_review,
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO job_applications
                (company_name, job_title, status, date_applied, next_action,
                 recruiter_name, salary_range, confidence, source_email_id, notion_page_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (source_email_id) DO UPDATE SET
                status         = EXCLUDED.status,
                next_action    = EXCLUDED.next_action,
                notion_page_id = EXCLUDED.notion_page_id,
                updated_at     = now()
            """,
            application.company_name,
            application.job_title,
            application.status.value,
            application.date_applied,
            application.next_action,
            application.recruiter_name,
            application.salary_range,
            application.confidence,
            application.source_email_id,
            application.notion_page_id,
        )

    return ExtractionResponse(
        success=True,
        application=application,
        routed_to_review=routed_to_review,
    )


@app.post("/webhook/n8n", status_code=status.HTTP_204_NO_CONTENT)
async def n8n_webhook(payload: N8nWebhookPayload) -> None:
    """Log n8n execution events for observability."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO n8n_events (workflow_id, execution_id, event, data)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            payload.workflow_id,
            payload.execution_id,
            payload.event,
            payload.data,
        )
    logger.info("n8n event logged: %s", payload.event)


@app.get("/stats", response_model=FunnelStats)
async def stats() -> FunnelStats:
    """Return application funnel counts for the Slack digest."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT status, COUNT(*) AS cnt
            FROM job_applications
            GROUP BY status
            """
        )

    counts: dict[str, int] = {r["status"]: r["cnt"] for r in rows}
    applied = counts.get(ApplicationStatus.applied.value, 0)
    interview = counts.get(ApplicationStatus.interview.value, 0)
    offer = counts.get(ApplicationStatus.offer.value, 0)
    rejected = counts.get(ApplicationStatus.rejected.value, 0)
    needs_review = counts.get(ApplicationStatus.needs_review.value, 0)
    total = applied + interview + offer + rejected + needs_review

    return FunnelStats(
        applied=applied,
        interview=interview,
        offer=offer,
        rejected=rejected,
        needs_review=needs_review,
        total=total,
        response_rate=round((interview + offer) / applied, 4) if applied else 0.0,
        offer_rate=round(offer / applied, 4) if applied else 0.0,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
