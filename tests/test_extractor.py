"""Tests for extractor.py — Gemini API calls are fully mocked."""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import ApplicationStatus, JobApplication


def _make_llm_response(content: str):
    """Build a fake openai ChatCompletion response object."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _good_payload(**overrides) -> dict:
    base = {
        "company_name": "Acme Corp",
        "job_title": "ML Engineer",
        "status": "Applied",
        "date_applied": "2026-05-01",
        "next_action": "Complete take-home assignment",
        "recruiter_name": "Alice Smith",
        "salary_range": "$130k–$160k",
        "confidence": 0.93,
    }
    return {**base, **overrides}


@pytest.mark.asyncio
class TestExtractJobApplication:
    async def test_happy_path(self):
        """Well-formed JSON from Gemini → correct JobApplication returned."""
        from extractor import extract_job_application

        payload = _good_payload()
        mock_resp = _make_llm_response(json.dumps(payload))

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("extractor.get_client", return_value=mock_client):
            result = await extract_job_application(
                email_id="msg-001",
                subject="Interview Invite at Acme Corp",
                sender="hr@acme.com",
                body="We'd like to schedule an interview for the ML Engineer role.",
            )

        assert isinstance(result, JobApplication)
        assert result.company_name == "Acme Corp"
        assert result.job_title == "ML Engineer"
        assert result.status == ApplicationStatus.applied
        assert result.confidence == 0.93
        assert result.source_email_id == "msg-001"

    async def test_date_string_coerced_to_date(self):
        """ISO date string in JSON is converted to a date object."""
        from extractor import extract_job_application

        payload = _good_payload(date_applied="2026-04-15")
        mock_resp = _make_llm_response(json.dumps(payload))
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("extractor.get_client", return_value=mock_client):
            result = await extract_job_application("msg-002", "sub", "sender", "body")

        assert result.date_applied == date(2026, 4, 15)

    async def test_invalid_date_becomes_none(self):
        """Unparseable date string → date_applied is None (not a crash)."""
        from extractor import extract_job_application

        payload = _good_payload(date_applied="not-a-date")
        mock_resp = _make_llm_response(json.dumps(payload))
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("extractor.get_client", return_value=mock_client):
            result = await extract_job_application("msg-003", "sub", "sender", "body")

        assert result.date_applied is None

    async def test_low_confidence_forces_needs_review(self):
        """Confidence < 0.7 overrides whatever status was returned."""
        from extractor import extract_job_application

        payload = _good_payload(status="Applied", confidence=0.55)
        mock_resp = _make_llm_response(json.dumps(payload))
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("extractor.get_client", return_value=mock_client):
            result = await extract_job_application("msg-004", "sub", "sender", "body")

        assert result.status == ApplicationStatus.needs_review
        assert result.confidence == 0.55

    async def test_confidence_at_threshold_not_overridden(self):
        """Confidence exactly 0.7 should NOT be downgraded to needs_review."""
        from extractor import extract_job_application

        payload = _good_payload(status="Interview", confidence=0.7)
        mock_resp = _make_llm_response(json.dumps(payload))
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("extractor.get_client", return_value=mock_client):
            result = await extract_job_application("msg-005", "sub", "sender", "body")

        assert result.status == ApplicationStatus.interview

    async def test_malformed_json_returns_fallback(self):
        """Non-JSON response → fallback JobApplication with needs_review and confidence 0."""
        from extractor import extract_job_application

        mock_resp = _make_llm_response("This is not JSON at all.")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("extractor.get_client", return_value=mock_client):
            result = await extract_job_application("msg-006", "sub", "sender", "body")

        assert result.status == ApplicationStatus.needs_review
        assert result.confidence == 0.0
        assert result.company_name == "Unknown"
        assert result.source_email_id == "msg-006"

    async def test_missing_required_fields_returns_fallback(self):
        """JSON missing company_name/job_title → fallback with Unknown values."""
        from extractor import extract_job_application

        partial = {"confidence": 0.8, "status": "Applied"}
        mock_resp = _make_llm_response(json.dumps(partial))
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("extractor.get_client", return_value=mock_client):
            result = await extract_job_application("msg-007", "sub", "sender", "body")

        assert result.company_name == "Unknown"
        assert result.job_title == "Unknown"

    async def test_api_exception_propagates(self):
        """Exceptions from the Gemini API (network errors etc.) are re-raised."""
        from extractor import extract_job_application

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("Connection timeout")
        )

        with patch("extractor.get_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Connection timeout"):
                await extract_job_application("msg-008", "sub", "sender", "body")

    async def test_source_email_id_attached(self):
        """email_id parameter is always stored on the returned model."""
        from extractor import extract_job_application

        payload = _good_payload()
        mock_resp = _make_llm_response(json.dumps(payload))
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("extractor.get_client", return_value=mock_client):
            result = await extract_job_application("unique-id-xyz", "sub", "sender", "body")

        assert result.source_email_id == "unique-id-xyz"
