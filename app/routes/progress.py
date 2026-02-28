import json

from fastapi import APIRouter, Request, Response

from ..auth import verify_token
from ..database import get_pool

router = APIRouter()


@router.get("/progress")
async def get_progress(request: Request):
    uid = await verify_token(request)
    if not uid:
        return Response(
            content=json.dumps({"error": "Unauthorized"}),
            status_code=401,
            media_type="application/json",
        )

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT data FROM user_progress WHERE uid = $1", uid
    )

    if not row:
        return Response(content="null", media_type="application/json")

    # row["data"] is already a JSON string from asyncpg (jsonb column)
    return Response(content=json.dumps(row["data"]), media_type="application/json")


@router.put("/progress")
async def put_progress(request: Request):
    uid = await verify_token(request)
    if not uid:
        return Response(
            content=json.dumps({"error": "Unauthorized"}),
            status_code=401,
            media_type="application/json",
        )

    body = await request.json()

    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO user_progress (uid, data)
        VALUES ($1, $2::jsonb)
        ON CONFLICT (uid) DO UPDATE SET data = $2::jsonb
        """,
        uid,
        json.dumps(body),
    )

    return {"status": "ok"}
