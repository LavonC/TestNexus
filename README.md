# GoaIT — Goa Tech Ecosystem & Autonomous Career Intelligence Platform

A 24/7 web-hosted career intelligence platform monitoring 238+ tech companies, public service commissions (GPSC), and local circulars across Goa, India.

Built specifically to run **100% free forever** on Render's free tier, using **Turso (LibSQL)** cloud database, in-process **APScheduler** background scraping (0 AI tokens spent during ingestion), a **React + Vite + Tailwind** modern web interface, and a **3-tier Q&A chatbot** (User Key → Server Key → Offline DB Grounding).

---

## 🌟 Key Features

1. **Continuous 24/7 Scraping with Zero AI Ingestion Overhead**:
   - In-process **APScheduler** runs every 6 hours, scanning 238+ Goan company websites and careers portals.
   - Zero Playwright / Chromium requirement (pure static `httpx` + `BeautifulSoup` + `feedparser` + `pypdf` text extraction).
   - Keeps RAM consumption under 250MB (safely below Render's 512MB free tier limit).

2. **Turso (LibSQL) Cloud Database Migration**:
   - Replaced ephemeral filesystem SQLite with cloud **Turso / LibSQL** over HTTP/Hrana.
   - Persists state across Render free-tier container restarts and spin-downs.
   - Built-in transparent fallback to local `aiosqlite` for offline execution and fast test suite runs.
   - Full-text search (FTS5) indexes for instant substring and keyword search.

3. **3-Tier AI Career Intelligence Chatbot**:
   - **Tier 1 (User Key)**: Users can supply their personal Google AI Studio Gemini API key (stored securely in browser `localStorage`) for 1,500 free daily requests directly with Google.
   - **Tier 2 (Server Key)**: Rotating server-side Gemini keys with automatic quota backoff and model cascading (`gemini-2.5-flash` → `gemini-3.8-flash` → `gemini-2.5-pro`).
   - **Tier 3 (100% Offline DB Search Fallback)**: If no keys are available or quota is exceeded, answers questions directly from SQLite/Turso FTS5 and LIKE queries.

4. **Public Sector & Government IT Vacancies**:
   - Scrapes Goa Public Service Commission (GPSC), CBES, GEL, and Goa Department of Information Technology circulars.
   - Urgency countdown tracker: Red badge (< 3 days left), Amber badge (< 7 days left).
   - Direct links to official circular PDFs and application forms.

5. **Automated Free-Tier Job Alerts & Feeds**:
   - **Email Alerts**: Instant email alerts via **Resend** (3,000 free emails/month) with 1-click unsubscribe tokens.
   - **Syndication Feeds**: Auto-generated Atom XML Feed (`/api/feed/jobs.xml`) compatible with RSS readers and Slack/Discord webhooks.
   - **Exports**: Instant downloads for Markdown Digest (`digest.md`), JSON Dataset (`digest.json`), Jobs CSV (`jobs.csv`), and Companies CSV (`companies.csv`).

6. **Modern React 18 + Vite + Tailwind Frontend GUI**:
   - **Dashboard**: Real-time KPI metrics, hiring trends chart (Recharts), top hiring companies, and background scan countdown timer.
   - **Companies Directory**: Filter by Goa location (Panaji, Verna, Margao, etc.), tech stack, and hiring status.
   - **Company Profiles**: Detailed company summaries, verified office locations, active openings, and collapsible historical openings archive.
   - **Job Board**: Multi-faceted filterable board (experience level, tech stack, location, Computer Engineering only toggle) with direct apply links and browser bookmarking.
   - **Company Comparison**: Side-by-side comparison matrix of 2-3 employers.
   - **Saved Jobs**: LocalStorage-persisted bookmarks.

---

## 📁 Repository Structure

```
GoaIT/
├── backend/                  # Standalone backend service package for Render
│   ├── src/                  # Application code (FastAPI, database, scrapers)
│   ├── Dockerfile            # Container definition for Render deployment
│   ├── render.yaml           # Backend service blueprint
│   └── requirements.txt      # Production backend dependencies
├── frontend/                 # React 18 + Vite + Tailwind CSS Single Page App
│   ├── src/
│   │   ├── api/client.ts     # Typed API client
│   │   ├── components/       # Navbar, Footer, AlertModal (native <dialog>)
│   │   ├── pages/            # Dashboard, Companies, Jobs, GovtJobs, Chat, Reports, Compare, Saved
│   │   └── types.ts          # Shared TypeScript interfaces
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.ts
├── data/
│   └── companies_seed.json   # 238+ Goan tech, hardware, and engineering companies
├── scripts/
│   └── migrate_to_turso.py   # One-time migration tool (SQLite -> Turso LibSQL)
├── src/                      # Root Python package
│   ├── app.py                # FastAPI entry point, lifespan, CORS, and GZip
│   ├── config.py             # App settings (Turso, Gemini, Resend, Admin)
│   ├── database.py           # Turso LibSQL & aiosqlite hybrid database adapter
│   ├── gemini_agent.py       # 3-tier Q&A agent and structured extraction
│   ├── models.py             # Pydantic data schemas
│   ├── routers/              # API endpoints (stats, companies, jobs, chat, exports, admin)
│   ├── scheduler.py          # APScheduler background worker and email notifications
│   └── scraper.py            # Static HTML, ATS portals, and PDF circular parsing
├── tests/                    # 118 comprehensive unit and integration tests
├── render.yaml               # Root multi-service Render Blueprint (Backend + Frontend)
└── README.md
```

---

## 🚀 Render Deployment (100% Free Tier)

Deploying GoaIT to Render takes less than 5 minutes using the included `render.yaml` Blueprint:

### Step 1: Create a Free Turso Database
1. Go to [turso.tech](https://turso.tech) and create a free account (includes 500 databases and 9GB storage).
2. Create a database:
   ```bash
   turso db create goait
   turso db show goait --url
   turso db tokens create goait
   ```
3. Save the `libsql://...` database URL and authentication token.

### Step 2: One-Time Local Data Migration
Run the bundled migration script to seed your Turso database from the local SQLite dataset:
```bash
python scripts/migrate_to_turso.py \
  --sqlite-db data/goa_companies.db \
  --turso-url "libsql://goait-YOUR-ORG.turso.io" \
  --turso-token "YOUR_TURSO_TOKEN"
```

### Step 3: Deploy via Render Blueprint
1. Push this repository to your GitHub account.
2. In the [Render Dashboard](https://dashboard.render.com), click **New +** → **Blueprint**.
3. Select your repository. Render automatically reads `render.yaml` and provisions:
   - `goait-api`: Python 3.11 web service
   - `goait-frontend`: Static site
4. Fill in the required environment variables:
   - `TURSO_DATABASE_URL`: `libsql://goait-YOUR-ORG.turso.io`
   - `TURSO_AUTH_TOKEN`: Your Turso auth token
   - `GEMINI_API_KEY`: Server-side Gemini key (optional)
   - `FRONTEND_URL`: URL of the `goait-frontend` static site (e.g. `https://goait-frontend.onrender.com`)
   - `ADMIN_SECRET`: Auto-generated secret or custom password
   - `RESEND_API_KEY`: (Optional) Free API key from [resend.com](https://resend.com)
   - `RESEND_FROM_EMAIL`: (Optional) Verified sender email (e.g. `alerts@yourdomain.com` or `onboarding@resend.dev`)
5. Click **Apply**.

### Step 4: Prevent 15-Minute Free-Tier Sleep (Optional)
To keep the backend continuously warm and running its 6-hour scheduler, set up a free HTTP ping on [UptimeRobot](https://uptimerobot.com):
- **URL**: `https://goait-api.onrender.com/api/health`
- **Interval**: Every 10 minutes

---

## 💻 Local Development Setup

### Backend (Python + FastAPI)
```bash
# 1. Clone repository
git clone https://github.com/your-username/GoaIT.git
cd GoaIT

# 2. Set up virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your keys or leave empty for offline mode

# 5. Start development API server
uvicorn src.app:app --reload --port 8000
```
API Documentation will be available at `http://localhost:8000/docs`.

### Frontend (React + Vite + Tailwind)
```bash
cd frontend

# Install dependencies
npm install

# Start Vite dev server with proxy to backend
npm run dev
```
Open `http://localhost:3000` in your browser.

---

## 🧪 Running Tests

The test suite contains **118 comprehensive tests** covering the database adapter, scrapers, FastAPI routers, 3-tier Q&A, and edge cases:

```bash
# Run entire test suite
pytest

# Run FastAPI router tests specifically
pytest tests/test_api.py -v
```

All tests pass 100% offline with zero live network calls or paid API keys required.

---

## 🔒 Security & Admin Endpoints

- All admin triggers (e.g. `/api/admin/scrape`) require the `X-Admin-Secret` HTTP header matching your `ADMIN_SECRET`.
- Read-only SQL queries use strict SQL AST and lexical analysis rejecting non-SELECT or multiple statements.
- User-supplied Gemini API keys are never stored on disk or logged server-side.

---

## 📄 License

MIT License. Designed and maintained for the Goa engineering and technology community.
