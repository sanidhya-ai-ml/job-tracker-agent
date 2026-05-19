"""
FastAPI endpoint tests — database pool and extractor are mocked.
Uses the `client` fixture from conftest.py which patches asyncpg.create_pool.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from models import ApplicationStatus, JobApplication


def _make_application(**overrides) -> JobApplication:
    base = dict(
        company_name="Acme Corp",
        job_title="ML Engineer",
        status=ApplicationStatus.applied,
        confidence=0.93,
        source_email_id="msg-001",
    )
    return JobApplication(**{**base, **overrides})


# ── /health ───────────────────────────────────────────────────────────────────

def test_health(client):
    c, _ = client
    resp = c.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── /extract ──────────────────────────────────────────────────────────────────

def test_extract_happy_path(client):
    """Valid email → 200, success=True, routed_to_review=False."""
    c, _ = client
    app = _make_application(status=ApplicationStatus.applied, confidence=0.93)

    with patch("main.extract_job_application", AsyncMock(return_value=app)):
        with patch("main.is_notion_configured", return_value=False):
            resp = c.post("/extract", json={
                "email_id": "msg-001",
                "subject": "Interview Invite",
                "sender": "hr@acme.com",
                "body": "We'd like to schedule an interview.",
            })

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["routed_to_review"] is False
    assert data["application"]["company_name"] == "Acme Corp"
    assert data["application"]["confidence"] == 0.93


def test_extract_low_confidence_routes_to_review(client):
    """Low-confidence extraction sets routed_to_review=True."""
    c, _ = client
    app = _make_application(status=ApplicationStatus.needs_review, confidence=0.55)

    with patch("main.extract_job_application", AsyncMock(return_value=app)):
        with patch("main.is_notion_configured", return_value=False):
            resp = c.post("/extract", json={
                "email_id": "msg-002",
                "subject": "Newsletter",
                "sender": "no-reply@spam.com",
                "body": "Unsubscribe here...",
            })

    assert resp.status_code == 200
    data = resp.json()
    assert data["routed_to_review"] is True
    assert data["application"]["status"] == ApplicationStatus.needs_review.value


def test_extract_llm_failure_returns_502(client):
    """Exception from extract_job_application → HTTP 502."""
    c, _ = client

    with patch("main.extract_job_application", AsyncMock(side_effect=RuntimeError("Gemini down"))):
        resp = c.post("/extract", json={
            "email_id": "msg-003",
            "subject": "Test",
            "sender": "x@x.com",
            "body": "body",
        })

    assert resp.status_code == 502
    assert "LLM extraction error" in resp.json()["detail"]


def test_extract_missing_body_field(client):
    """Request missing required 'body' field → 422 Unprocessable Entity."""
    c, _ = client
    resp = c.post("/extract", json={
        "email_id": "msg-004",
        "subject": "Test",
        "sender": "x@x.com",
        # body is missing
    })
    assert resp.status_code == 422


# ── /applications ─────────────────────────────────────────────────────────────

def test_list_applications_empty(client):
    """Empty DB → returns empty list."""
    c, mock_conn = client
    mock_conn.fetch = AsyncMock(return_value=[])
    resp = c.get("/applications")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_applications_with_rows(client):
    """DB rows are returned as a list of dicts."""
    c, mock_conn = client
    from datetime import datetime

    mock_row = {
        "id": 1,
        "company_name": "Google",
        "job_title": "SWE",
        "status": "Applied",
        "date_applied": date(2026, 5, 1),
        "next_action": None,
        "recruiter_name": "Bob",
        "salary_range": None,
        "confidence": 0.95,
        "source_email_id": "msg-010",
        "notion_page_id": None,
        "created_at": datetime(2026, 5, 1, 12, 0, 0),
        "updated_at": datetime(2026, 5, 1, 12, 0, 0),
    }
    mock_conn.fetch = AsyncMock(return_value=[mock_row])
    resp = c.get("/applications")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["company_name"] == "Google"


def test_list_applications_pagination_params(client):
    """limit and offset query params are accepted without error."""
    c, mock_conn = client
    mock_conn.fetch = AsyncMock(return_value=[])
    resp = c.get("/applications?limit=10&offset=20")
    assert resp.status_code == 200


# ── /stats ────────────────────────────────────────────────────────────────────

def test_stats_empty_db(client):
    """No rows in DB → all counts zero, rates zero."""
    c, mock_conn = client
    mock_conn.fetch = AsyncMock(return_value=[])
    resp = c.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["applied"] == 0
    assert data["total"] == 0
    assert data["response_rate"] == 0.0
    assert data["offer_rate"] == 0.0


def test_stats_with_data(client):
    """Correct response_rate and offer_rate calculated from DB counts."""
    c, mock_conn = client
    mock_conn.fetch = AsyncMock(return_value=[
        {"status": "Applied", "cnt": 10},
        {"status": "Interview", "cnt": 3},
        {"status": "Offer", "cnt": 1},
        {"status": "Rejected", "cnt": 4},
        {"status": "needs_review", "cnt": 2},
    ])
    resp = c.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["applied"] == 10
    assert data["interview"] == 3
    assert data["offer"] == 1
    assert data["total"] == 20
    assert data["response_rate"] == round(4 / 10, 4)
    assert data["offer_rate"] == round(1 / 10, 4)


# ── /webhook/n8n ──────────────────────────────────────────────────────────────

def test_n8n_webhook_logged(client):
    """Valid n8n payload → 200 with status=logged."""
    c, _ = client
    resp = c.post("/webhook/n8n", json={
        "event": "execution.started",
        "workflow_id": "wf-abc",
        "execution_id": "exec-001",
        "data": {"key": "value"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "logged"
    assert data["event"] == "execution.started"


def test_n8n_webhook_minimal_payload(client):
    """Only required 'event' field → still returns 200."""
    c, _ = client
    resp = c.post("/webhook/n8n", json={"event": "test.event"})
    assert resp.status_code == 200
    assert resp.json()["event"] == "test.event"


def test_n8n_webhook_missing_event(client):
    """Missing required 'event' field → 422."""
    c, _ = client
    resp = c.post("/webhook/n8n", json={"workflow_id": "wf-x"})
    assert resp.status_code == 422
