# Changelog

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
