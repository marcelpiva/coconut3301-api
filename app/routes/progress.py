import json

from fastapi import APIRouter, Request, Response

from ..auth import verify_token
from ..database import get_pool

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
