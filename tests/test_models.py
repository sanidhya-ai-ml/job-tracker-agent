"""Tests for Pydantic models in models.py — no I/O, no mocking needed."""
from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from models import (
    ApplicationStatus,
    EmailEvent,
    ExtractionRequest,
    ExtractionResponse,
    FunnelStats,
    JobApplication,
    N8nWebhookPayload,
)


# ── ApplicationStatus ─────────────────────────────────────────────────────────

class TestApplicationStatus:
    def test_all_values_exist(self):
        assert ApplicationStatus.applied.value == "Applied"
        assert ApplicationStatus.interview.value == "Interview"
        assert ApplicationStatus.offer.value == "Offer"
        assert ApplicationStatus.rejected.value == "Rejected"
        assert ApplicationStatus.needs_review.value == "needs_review"

    def test_is_str_enum(self):
        assert isinstance(ApplicationStatus.applied, str)

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            ApplicationStatus("NotAStatus")


# ── JobApplication ────────────────────────────────────────────────────────────

class TestJobApplication:
    def _valid(self, **overrides) -> dict:
        base = {
            "company_name": "Acme Corp",
            "job_title": "ML Engineer",
            "status": ApplicationStatus.applied,
            "confidence": 0.92,
        }
        return {**base, **overrides}

    def test_minimal_construction(self):
        app = JobApplication(**self._valid())
        assert app.company_name == "Acme Corp"
        assert app.job_title == "ML Engineer"
        assert app.status == ApplicationStatus.applied
        assert app.confidence == 0.92

    def test_optional_fields_default_none(self):
        app = JobApplication(**self._valid())
        assert app.date_applied is None
        assert app.next_action is None
        assert app.recruiter_name is None
        assert app.salary_range is None
        assert app.source_email_id is None
        assert app.notion_page_id is None

    def test_optional_fields_set(self):
        app = JobApplication(**self._valid(
            date_applied=date(2026, 5, 1),
            next_action="Complete assessment",
            recruiter_name="Priya Sharma",
            salary_range="$120k–$150k",
            source_email_id="msg-abc-123",
        ))
        assert app.date_applied == date(2026, 5, 1)
        assert app.next_action == "Complete assessment"
        assert app.recruiter_name == "Priya Sharma"

    def test_confidence_lower_bound(self):
        app = JobApplication(**self._valid(confidence=0.0))
        assert app.confidence == 0.0

    def test_confidence_upper_bound(self):
        app = JobApplication(**self._valid(confidence=1.0))
        assert app.confidence == 1.0

    def test_confidence_below_zero_raises(self):
        with pytest.raises(ValidationError):
            JobApplication(**self._valid(confidence=-0.1))

    def test_confidence_above_one_raises(self):
        with pytest.raises(ValidationError):
            JobApplication(**self._valid(confidence=1.01))

    def test_created_at_auto_set(self):
        app = JobApplication(**self._valid())
        assert isinstance(app.created_at, datetime)

    def test_status_from_string(self):
        app = JobApplication(**self._valid(status="Applied"))
        assert app.status == ApplicationStatus.applied

    def test_needs_review_status(self):
        app = JobApplication(**self._valid(status=ApplicationStatus.needs_review, confidence=0.5))
        assert app.status == ApplicationStatus.needs_review


# ── ExtractionRequest ─────────────────────────────────────────────────────────

class TestExtractionRequest:
    def test_required_fields(self):
        req = ExtractionRequest(
            email_id="msg-001",
            subject="Interview Invite",
            sender="hr@company.com",
            body="We would like to schedule an interview.",
        )
        assert req.email_id == "msg-001"
        assert req.received_at is None

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            ExtractionRequest(email_id="x", subject="x")  # missing sender, body


# ── ExtractionResponse ────────────────────────────────────────────────────────

class TestExtractionResponse:
    def test_defaults(self):
        resp = ExtractionResponse(success=True)
        assert resp.application is None
        assert resp.error is None
        assert resp.routed_to_review is False

    def test_with_application(self):
        app = JobApplication(
            company_name="Google",
            job_title="SWE",
            status=ApplicationStatus.applied,
            confidence=0.95,
        )
        resp = ExtractionResponse(success=True, application=app)
        assert resp.application.company_name == "Google"


# ── FunnelStats ───────────────────────────────────────────────────────────────

class TestFunnelStats:
    def test_defaults_zero(self):
        stats = FunnelStats()
        assert stats.applied == 0
        assert stats.total == 0
        assert stats.response_rate == 0.0
        assert stats.offer_rate == 0.0

    def test_rates_set_explicitly(self):
        stats = FunnelStats(
            applied=10, interview=3, offer=1, rejected=4, needs_review=2,
            total=20,
            response_rate=0.4,
            offer_rate=0.1,
        )
        assert stats.response_rate == 0.4
        assert stats.offer_rate == 0.1

    def test_as_of_auto_set(self):
        stats = FunnelStats()
        assert isinstance(stats.as_of, datetime)


# ── N8nWebhookPayload ─────────────────────────────────────────────────────────

class TestN8nWebhookPayload:
    def test_minimal(self):
        payload = N8nWebhookPayload(event="execution.started")
        assert payload.event == "execution.started"
        assert payload.workflow_id is None
        assert payload.data == {}

    def test_with_data(self):
        payload = N8nWebhookPayload(
            event="execution.finished",
            workflow_id="wf-abc",
            execution_id="exec-001",
            data={"status": "success"},
        )
        assert payload.data["status"] == "success"
