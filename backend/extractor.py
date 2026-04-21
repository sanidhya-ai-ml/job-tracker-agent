from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from openai import AsyncOpenAI

from models import ApplicationStatus, JobApplication

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extract_job_email.txt"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()
    return _client


async def extract_job_application(
    email_id: str,
    subject: str,
    sender: str,
    body: str,
) -> JobApplication:
    """Call OpenAI with structured JSON output and return a JobApplication.

    Falls back to status=needs_review when confidence < 0.7 or parsing fails.
    """
    user_message = f"""Subject: {subject}
From: {sender}

{body}"""

    try:
        response = await get_client().chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=512,
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)

        confidence = float(data.get("confidence", 0.0))

        # Force needs_review when confidence is too low
        if confidence < 0.7:
            logger.warning("Low confidence (%.2f) for email %s — routing to needs_review", confidence, email_id)
            data["status"] = ApplicationStatus.needs_review

        # Coerce date string → date object
        date_raw = data.get("date_applied")
        if isinstance(date_raw, str):
            try:
                data["date_applied"] = date.fromisoformat(date_raw)
            except ValueError:
                data["date_applied"] = None

        return JobApplication(
            company_name=data.get("company_name", "Unknown"),
            job_title=data.get("job_title", "Unknown"),
            status=ApplicationStatus(data.get("status", ApplicationStatus.needs_review)),
            date_applied=data.get("date_applied"),
            next_action=data.get("next_action"),
            recruiter_name=data.get("recruiter_name"),
            salary_range=data.get("salary_range"),
            confidence=confidence,
            source_email_id=email_id,
        )

    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.exception("Extraction parse error for email %s: %s", email_id, exc)
        return JobApplication(
            company_name="Unknown",
            job_title="Unknown",
            status=ApplicationStatus.needs_review,
            confidence=0.0,
            source_email_id=email_id,
        )
    except Exception as exc:
        logger.exception("OpenAI API error for email %s: %s", email_id, exc)
        raise
