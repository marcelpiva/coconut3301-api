"""
Public content endpoints — serves puzzle/stage/season/reveal data to the Flutter app.

Responses match the exact JSON shape that the app's fromJson() factories expect,
so no changes needed on the client parsing side.
"""

import json

from fastapi import APIRouter, Response

from ..database import get_pool

router = APIRouter()

CACHE_HEADERS = {"Cache-Control": "public, max-age=300"}


def _extract_translation(translations: dict | str | None, locale: str) -> dict:
    """Extract a locale's translation from the JSONB field, falling back to English."""
    if translations is None:
        return {}
    if isinstance(translations, str):
        translations = json.loads(translations)
    return translations.get(locale) or translations.get("en") or {}


@router.get("/content/seasons")
async def get_seasons(locale: str = "en"):
    """Return all active seasons in the same format as seasons_{locale}.json."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, "order", stage_ids, required_season_id, unlock_date,
               translations, is_active
        FROM seasons
        WHERE is_active = true
        ORDER BY "order" ASC
        """
    )

    seasons = []
    for row in rows:
        t = _extract_translation(row["translations"], locale)
        seasons.append({
            "id": row["id"],
            "name": t.get("name", ""),
            "subtitle": t.get("subtitle", ""),
            "description": t.get("description", ""),
            "order": row["order"],
            "stageIds": row["stage_ids"] or [],
            "requiredSeasonId": row["required_season_id"],
            "unlockDate": row["unlock_date"],
            "preview": t.get("preview"),
        })

    return Response(
        content=json.dumps({"seasons": seasons}),
        media_type="application/json",
        headers=CACHE_HEADERS,
    )


@router.get("/content/season/{season_id}")
async def get_season_content(season_id: str, locale: str = "en"):
    """Return a season's full content (stages + puzzles + reveals).

    Response shape matches puzzles_{locale}.json / season_N_{locale}.json.
    """
    pool = await get_pool()

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
            "name": t.get("name", ""),
            "subtitle": t.get("subtitle", ""),
            "description": t.get("description", ""),
            "order": row["order"],
            "requiredPuzzles": row["required_puzzles"],
            "puzzleIds": row["puzzle_ids"] or [],
            "seasonId": row["season_id"],
        })

    # 2. Get puzzles for those stages
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
    puzzle_ids = []
    for row in puzzle_rows:
        t = _extract_translation(row["translations"], locale)
        puzzle_ids.append(row["id"])
        puzzles.append({
            "id": row["id"],
            "title": t.get("title", ""),
            "description": t.get("description", ""),
            "type": row["type"],
            "stageId": row["stage_id"],
            "order": row["order"],
            "data": t.get("data", {}),
            "answerHash": t.get("answerHash", ""),
            "hints": t.get("hints", []),
        })

    # 3. Get reveals for those puzzles
    reveal_rows = await pool.fetch(
        """
        SELECT puzzle_id, lore_unlock, translations
        FROM reveals
        WHERE puzzle_id = ANY($1)
        """,
        puzzle_ids,
    )

    reveals = []
    for row in reveal_rows:
        t = _extract_translation(row["translations"], locale)
        reveals.append({
            "puzzleId": row["puzzle_id"],
            "title": t.get("title", ""),
            "classification": t.get("classification", ""),
            "body": t.get("body", ""),
            "loreUnlock": row["lore_unlock"],
        })

    return Response(
        content=json.dumps({
            "stages": stages,
            "puzzles": puzzles,
            "reveals": reveals,
        }),
        media_type="application/json",
        headers=CACHE_HEADERS,
    )


@router.get("/content/glossary")
async def get_glossary(locale: str = "en"):
    """Return all active glossary entries with translations flattened for the locale."""
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
            "term": t.get("term", ""),
            "aliases": t.get("aliases", []),
            "summary": t.get("summary", ""),
            "history": t.get("history", ""),
            "howItWorks": t.get("howItWorks", ""),
            "analogy": t.get("analogy", ""),
            "examples": t.get("examples", []),
            "relatedTerms": t.get("relatedTerms", []),
        })

    return Response(
        content=json.dumps({"entries": entries}),
        media_type="application/json",
        headers=CACHE_HEADERS,
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
        headers=CACHE_HEADERS,
    )
