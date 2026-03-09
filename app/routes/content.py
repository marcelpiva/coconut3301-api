"""
Public content endpoints — serves puzzle/stage/season/reveal data to the Flutter app.

Responses match the exact JSON shape that the app's fromJson() factories expect,
so no changes needed on the client parsing side.

Security: sensitive puzzle data (shift, key, method) is stripped from responses.
Hints and reveals are served via separate on-demand endpoints.
"""

import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import verify_token
from ..database import get_pool
from ..limiter import limiter

router = APIRouter()

CACHE_HEADERS_PUBLIC = {"Cache-Control": "public, max-age=60"}
CACHE_HEADERS_PRIVATE = {"Cache-Control": "private, no-store"}


_UNAUTHORIZED = Response(content='{"error":"Unauthorized"}', status_code=401, media_type="application/json")


async def _soft_auth(request: Request) -> str | None:
    """Verify Firebase token but don't block — returns uid or None.

    Used for listing endpoints (seasons, season content, glossary) where
    content is already stripped of sensitive data. When uid is available,
    per-user unlocks are applied; otherwise falls back to date-based unlocks.
    """
    uid = await verify_token(request)
    auth_header = request.headers.get("Authorization", "")
    has_bearer = auth_header.startswith("Bearer ") if auth_header else False
    if not uid and has_bearer:
        print(f"[AUTH] {request.url.path} token provided but invalid")
    return uid


async def _require_auth(request: Request) -> str | None:
    """Verify Firebase token — hard requirement for spoiler-sensitive endpoints.

    Used for hints and reveals where content is a spoiler.
    Returns uid or None (caller should return 401 if None).
    """
    uid = await verify_token(request)
    auth_header = request.headers.get("Authorization", "")
    has_bearer = auth_header.startswith("Bearer ") if auth_header else False
    print(f"[AUTH] {request.url.path} has_bearer={has_bearer} uid={uid}")
    return uid


async def _get_user_unlocked_seasons(pool, uid: str) -> set:
    """Fetch the set of season IDs this user has unlocked (from user_progress)."""
    row = await pool.fetchrow("SELECT data FROM user_progress WHERE uid = $1", uid)
    if not row or not row["data"]:
        return {"season_1"}
    data = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
    return set(data.get("unlockedSeasons", ["season_1"]))


def _is_season_accessible(unlock_date_str: str | None, season_id: str, user_seasons: set) -> bool:
    """Check if a season is accessible: date unlocked OR user has individual unlock."""
    if _is_date_unlocked(unlock_date_str):
        return True
    return season_id in user_seasons


# Keys in puzzle `data` that reveal the solution — stripped from public responses.
_SENSITIVE_DATA_KEYS = {"shift", "key", "alphabet", "answer", "solution", "plaintext"}


def _strip_sensitive_data(data: dict) -> dict:
    """Return a copy of puzzle data with solution-revealing keys removed."""
    return {k: v for k, v in data.items() if k not in _SENSITIVE_DATA_KEYS}


def _is_date_unlocked(unlock_date_str: str | None) -> bool:
    """Check if a season's unlock_date has passed (or doesn't exist)."""
    if not unlock_date_str:
        return True
    try:
        unlock_dt = datetime.fromisoformat(unlock_date_str.replace("Z", "+00:00"))
        if unlock_dt.tzinfo is None:
            unlock_dt = unlock_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= unlock_dt
    except (ValueError, TypeError):
        return True


async def _is_puzzle_accessible(pool, puzzle_id: str, user_seasons: set | None = None) -> bool:
    """Check if a puzzle belongs to an accessible season (date-unlocked or user-unlocked)."""
    row = await pool.fetchrow(
        """
        SELECT s.id AS season_id, s.unlock_date
        FROM puzzles p
        JOIN stages st ON p.stage_id = st.id
        JOIN seasons s ON st.season_id = s.id
        WHERE p.id = $1 AND p.is_active = true
        """,
        puzzle_id,
    )
    if not row:
        return False
    if _is_date_unlocked(row["unlock_date"]):
        return True
    if user_seasons and row["season_id"] in user_seasons:
        return True
    return False


def _extract_translation(translations: dict | str | None, locale: str) -> dict:
    """Extract a locale's translation from the JSONB field, falling back to English."""
    if translations is None:
        return {}
    if isinstance(translations, str):
        translations = json.loads(translations)
    return translations.get(locale) or translations.get("en") or {}


@router.get("/content/series")
@limiter.limit("60/minute")
async def get_series(request: Request, locale: str = "en"):
    """Return all active series."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, "order", translations, is_active, cover_image
        FROM series
        WHERE is_active = true
        ORDER BY "order" ASC
        """
    )

    result = []
    for row in rows:
        t = _extract_translation(row["translations"], locale)
        result.append({
            "id": row["id"],
            "name": t.get("name") or "",
            "subtitle": t.get("subtitle") or "",
            "description": t.get("description") or "",
            "synopsis": t.get("synopsis") or "",
            "order": row["order"],
            "coverImage": row["cover_image"],
        })

    return Response(
        content=json.dumps({"series": result}),
        media_type="application/json",
        headers=CACHE_HEADERS_PUBLIC,
    )


@router.get("/content/series/{series_id}/seasons")
@limiter.limit("60/minute")
async def get_series_seasons(request: Request, series_id: str, locale: str = "en"):
    """Return all active seasons for a specific series."""
    uid = await _soft_auth(request)
    pool = await get_pool()

    user_seasons = await _get_user_unlocked_seasons(pool, uid) if uid else {"season_1"}

    rows = await pool.fetch(
        """
        SELECT id, "order", stage_ids, required_season_id, unlock_date,
               translations, is_active
        FROM seasons
        WHERE is_active = true AND series_id = $1
        ORDER BY "order" ASC
        """,
        series_id,
    )

    seasons = []
    for row in rows:
        t = _extract_translation(row["translations"], locale)
        accessible = _is_season_accessible(row["unlock_date"], row["id"], user_seasons)

        if accessible:
            seasons.append({
                "id": row["id"],
                "name": t.get("name") or "",
                "subtitle": t.get("subtitle") or "",
                "description": t.get("description") or "",
                "order": row["order"],
                "stageIds": row["stage_ids"] or [],
                "requiredSeasonId": row["required_season_id"],
                "unlockDate": row["unlock_date"],
                "preview": t.get("preview"),
                "seriesId": series_id,
            })
        else:
            seasons.append({
                "id": row["id"],
                "name": t.get("name") or "",
                "subtitle": t.get("subtitle") or "",
                "description": "",
                "order": row["order"],
                "stageIds": [],
                "requiredSeasonId": row["required_season_id"],
                "unlockDate": row["unlock_date"],
                "preview": t.get("preview"),
                "seriesId": series_id,
            })

    cache = CACHE_HEADERS_PRIVATE if uid else CACHE_HEADERS_PUBLIC
    return Response(
        content=json.dumps({"seasons": seasons}),
        media_type="application/json",
        headers=cache,
    )


@router.get("/content/seasons")
@limiter.limit("60/minute")
async def get_seasons(request: Request, locale: str = "en"):
    """Return all active seasons in the same format as seasons_{locale}.json."""
    uid = await _soft_auth(request)
    pool = await get_pool()

    user_seasons = await _get_user_unlocked_seasons(pool, uid) if uid else {"season_1"}

    rows = await pool.fetch(
        """
        SELECT id, series_id, "order", stage_ids, required_season_id, unlock_date,
               translations, is_active
        FROM seasons
        WHERE is_active = true
        ORDER BY "order" ASC
        """
    )

    seasons = []
    for row in rows:
        t = _extract_translation(row["translations"], locale)
        accessible = _is_season_accessible(row["unlock_date"], row["id"], user_seasons)

        if accessible:
            seasons.append({
                "id": row["id"],
                "seriesId": row["series_id"],
                "name": t.get("name") or "",
                "subtitle": t.get("subtitle") or "",
                "description": t.get("description") or "",
                "order": row["order"],
                "stageIds": row["stage_ids"] or [],
                "requiredSeasonId": row["required_season_id"],
                "unlockDate": row["unlock_date"],
                "preview": t.get("preview"),
            })
        else:
            # Locked season: minimal metadata only, no content references
            seasons.append({
                "id": row["id"],
                "seriesId": row["series_id"],
                "name": t.get("name") or "",
                "subtitle": t.get("subtitle") or "",
                "description": "",
                "order": row["order"],
                "stageIds": [],
                "requiredSeasonId": row["required_season_id"],
                "unlockDate": row["unlock_date"],
                "preview": t.get("preview"),
            })

    cache = CACHE_HEADERS_PRIVATE if uid else CACHE_HEADERS_PUBLIC
    return Response(
        content=json.dumps({"seasons": seasons}),
        media_type="application/json",
        headers=cache,
    )


@router.get("/content/season/{season_id}")
@limiter.limit("60/minute")
async def get_season_content(request: Request, season_id: str, locale: str = "en"):
    """Return a season's content (stages + puzzles).

    Security: puzzle data is stripped of solution-revealing keys (shift, key, method).
    Hints are replaced with hintCount; reveals are not included (use separate endpoints).
    Locked seasons (unlock_date in the future) return 403.
    """
    uid = await _soft_auth(request)
    pool = await get_pool()

    user_seasons = await _get_user_unlocked_seasons(pool, uid) if uid else {"season_1"}

    # Check if season is accessible (date-unlocked or user-unlocked)
    season_row = await pool.fetchrow(
        "SELECT unlock_date FROM seasons WHERE id = $1 AND is_active = true",
        season_id,
    )
    if season_row and not _is_season_accessible(season_row["unlock_date"], season_id, user_seasons):
        return Response(
            content=json.dumps({"error": "Season not yet available"}),
            status_code=403,
            media_type="application/json",
        )

    # 1. Get stages for this season
    stage_rows = await pool.fetch(
        """
        SELECT id, season_id, "order", required_puzzles, puzzle_ids, translations
        FROM stages
        WHERE season_id = $1 AND is_active = true
        ORDER BY "order" ASC
        """,
        season_id,
    )

    stages = []
    all_stage_ids = []
    for row in stage_rows:
        t = _extract_translation(row["translations"], locale)
        all_stage_ids.append(row["id"])
        stages.append({
            "id": row["id"],
            "name": t.get("name") or "",
            "subtitle": t.get("subtitle") or "",
            "description": t.get("description") or "",
            "order": row["order"],
            "requiredPuzzles": row["required_puzzles"] or 0,
            "puzzleIds": row["puzzle_ids"] or [],
            "seasonId": row["season_id"],
        })

    # 2. Get puzzles for those stages — strip sensitive data
    puzzle_rows = await pool.fetch(
        """
        SELECT id, type, stage_id, "order", translations
        FROM puzzles
        WHERE stage_id = ANY($1) AND is_active = true
        ORDER BY stage_id, "order" ASC
        """,
        all_stage_ids,
    )

    puzzles = []
    for row in puzzle_rows:
        t = _extract_translation(row["translations"], locale)
        raw_data = t.get("data") or {}
        hints = t.get("hints") or []

        puzzles.append({
            "id": row["id"],
            "title": t.get("title") or "",
            "description": t.get("description") or "",
            "type": row["type"],
            "stageId": row["stage_id"],
            "order": row["order"],
            "data": _strip_sensitive_data(raw_data),
            "hints": [],
            "hintCount": len(hints),
        })

    # Reveals are NOT included — fetched on demand via /content/reveal/{puzzle_id}

    cache = CACHE_HEADERS_PRIVATE if uid else CACHE_HEADERS_PUBLIC
    return Response(
        content=json.dumps({
            "stages": stages,
            "puzzles": puzzles,
        }),
        media_type="application/json",
        headers=cache,
    )


@router.get("/content/glossary")
@limiter.limit("60/minute")
async def get_glossary(request: Request, locale: str = "en"):
    """Return all active glossary entries with translations flattened for the locale."""
    await _soft_auth(request)  # log auth status but don't block
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, "order", translations
        FROM glossary
        WHERE is_active = true
        ORDER BY "order" ASC
        """
    )

    entries = []
    for row in rows:
        t = _extract_translation(row["translations"], locale)
        if not t.get("term"):
            continue
        entries.append({
            "id": row["id"],
            "order": row["order"],
            "term": t.get("term") or "",
            "aliases": t.get("aliases") or [],
            "summary": t.get("summary") or "",
            "history": t.get("history") or "",
            "howItWorks": t.get("howItWorks") or "",
            "analogy": t.get("analogy") or "",
            "examples": t.get("examples") or [],
            "relatedTerms": t.get("relatedTerms") or [],
        })

    return Response(
        content=json.dumps({"entries": entries}),
        media_type="application/json",
        headers=CACHE_HEADERS_PUBLIC,
    )


@router.get("/content/config")
async def get_config():
    """Return app configuration."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT puzzle_source, maintenance_mode, min_app_version
        FROM app_config
        WHERE key = 'main'
        """
    )

    if not row:
        return {
            "puzzleSource": "remote",
            "maintenanceMode": False,
            "minAppVersion": "1.0.0",
        }

    return Response(
        content=json.dumps({
            "puzzleSource": row["puzzle_source"],
            "maintenanceMode": row["maintenance_mode"],
            "minAppVersion": row["min_app_version"],
        }),
        media_type="application/json",
        headers=CACHE_HEADERS_PUBLIC,
    )


# ---------------------------------------------------------------------------
# Hints — on-demand, one at a time
# ---------------------------------------------------------------------------


@router.get("/content/hint/{puzzle_id}/{hint_index}")
@limiter.limit("10/minute")
async def get_hint(request: Request, puzzle_id: str, hint_index: int, locale: str = "en"):
    """Return a single hint for a puzzle by index (0-based)."""
    uid = await _require_auth(request)
    if not uid:
        return _UNAUTHORIZED
    pool = await get_pool()

    user_seasons = await _get_user_unlocked_seasons(pool, uid)
    if not await _is_puzzle_accessible(pool, puzzle_id, user_seasons):
        return Response(
            content=json.dumps({"error": "Season not yet available"}),
            status_code=403,
            media_type="application/json",
        )

    row = await pool.fetchrow(
        "SELECT translations FROM puzzles WHERE id = $1 AND is_active = true",
        puzzle_id,
    )
    if not row:
        return Response(
            content='{"error":"Puzzle not found"}',
            status_code=404,
            media_type="application/json",
        )

    t = _extract_translation(row["translations"], locale)
    hints = t.get("hints") or []

    if hint_index < 0 or hint_index >= len(hints):
        return Response(
            content='{"error":"Hint index out of range"}',
            status_code=404,
            media_type="application/json",
        )

    return Response(
        content=json.dumps({"hint": hints[hint_index]}),
        media_type="application/json",
        headers=CACHE_HEADERS_PRIVATE,
    )


# ---------------------------------------------------------------------------
# Reveals — on-demand, after puzzle is solved
# ---------------------------------------------------------------------------


@router.get("/content/reveal/{puzzle_id}")
@limiter.limit("10/minute")
async def get_reveal(request: Request, puzzle_id: str, locale: str = "en"):
    """Return reveal data for a solved puzzle."""
    uid = await _require_auth(request)
    if not uid:
        return _UNAUTHORIZED
    pool = await get_pool()

    user_seasons = await _get_user_unlocked_seasons(pool, uid)
    if not await _is_puzzle_accessible(pool, puzzle_id, user_seasons):
        return Response(
            content=json.dumps({"error": "Season not yet available"}),
            status_code=403,
            media_type="application/json",
        )

    row = await pool.fetchrow(
        "SELECT puzzle_id, lore_unlock, translations FROM reveals WHERE puzzle_id = $1",
        puzzle_id,
    )
    if not row:
        return Response(
            content='{"error":"Reveal not found"}',
            status_code=404,
            media_type="application/json",
        )

    t = _extract_translation(row["translations"], locale)
    return Response(
        content=json.dumps({
            "puzzleId": row["puzzle_id"],
            "title": t.get("title") or "",
            "classification": t.get("classification") or "",
            "body": t.get("body") or "",
            "loreUnlock": row["lore_unlock"],
        }),
        media_type="application/json",
        headers=CACHE_HEADERS_PRIVATE,
    )


# ---------------------------------------------------------------------------
# Answer verification — server-side check
# ---------------------------------------------------------------------------


class VerifyAnswerRequest(BaseModel):
    puzzleId: str
    answerHash: str
    locale: str = "en"


@router.post("/content/verify-answer")
@limiter.limit("30/minute")
async def verify_answer(request: Request, body: VerifyAnswerRequest):
    """Verify a puzzle answer hash against the stored hash."""
    uid = await _soft_auth(request)
    pool = await get_pool()

    user_seasons = await _get_user_unlocked_seasons(pool, uid) if uid else {"season_1"}
    if not await _is_puzzle_accessible(pool, body.puzzleId, user_seasons):
        return Response(
            content=json.dumps({"error": "Season not yet available"}),
            status_code=403,
            media_type="application/json",
        )

    row = await pool.fetchrow(
        "SELECT translations FROM puzzles WHERE id = $1 AND is_active = true",
        body.puzzleId,
    )
    if not row:
        return Response(
            content=json.dumps({"correct": False}),
            media_type="application/json",
        )

    t = _extract_translation(row["translations"], body.locale)
    stored_hash = t.get("answerHash", "")

    return Response(
        content=json.dumps({"correct": body.answerHash == stored_hash}),
        media_type="application/json",
    )


# ---------------------------------------------------------------------------
# TTS Audio CDN — authenticated on-demand delivery
# ---------------------------------------------------------------------------

@router.get("/cdn/data/tts/{locale}/{narration_id}")
async def get_tts_audio(locale: str, narration_id: str, request: Request):
    """Serve TTS audio files. Requires Firebase auth."""
    uid = await verify_token(request)
    if not uid:
        return Response(
            content='{"error":"Unauthorized"}',
            status_code=401,
            media_type="application/json",
        )

    # Sanitize path components
    safe_locale = locale.replace("/", "").replace("..", "")
    safe_id = narration_id.replace("/", "").replace("..", "").removesuffix(".mp3")
    path = f"static/data/tts/{safe_locale}/{safe_id}.mp3"

    if not os.path.isfile(path):
        return Response(
            content='{"error":"Not found"}',
            status_code=404,
            media_type="application/json",
        )

    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ---------------------------------------------------------------------------
# Content version — allows app to detect when content has been updated
# ---------------------------------------------------------------------------

@router.get("/content/version")
async def get_content_version():
    """Return a content version hash so the app can detect updates."""
    try:
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT COALESCE(
                GREATEST(
                    (SELECT MAX(updated_at) FROM seasons),
                    (SELECT MAX(updated_at) FROM stages),
                    (SELECT MAX(updated_at) FROM puzzles)
                ),
                NOW()
            )::text AS version
            """
        )
        base_version = row["version"] if row else "unknown"

        unlock_row = await pool.fetchrow(
            """
            SELECT COUNT(*) AS unlocked
            FROM seasons
            WHERE is_active = true
              AND (unlock_date IS NULL OR unlock_date <= NOW())
            """
        )
        unlocked_count = unlock_row["unlocked"] if unlock_row else 0
        version = f"{base_version}|u{unlocked_count}"
    except Exception as e:
        print(f"[VERSION] Error: {e}")
        version = "error"

    return Response(
        content=json.dumps({"version": version}),
        media_type="application/json",
        headers={"Cache-Control": "no-cache"},
    )
