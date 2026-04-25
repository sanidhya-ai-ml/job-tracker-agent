from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

from models import ApplicationStatus, JobApplication

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionClient:
    def __init__(self) -> None:
        self._token = os.environ["NOTION_TOKEN"]
        self._db_id = os.environ["NOTION_DATABASE_ID"]
        self._review_page_id = os.environ["NOTION_REVIEW_PAGE_ID"]
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def upsert_application(self, app: JobApplication) -> str:
        """Create or update a Notion page for the application. Returns the page ID."""
        existing_id = await self._find_existing_page(app.company_name, app.job_title)
        if existing_id:
            await self._update_page(existing_id, app)
            return existing_id
        return await self._create_page(app)

    async def route_to_manual_review(self, app: JobApplication, reason: str) -> None:
        """Append a comment block to the Manual Review page."""
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{NOTION_API_BASE}/blocks/{self._review_page_id}/children",
                headers=self._headers,
                json={
                    "children": [
                        {
                            "object": "block",
                            "type": "callout",
                            "callout": {
                                "rich_text": [
                                    {
                                        "type": "text",
                                        "text": {
                                            "content": (
                                                f"Review needed: {app.company_name} — {app.job_title}\n"
                                                f"Email ID: {app.source_email_id}\n"
                                                f"Reason: {reason}"
                                            )
                                        },
                                    }
                                ],
                                "icon": {"emoji": "⚠️"},
                                "color": "yellow_background",
                            },
                        }
                    ]
                },
            )

    async def _find_existing_page(self, company: str, title: str) -> Optional[str]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{NOTION_API_BASE}/databases/{self._db_id}/query",
                headers=self._headers,
                json={
                    "filter": {
                        "and": [
                            {"property": "Company", "title": {"equals": company}},
                            {"property": "Job Title", "rich_text": {"equals": title}},
                        ]
                    }
                },
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            return results[0]["id"] if results else None

    async def _create_page(self, app: JobApplication) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{NOTION_API_BASE}/pages",
                headers=self._headers,
                json=self._build_page_payload(app),
            )
            resp.raise_for_status()
            page_id: str = resp.json()["id"]
            logger.info("Created Notion page %s for %s @ %s", page_id, app.job_title, app.company_name)
            return page_id

    async def _update_page(self, page_id: str, app: JobApplication) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{NOTION_API_BASE}/pages/{page_id}",
                headers=self._headers,
                json={"properties": self._build_properties(app)},
            )
            resp.raise_for_status()
            logger.info("Updated Notion page %s", page_id)

    def _build_page_payload(self, app: JobApplication) -> dict[str, Any]:
        return {
            "parent": {"database_id": self._db_id},
            "properties": self._build_properties(app),
        }

    def _build_properties(self, app: JobApplication) -> dict[str, Any]:
        props: dict[str, Any] = {
            "Company": {"title": [{"text": {"content": app.company_name}}]},
            "Job Title": {"rich_text": [{"text": {"content": app.job_title}}]},
            "Status": {"select": {"name": app.status.value}},
        }
        if app.date_applied:
            props["Date Applied"] = {"date": {"start": app.date_applied.isoformat()}}
        if app.next_action:
            props["Next Action"] = {"rich_text": [{"text": {"content": app.next_action}}]}
        if app.recruiter_name:
            props["Recruiter"] = {"rich_text": [{"text": {"content": app.recruiter_name}}]}
        if app.salary_range:
            props["Salary Range"] = {"rich_text": [{"text": {"content": app.salary_range}}]}
        if app.source_email_id:
            props["Email ID"] = {"rich_text": [{"text": {"content": app.source_email_id}}]}
        return props


_notion_client: NotionClient | None = None

_PLACEHOLDERS = {"secret_...", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "", "secret_"}


def is_notion_configured() -> bool:
    token = os.environ.get("NOTION_TOKEN", "")
    db_id = os.environ.get("NOTION_DATABASE_ID", "")
    return token not in _PLACEHOLDERS and db_id not in _PLACEHOLDERS


def get_notion_client() -> NotionClient:
    global _notion_client
    if _notion_client is None:
        _notion_client = NotionClient()
    return _notion_client
