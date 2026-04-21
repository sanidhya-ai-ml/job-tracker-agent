from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ApplicationStatus(str, Enum):
    applied = "Applied"
    interview = "Interview"
    offer = "Offer"
    rejected = "Rejected"
    needs_review = "needs_review"


class JobApplication(BaseModel):
    company_name: str = Field(..., description="Name of the hiring company")
    job_title: str = Field(..., description="Role or position title")
    status: ApplicationStatus = Field(..., description="Current application status")
    date_applied: Optional[date] = Field(None, description="Date the application was submitted")
    next_action: Optional[str] = Field(None, description="Next step the applicant should take")
    recruiter_name: Optional[str] = Field(None, description="Name of the recruiter or contact")
    salary_range: Optional[str] = Field(None, description="Salary range mentioned in the email")
    confidence: float = Field(..., ge=0.0, le=1.0, description="LLM extraction confidence score")
    source_email_id: Optional[str] = Field(None, description="Gmail message ID for traceability")
    notion_page_id: Optional[str] = Field(None, description="Notion page ID after upsert")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EmailEvent(BaseModel):
    email_id: str = Field(..., description="Gmail message ID")
    subject: str
    sender: str
    received_at: datetime
    body: str = Field(..., description="Plain text email body")
    labels: list[str] = Field(default_factory=list)


class ExtractionRequest(BaseModel):
    email_id: str
    subject: str
    sender: str
    body: str
    received_at: Optional[datetime] = None


class ExtractionResponse(BaseModel):
    success: bool
    application: Optional[JobApplication] = None
    error: Optional[str] = None
    routed_to_review: bool = False


class FunnelStats(BaseModel):
    applied: int = 0
    interview: int = 0
    offer: int = 0
    rejected: int = 0
    needs_review: int = 0
    total: int = 0
    response_rate: float = 0.0
    offer_rate: float = 0.0
    as_of: datetime = Field(default_factory=datetime.utcnow)


class N8nWebhookPayload(BaseModel):
    workflow_id: Optional[str] = None
    execution_id: Optional[str] = None
    event: str
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
