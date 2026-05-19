"""
Shared fixtures for job-tracker-agent tests.

Adds backend/ to sys.path and seeds required environment variables before
any application module is imported, so module-level code (DATABASE_URL,
SYSTEM_PROMPT file read) does not crash.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ── path setup ───────────────────────────────────────────────────────────────
BACKEND = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

# ── env vars (must be set before importing main/extractor) ───────────────────
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/testdb")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("NOTION_TOKEN", "")
os.environ.setdefault("NOTION_DATABASE_ID", "")
os.environ.setdefault("NOTION_REVIEW_PAGE_ID", "test-review-page-id")

# ── import app after env vars are set ────────────────────────────────────────
from main import app  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_mock_conn(fetch_return=None):
    """Return an AsyncMock connection with configurable fetch result."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    return conn


def _make_mock_pool(conn):
    """Wrap a mock connection in an asyncpg-style pool mock."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)
    pool.close = AsyncMock()
    return pool


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_conn():
    """A bare mock asyncpg connection (fetch returns [])."""
    return _make_mock_conn()


@pytest.fixture()
def client(mock_conn):
    """
    FastAPI TestClient with the DB pool replaced by a mock.
    Yields (TestClient, mock_conn) so tests can configure fetch return values.
    """
    pool = _make_mock_pool(mock_conn)
    with patch("asyncpg.create_pool", AsyncMock(return_value=pool)):
        with TestClient(app) as c:
            yield c, mock_conn
