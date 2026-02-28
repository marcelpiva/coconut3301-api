import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response

from ..auth import verify_token
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

    # Only accept first submission — prevents leaderboard manipulation
    existing = await pool.fetchrow(
        """
        SELECT 1 FROM leaderboard_entries
        WHERE puzzle_id = $1 AND uid = $2
        """,
        puzzle_id,
        uid,
    )

    if existing:
        return {"status": "ok"}

    await pool.execute(
        """
        INSERT INTO leaderboard_entries (puzzle_id, uid, display_name, solve_time, attempts, hints_used, submitted_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (puzzle_id, uid) DO NOTHING
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
