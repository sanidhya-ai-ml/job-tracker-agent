# job-tracker-agent

An AI-powered job application tracker that monitors your Gmail, extracts structured data with **Gemini 2.5 Flash**, persists it to PostgreSQL, optionally syncs to Notion, and delivers a daily Slack digest — all automated via n8n. No manual data entry needed.

## How It Works

```
Gmail ──► n8n (poll every 5 min)
               │
               ▼
        POST /extract  (FastAPI)
               │
               ▼
       Gemini 2.5 Flash (LLM)
        extracts structured JSON
               │
         confidence check
         ├── ≥ 0.7 → PostgreSQL + Notion (if configured)
         └── < 0.7 → Manual Review (Notion page or flag in DB)
               │
        n8n daily cron (8am IST)
               │
               ▼
        GET /stats ──► Slack digest
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Workflow Automation | n8n (self-hosted) |
| LLM Extraction | Gemini 2.5 Flash via OpenAI-compatible endpoint |
| Backend API | FastAPI 0.111 + Python 3.11 + asyncpg |
| Data Models | Pydantic v2 |
| Database | PostgreSQL 16 |
| Notion Sync | Notion API v1 (optional) |
| Notifications | Slack Block Kit (optional) |
| Infrastructure | Docker Compose (multi-stage build) |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/extract` | Extract job data from raw email via Gemini |
| `GET` | `/applications` | List all tracked applications from PostgreSQL |
| `GET` | `/stats` | Funnel counts (applied / interview / offer / rejected) |
| `POST` | `/webhook/n8n` | n8n execution event logger |

## Quick Start

### Prerequisites

- Docker Desktop ≥ 24
- A Gmail account
- Gemini API key — [get one free](https://aistudio.google.com/app/apikey)

### Step 1 — Clone and configure

```bash
git clone https://github.com/sanidhya-ai-ml/job-tracker-agent.git
cd job-tracker-agent
cp .env.example .env
```

Edit `.env` — only `GEMINI_API_KEY` is required to start:

```env
GEMINI_API_KEY=AIza...          # required
NOTION_TOKEN=secret_...         # optional — skip to use DB only
SLACK_BOT_TOKEN=xoxb-...        # optional — skip if no Slack
```

### Step 2 — Start all services

```bash
docker compose up --build -d
```

Services started:
- **PostgreSQL** → `localhost:5432`
- **FastAPI** → `localhost:8000` (Swagger UI at `/docs`)
- **n8n** → `localhost:5678` (login: `admin` / `changeme_in_prod`)

### Step 3 — Import n8n workflows

1. Open [http://localhost:5678](http://localhost:5678)
2. Click **+** → **Workflow** → **Import from file**
3. Import `workflows/job_tracker_main.json`
4. Import `workflows/daily_digest.json`

### Step 4 — Connect Gmail in n8n

1. Open the `job_tracker_main` workflow
2. Click the **Gmail Trigger** node → **Create new credential**
3. You'll need a Google OAuth2 Client ID + Secret:
   - Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
   - Create OAuth 2.0 Client ID (Web application)
   - Add redirect URI: `http://localhost:5678/rest/oauth2-credential/callback`
   - Copy Client ID and Client Secret into n8n
4. Click **Sign in with Google** → authorize with your Gmail account
5. **Save** the workflow → click **Publish** to activate

### Step 5 — Test it

Send yourself a job-related email, wait up to 5 minutes, then check:

```bash
curl http://localhost:8000/applications
```

Or use the Swagger UI at [http://localhost:8000/docs](http://localhost:8000/docs).

## Test via Swagger UI

Open [http://localhost:8000/docs](http://localhost:8000/docs) → **POST /extract** → **Try it out** → paste:

```json
{
  "email_id": "test-001",
  "subject": "Your application to Google - Software Engineer",
  "sender": "recruiting@google.com",
  "body": "Hi Sanidhya, thank you for applying for the Software Engineer role at Google. We will review your application and get back to you within 2 weeks."
}
```

Expected response:
```json
{
  "success": true,
  "application": {
    "company_name": "Google",
    "job_title": "Software Engineer",
    "status": "Applied",
    "confidence": 0.95,
    "next_action": "Wait for further communication within 2 weeks"
  },
  "routed_to_review": false
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | ✅ | Google AI Studio API key |
| `POSTGRES_USER` | ✅ | PostgreSQL username (default: `jobtracker`) |
| `POSTGRES_PASSWORD` | ✅ | PostgreSQL password |
| `POSTGRES_DB` | ✅ | PostgreSQL database name (default: `jobtracker`) |
| `N8N_USER` | ✅ | n8n login username (default: `admin`) |
| `N8N_PASSWORD` | ✅ | n8n login password |
| `NOTION_TOKEN` | optional | Notion integration secret — skipped if placeholder |
| `NOTION_DATABASE_ID` | optional | Notion Job Applications database ID |
| `NOTION_REVIEW_PAGE_ID` | optional | Notion Manual Review page ID |
| `SLACK_BOT_TOKEN` | optional | Slack bot token for daily digest |
| `SLACK_CHANNEL` | optional | Slack channel (e.g. `#job-search`) |
| `N8N_LICENSE_ACTIVATION_KEY` | optional | n8n license key |

## How LLM Extraction Works

The system prompt (`prompts/extract_job_email.txt`) instructs Gemini to extract:

| Field | Description |
|-------|-------------|
| `company_name` | Hiring company name |
| `job_title` | Role/position title |
| `status` | `Applied` / `Interview` / `Offer` / `Rejected` / `needs_review` |
| `date_applied` | ISO date of application or email |
| `next_action` | What to do next |
| `recruiter_name` | Recruiter/contact name |
| `salary_range` | Compensation range if mentioned |
| `confidence` | 0.0–1.0 confidence score |

Emails with `confidence < 0.7` are automatically routed to `needs_review` instead of being auto-logged.

## Daily Slack Digest

The `daily_digest` workflow fires every weekday at 8am IST and sends:

```
📋 Job Search Daily Digest — Fri Apr 25 2026
──────────────────────────────────────────────
📨 Applied    🎤 Interview    🎉 Offer    ❌ Rejected
    42              11            2           18

📊 Response Rate: 30.9%    ✅ Offer Rate: 4.8%
⚠️  3 email(s) need manual review
```

## Project Structure

```
job-tracker-agent/
├── backend/
│   ├── main.py                 # FastAPI app — routes, DB bootstrap, lifespan
│   ├── extractor.py            # Gemini 2.5 Flash structured extraction
│   ├── notion_client.py        # Notion API — optional upsert/review routing
│   ├── models.py               # Pydantic v2 data models
│   ├── Dockerfile              # Multi-stage Python 3.11-slim image
│   └── requirements.txt
├── prompts/
│   └── extract_job_email.txt   # System prompt for email parsing
├── workflows/
│   ├── job_tracker_main.json   # Gmail → /extract → Notion (every 5 min)
│   └── daily_digest.json       # Cron → /stats → Slack (8am IST weekdays)
├── docker-compose.yml
├── .env.example
├── Makefile
└── README.md
```

## Useful Commands

```bash
# Start all services
docker compose up -d

# Rebuild after code changes
docker compose up --build -d

# View logs
docker compose logs -f fastapi

# Stop everything
docker compose down

# Stop and remove volumes (full reset)
docker compose down -v
```

## Author

**Sanidhya Singh** — AI/ML Engineer
[GitHub](https://github.com/sanidhya-ai-ml) · [LinkedIn](https://www.linkedin.com/in/sanidhya-aiml)
