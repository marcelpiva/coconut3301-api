# Coconut 3301 API

FastAPI backend for the Coconut 3301 puzzle app. Handles user progress sync, leaderboard, content delivery, push notifications, and admin operations.

## Endpoints

### Public Content (`/api/v1/content`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/content/seasons` | GET | List active seasons with translations (locale param) |
| `/content/season/{season_id}` | GET | Full season content (stages + puzzles + reveals) |
| `/content/glossary` | GET | Glossary entries with translations |
| `/content/config` | GET | App config (puzzle source, maintenance mode, min version) |

### User Progress (`/api/v1/progress`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/progress` | GET | Firebase | Fetch user progress |
| `/progress` | PUT | Firebase | Sync progress (server-side merge) |

Server-side merge logic: union for sets (solvedPuzzles, achievements), max for counters (hints, attempts), min for solve times.

### Leaderboard (`/api/v1/leaderboard`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/leaderboard/{puzzle_id}` | GET | No | Top 50 solvers for a puzzle |
| `/leaderboard/{puzzle_id}` | POST | Firebase | Submit first solve (one-time only) |

### Notifications (`/api/v1`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/fcm-token` | POST | Firebase | Register FCM token |
| `/fcm-token` | DELETE | Firebase | Remove FCM token |
| `/notification-preferences` | GET | Firebase | Get notification preferences |
| `/notification-preferences` | PUT | Firebase | Update notification preferences |

### Admin (`/api/v1/admin`)

All admin endpoints require Firebase token + role verification (editor/admin/super_admin). All mutations logged to `admin_audit_log`.

| Resource | Methods | Description |
|----------|---------|-------------|
| `/admin/seasons` | GET, POST, PUT, DELETE | Season CRUD |
| `/admin/stages` | GET, POST, PUT, DELETE | Stage CRUD |
| `/admin/puzzles` | GET, POST, PUT, DELETE | Puzzle CRUD |
| `/admin/reveals` | GET, POST, PUT | Reveal upsert |
| `/admin/config` | GET, PUT | App config |
| `/admin/glossary` | GET, POST, PUT, DELETE | Glossary CRUD |
| `/admin/tts-files` | GET, POST (sync) | TTS file tracking |
| `/admin/push` | POST | Send push notification |
| `/admin/push/log` | GET | Notification history |
| `/admin/campaigns` | GET, POST, DELETE | Scheduled campaigns |

## Auth

- **Firebase ID tokens** (Bearer header) — for Flutter app
- **Session cookies** (X-Session-Cookie header) — for admin panel
- **Role-based access**: editor, admin, super_admin (stored in `admin_users` table)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI |
| Server | Uvicorn (ASGI) |
| Database | PostgreSQL (asyncpg) |
| Auth | Firebase Admin SDK |
| Notifications | Firebase Cloud Messaging (FCM) |

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL
- Firebase project

### Setup

```bash
cd coconut3301-api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Configure DATABASE_URL and FIREBASE_SERVICE_ACCOUNT_KEY
uvicorn app.main:app --reload
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `FIREBASE_SERVICE_ACCOUNT_KEY` | Firebase service account JSON |

## Deploy

Deployed on Railway via Docker.

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Health check at `/health`.

## Project Structure

```
app/
├── main.py                    # FastAPI app + router config
├── auth.py                    # Firebase auth + role verification
├── database.py                # asyncpg connection pool
├── routes/
│   ├── progress.py            # GET/PUT /progress
│   ├── leaderboard.py         # Leaderboard endpoints
│   ├── content.py             # Public content (seasons, glossary, config)
│   ├── admin.py               # Admin CRUD (all entities + audit log)
│   └── notifications.py       # FCM tokens, preferences, campaigns
└── services/
    └── notification_sender.py # FCM push delivery + preference gating
```
