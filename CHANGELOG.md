# Changelog

## 1.1.0 — 2026-03-02

### Fixed
- Soft auth on listing endpoints (seasons, season content, glossary) — no longer returns 401 for unauthenticated requests
- Null-safe JSON field serialization (`dict.get("key") or ""` instead of `dict.get("key", "")`)
- Auth-aware cache headers: `private, no-store` for authenticated responses, `public` with `Vary: Authorization` for public responses

### Changed
- Content security model: listing endpoints use soft auth (per-user unlocks when token present, date-based fallback otherwise); hints and reveals require hard auth (401)
- Hard auth kept only on spoiler-sensitive endpoints (`/content/hint`, `/content/reveal`)

## 1.0.0 — 2026-02-28

### Added
- User progress sync with server-side merge (union sets, max counters, min solve times)
- First-solve-only leaderboard with top 50 rankings per puzzle
- Leaderboard displacement notifications (top 3 alerts)
- Public content API: seasons, stages, puzzles, reveals, glossary, app config
- Admin CRUD for all content entities with audit logging
- TTS file management endpoints
- Firebase ID token + session cookie authentication
- Role-based admin access (editor, admin, super_admin)
- FCM token registration and management
- User notification preferences (7 categories)
- Push notification sending (single user and broadcast)
- Scheduled notification campaigns with CRUD
- Notification delivery log
- asyncpg connection pool (PostgreSQL)
- Docker + Railway deployment config
- Health check endpoint
