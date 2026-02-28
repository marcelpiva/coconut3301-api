import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from firebase_admin import auth as fb_auth

from ..auth import verify_token, _get_firebase_app
from ..database import get_pool

router = APIRouter()


@router.get("/leaderboard/{puzzle_id}")
async def get_leaderboard(puzzle_id: str):
    """Public — no auth required."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT uid, display_name, solve_time, attempts, hints_used, submitted_at
        FROM leaderboard_entries
        WHERE puzzle_id = $1
        ORDER BY solve_time ASC
        LIMIT 50
        """,
        puzzle_id,
    )

    entries = [
        {
            "uid": row["uid"],
            "displayName": row["display_name"],
            "solveTime": row["solve_time"],
            "attempts": row["attempts"],
            "hintsUsed": row["hints_used"],
            "timestamp": row["submitted_at"] or "",
        }
        for row in rows
    ]

    return entries


@router.post("/leaderboard/{puzzle_id}")
async def post_leaderboard(puzzle_id: str, request: Request):
    uid = await verify_token(request)
    if not uid:
        return Response(
            content=json.dumps({"error": "Unauthorized"}),
            status_code=401,
            media_type="application/json",
        )

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()

    pool = await get_pool()

    # Only update if new solve time is better (or first submission)
    existing = await pool.fetchrow(
        """
        SELECT solve_time FROM leaderboard_entries
        WHERE puzzle_id = $1 AND uid = $2
        """,
        puzzle_id,
        uid,
    )

    if existing and existing["solve_time"] <= body.get("solveTime", 0):
        return {"status": "ok"}

    await pool.execute(
        """
        INSERT INTO leaderboard_entries (puzzle_id, uid, display_name, solve_time, attempts, hints_used, submitted_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (puzzle_id, uid) DO UPDATE SET
            display_name = $3,
            solve_time = $4,
            attempts = $5,
            hints_used = $6,
            submitted_at = $7
        """,
        puzzle_id,
        uid,
        body.get("displayName", "Anonymous"),
        body.get("solveTime", 0),
        body.get("attempts", 0),
        body.get("hintsUsed", 0),
        now,
    )

    return {"status": "ok"}


@router.post("/leaderboard-seed")
async def seed_leaderboard():
    """One-time endpoint: populate leaderboard from existing user_progress data."""
    _get_firebase_app()
    pool = await get_pool()

    rows = await pool.fetch("SELECT uid, data FROM user_progress")
    inserted = 0
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        uid = row["uid"]
        data = row["data"]
        if isinstance(data, str):
            data = json.loads(data)

        solved = data.get("solvedPuzzles", [])
        solve_times = data.get("solveTimes", {})
        attempts_map = data.get("attempts", {})
        hints_map = data.get("hintsUsed", {})

        if not solved:
            continue

        # Look up display name from Firebase Auth
        try:
            user = fb_auth.get_user(uid)
            display_name = user.display_name or "Anonymous"
        except Exception:
            display_name = "Anonymous"

        for puzzle_id in solved:
            solve_time = solve_times.get(puzzle_id, 0)
            if solve_time <= 0:
                continue

            await pool.execute(
                """
                INSERT INTO leaderboard_entries (puzzle_id, uid, display_name, solve_time, attempts, hints_used, submitted_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (puzzle_id, uid) DO NOTHING
                """,
                puzzle_id,
                uid,
                display_name,
                solve_time,
                attempts_map.get(puzzle_id, 0),
                hints_map.get(puzzle_id, 0),
                now,
            )
            inserted += 1

    return {"status": "ok", "inserted": inserted, "users_processed": len(rows)}
