"""
Tests for notion_client.py — all HTTP calls are intercepted with respx.
"""
from __future__ import annotations

import os
from datetime import date

import httpx
import pytest
import respx

from models import ApplicationStatus, JobApplication
from notion_client import (
    NOTION_API_BASE,
    NotionClient,
    is_notion_configured,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _sample_app(**overrides) -> JobApplication:
    base = dict(
        company_name="Acme Corp",
        job_title="ML Engineer",
        status=ApplicationStatus.applied,
        confidence=0.93,
        source_email_id="msg-001",
        date_applied=date(2026, 5, 1),
        next_action="Complete assessment",
        recruiter_name="Alice",
        salary_range="$130k",
    )
    return JobApplication(**{**base, **overrides})


def _notion_env(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "secret_test_token")
    monkeypatch.setenv("NOTION_DATABASE_ID", "db-abc-123")
    monkeypatch.setenv("NOTION_REVIEW_PAGE_ID", "review-page-xyz")


# ── is_notion_configured ──────────────────────────────────────────────────────

class TestIsNotionConfigured:
    def test_returns_false_when_token_empty(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "")
        monkeypatch.setenv("NOTION_DATABASE_ID", "db-123")
        assert is_notion_configured() is False

    def test_returns_false_when_db_id_empty(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "secret_token")
        monkeypatch.setenv("NOTION_DATABASE_ID", "")
        assert is_notion_configured() is False

    def test_returns_false_for_placeholder_token(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "secret_...")
        monkeypatch.setenv("NOTION_DATABASE_ID", "db-123")
        assert is_notion_configured() is False

    def test_returns_true_when_both_set(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "secret_realtoken123")
        monkeypatch.setenv("NOTION_DATABASE_ID", "real-db-id")
        assert is_notion_configured() is True


# ── _build_properties ─────────────────────────────────────────────────────────

class TestBuildProperties:
    def test_required_fields_present(self, monkeypatch):
        _notion_env(monkeypatch)
        nc = NotionClient()
        app = _sample_app()
        props = nc._build_properties(app)
        assert "Company" in props
        assert "Job Title" in props
        assert "Status" in props

    def test_company_is_title_type(self, monkeypatch):
        _notion_env(monkeypatch)
        nc = NotionClient()
        props = nc._build_properties(_sample_app())
        assert props["Company"]["title"][0]["text"]["content"] == "Acme Corp"

    def test_optional_fields_included_when_set(self, monkeypatch):
        _notion_env(monkeypatch)
        nc = NotionClient()
        props = nc._build_properties(_sample_app())
        assert "Date Applied" in props
        assert props["Date Applied"]["date"]["start"] == "2026-05-01"
        assert "Next Action" in props
        assert "Recruiter" in props
        assert "Salary Range" in props
        assert "Email ID" in props

    def test_optional_fields_absent_when_none(self, monkeypatch):
        _notion_env(monkeypatch)
        nc = NotionClient()
        app = _sample_app(
            date_applied=None,
            next_action=None,
            recruiter_name=None,
            salary_range=None,
            source_email_id=None,
        )
        props = nc._build_properties(app)
        assert "Date Applied" not in props
        assert "Next Action" not in props
        assert "Recruiter" not in props


# ── upsert_application (create path) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_creates_page_when_not_exists(monkeypatch):
    """_find_existing_page returns None → _create_page is called."""
    _notion_env(monkeypatch)
    nc = NotionClient()
    app = _sample_app()

    with respx.mock:
        # query endpoint returns no results
        respx.post(f"{NOTION_API_BASE}/databases/db-abc-123/query").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        # create page returns a page id
        respx.post(f"{NOTION_API_BASE}/pages").mock(
            return_value=httpx.Response(200, json={"id": "new-page-id-001"})
        )

        page_id = await nc.upsert_application(app)

    assert page_id == "new-page-id-001"


# ── upsert_application (update path) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_updates_page_when_exists(monkeypatch):
    """_find_existing_page returns an id → _update_page is called."""
    _notion_env(monkeypatch)
    nc = NotionClient()
    app = _sample_app()

    with respx.mock:
        respx.post(f"{NOTION_API_BASE}/databases/db-abc-123/query").mock(
            return_value=httpx.Response(200, json={"results": [{"id": "existing-page-id"}]})
        )
        respx.patch(f"{NOTION_API_BASE}/pages/existing-page-id").mock(
            return_value=httpx.Response(200, json={"id": "existing-page-id"})
        )

        page_id = await nc.upsert_application(app)

    assert page_id == "existing-page-id"


# ── route_to_manual_review ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_route_to_manual_review_sends_callout_block(monkeypatch):
    """A callout block containing company name and reason is sent to the review page."""
    _notion_env(monkeypatch)
    nc = NotionClient()
    app = _sample_app()

    with respx.mock:
        route = respx.patch(
            f"{NOTION_API_BASE}/blocks/review-page-xyz/children"
        ).mock(return_value=httpx.Response(200, json={}))

        await nc.route_to_manual_review(app, reason="Low confidence score")

    assert route.called
    sent_body = route.calls[0].request.content
    import json
    body = json.loads(sent_body)
    block = body["children"][0]
    assert block["type"] == "callout"
    callout_text = block["callout"]["rich_text"][0]["text"]["content"]
    assert "Acme Corp" in callout_text
    assert "Low confidence score" in callout_text
    assert block["callout"]["icon"]["emoji"] == "⚠️"


# ── HTTP error handling ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_existing_page_raises_on_http_error(monkeypatch):
    """Non-200 response from Notion API raises an httpx error."""
    _notion_env(monkeypatch)
    nc = NotionClient()

    with respx.mock:
        respx.post(f"{NOTION_API_BASE}/databases/db-abc-123/query").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            await nc._find_existing_page("Acme Corp", "ML Engineer")
