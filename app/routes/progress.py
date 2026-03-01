import asyncio
import json

from fastapi import APIRouter, Request, Response

from ..auth import verify_token
from ..database import get_pool
from ..services.notification_sender import send_to_user

router = APIRouter()


@router.get("/progress")
async def get_progress(request: Request):
    uid = await verify_token(request)
    if not uid:
        # Include debug info for diagnosing auth failures
        from ..auth import _get_firebase_app
        from firebase_admin import auth as fb_auth

        debug_info = {"error": "Unauthorized"}
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                _get_firebase_app()
                fb_auth.verify_id_token(token)
            except Exception as e:
                debug_info["auth_detail"] = str(e)
        else:
            debug_info["auth_detail"] = "No Bearer token in Authorization header"

        return Response(
            content=json.dumps(debug_info),
            status_code=401,
            media_type="application/json",
        )

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT data FROM user_progress WHERE uid = $1", uid
    )

    if not row:
        return Response(content="null", media_type="application/json")

    # asyncpg returns jsonb as a raw JSON string by default (no codec registered)
    data = row["data"]
    if isinstance(data, str):
        return Response(content=data, media_type="application/json")
    return Response(content=json.dumps(data), media_type="application/json")


@router.put("/progress")
async def put_progress(request: Request):
    uid = await verify_token(request)
    if not uid:
        return Response(
            content=json.dumps({"error": "Unauthorized"}),
            status_code=401,
            media_type="application/json",
        )

    incoming = await request.json()

    pool = await get_pool()

    # Fetch existing data so we can merge instead of overwrite
    row = await pool.fetchrow(
        "SELECT data FROM user_progress WHERE uid = $1", uid
    )

    if row and row["data"]:
        existing = row["data"]
        if isinstance(existing, str):
            existing = json.loads(existing)
        merged = _merge_progress(existing, incoming)
    else:
        existing = None
        merged = incoming

    await pool.execute(
        """
        INSERT INTO user_progress (uid, data)
        VALUES ($1, $2::jsonb)
        ON CONFLICT (uid) DO UPDATE SET data = $2::jsonb
        """,
        uid,
        json.dumps(merged),
    )

    # Detect new stage completions (fire-and-forget)
    if existing:
        asyncio.ensure_future(
            _notify_stage_completion(pool, uid, existing, merged)
        )

    return {"status": "ok"}


def _merge_progress(existing: dict, incoming: dict) -> dict:
    """Merge two progress dicts using union/max/min strategies.

    Mirrors the Dart _merge() in progress_provider.dart.
    """
    merged = {}

    # Sets — union (keep all)
    set_fields = [
        "solvedPuzzles",
        "unlockedStages",
        "unlockedSeasons",
        "achievements",
        "unlockedLore",
        "discoveredTools",
    ]
    for field in set_fields:
        a = existing.get(field, [])
        b = incoming.get(field, [])
        merged[field] = list(set(a) | set(b))

    # Maps — max per key (hintsUsed, attempts)
    max_fields = ["hintsUsed", "attempts"]
    for field in max_fields:
        merged[field] = _merge_maps_max(
            existing.get(field, {}), incoming.get(field, {})
        )

    # Maps — min per key (solveTimes — best/fastest time wins)
    min_fields = ["solveTimes"]
    for field in min_fields:
        merged[field] = _merge_maps_min(
            existing.get(field, {}), incoming.get(field, {})
        )

    # Scalars — max
    scalar_max_fields = ["globalCooldownEnd", "globalWrongAttempts"]
    for field in scalar_max_fields:
        merged[field] = max(
            existing.get(field, 0), incoming.get(field, 0)
        )

    # Booleans — OR
    bool_fields = ["introSeen", "tourSeen"]
    for field in bool_fields:
        merged[field] = existing.get(field, False) or incoming.get(field, False)

    # Preserve any extra fields from incoming that we don't explicitly merge
    known_fields = set(set_fields + max_fields + min_fields + scalar_max_fields + bool_fields)
    for key in incoming:
        if key not in known_fields:
            merged[key] = incoming[key]
    # Also preserve extra fields from existing that incoming doesn't have
    for key in existing:
        if key not in known_fields and key not in merged:
            merged[key] = existing[key]

    return merged


def _merge_maps_max(a: dict, b: dict) -> dict:
    """Merge two {str: int} maps keeping the max value per key."""
    result = dict(a)
    for key, val in b.items():
        result[key] = max(result.get(key, 0), val)
    return result


def _merge_maps_min(a: dict, b: dict) -> dict:
    """Merge two {str: int} maps keeping the min value per key."""
    result = dict(a)
    for key, val in b.items():
        if key in result:
            result[key] = min(result[key], val)
        else:
            result[key] = val
    return result


async def _notify_stage_completion(pool, uid: str, before: dict, after: dict):
    """Detect new stage completions and notify the user."""
    try:
        old_stages = set(before.get("unlockedStages", []))
        new_stages = set(after.get("unlockedStages", []))
        newly_unlocked = new_stages - old_stages

        if not newly_unlocked:
            return

        # Newly unlocked stages mean the previous stage was just completed
        for stage_id in newly_unlocked:
            await send_to_user(
                uid=uid,
                title="DOSSIER DECLASSIFIED",
                body="Stage complete. New operations await, recruit.",
                data={"route": "/stages"},
                category="progress",
            )
    except Exception as e:
        print(f"[NOTIFY] Stage completion notification failed: {e}")
