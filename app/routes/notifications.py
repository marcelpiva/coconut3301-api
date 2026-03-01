import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response

from ..auth import verify_admin, verify_token
from ..database import get_pool
from ..services.notification_sender import send_to_all, send_to_user

router = APIRouter()


@router.post("/fcm-token")
async def register_fcm_token(request: Request):
    """Register or update an FCM token for the authenticated user."""
    uid = await verify_token(request)
    if not uid:
        return Response(
            content=json.dumps({"error": "Unauthorized"}),
            status_code=401,
            media_type="application/json",
        )

    body = await request.json()
    token = body.get("token")
    if not token:
        return Response(
            content=json.dumps({"error": "Missing token"}),
            status_code=400,
            media_type="application/json",
        )

    platform = body.get("platform", "android")
    locale = body.get("locale", "en")
    now = datetime.now(timezone.utc).isoformat()

    pool = await get_pool()

    # Upsert: if token already exists (same device), update uid/platform/locale
    await pool.execute(
        """
        INSERT INTO fcm_tokens (uid, token, platform, locale, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $5)
        ON CONFLICT (token)
        DO UPDATE SET uid = $1, platform = $3, locale = $4, updated_at = $5
        """,
        uid,
        token,
        platform,
        locale,
        now,
    )

    return {"status": "ok"}


@router.delete("/fcm-token")
async def remove_fcm_token(request: Request):
    """Remove an FCM token on logout."""
    uid = await verify_token(request)
    if not uid:
        return Response(
            content=json.dumps({"error": "Unauthorized"}),
            status_code=401,
            media_type="application/json",
        )

    body = await request.json()
    token = body.get("token")
    if not token:
        return Response(
            content=json.dumps({"error": "Missing token"}),
            status_code=400,
            media_type="application/json",
        )

    pool = await get_pool()
    await pool.execute(
        "DELETE FROM fcm_tokens WHERE uid = $1 AND token = $2",
        uid,
        token,
    )

    return {"status": "ok"}


@router.get("/notification-preferences")
async def get_notification_preferences(request: Request):
    """Get notification preferences for the authenticated user."""
    uid = await verify_token(request)
    if not uid:
        return Response(
            content=json.dumps({"error": "Unauthorized"}),
            status_code=401,
            media_type="application/json",
        )

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM notification_preferences WHERE uid = $1", uid
    )

    if not row:
        # Return defaults
        return {
            "gameReminders": True,
            "progressUpdates": True,
            "competition": True,
            "inactivity": True,
            "newContent": True,
        }

    return {
        "gameReminders": row["game_reminders"],
        "progressUpdates": row["progress_updates"],
        "competition": row["competition"],
        "inactivity": row["inactivity"],
        "newContent": row["new_content"],
    }


@router.put("/notification-preferences")
async def put_notification_preferences(request: Request):
    """Update notification preferences for the authenticated user."""
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
        INSERT INTO notification_preferences (uid, game_reminders, progress_updates, competition, inactivity, new_content)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (uid)
        DO UPDATE SET
            game_reminders = $2,
            progress_updates = $3,
            competition = $4,
            inactivity = $5,
            new_content = $6
        """,
        uid,
        body.get("gameReminders", True),
        body.get("progressUpdates", True),
        body.get("competition", True),
        body.get("inactivity", True),
        body.get("newContent", True),
    )

    return {"status": "ok"}


@router.post("/admin/push")
async def admin_send_push(request: Request):
    """Send a push notification (admin only).

    Body:
      - title: notification title
      - body: notification body
      - uid: (optional) target a single user; omit to broadcast to all
      - data: (optional) extra data payload (e.g. {"route": "/stages"})
      - category: (optional) preference category (default: "broadcast")
    """
    admin = await verify_admin(request)
    if not admin:
        return Response(
            content=json.dumps({"error": "Forbidden"}),
            status_code=403,
            media_type="application/json",
        )

    body = await request.json()
    title = body.get("title")
    msg_body = body.get("body")
    if not title or not msg_body:
        return Response(
            content=json.dumps({"error": "Missing title or body"}),
            status_code=400,
            media_type="application/json",
        )

    uid = body.get("uid")
    data = body.get("data")
    category = body.get("category", "broadcast")

    if uid:
        sent = await send_to_user(
            uid=uid, title=title, body=msg_body, data=data, category=category
        )
    else:
        sent = await send_to_all(
            title=title, body=msg_body, data=data, category=category
        )

    return {"status": "ok", "sent": sent}


@router.get("/admin/push/log")
async def admin_push_log(request: Request):
    """Get recent notification log (admin only)."""
    admin = await verify_admin(request)
    if not admin:
        return Response(
            content=json.dumps({"error": "Forbidden"}),
            status_code=403,
            media_type="application/json",
        )

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, uid, type, title, body, sent_at, status
        FROM notification_log
        ORDER BY sent_at DESC
        LIMIT 50
        """
    )

    return [
        {
            "id": r["id"],
            "uid": r["uid"],
            "type": r["type"],
            "title": r["title"],
            "body": r["body"],
            "sentAt": r["sent_at"],
            "status": r["status"],
        }
        for r in rows
    ]


# ─── Campaign CRUD ──────────────────────────────────────────


@router.post("/admin/campaigns")
async def create_campaign(request: Request):
    """Create a scheduled notification campaign (admin only)."""
    admin = await verify_admin(request)
    if not admin:
        return Response(
            content=json.dumps({"error": "Forbidden"}),
            status_code=403,
            media_type="application/json",
        )

    body = await request.json()
    title = body.get("title")
    msg_body = body.get("body")
    scheduled_at = body.get("scheduledAt")
    if not title or not msg_body or not scheduled_at:
        return Response(
            content=json.dumps({"error": "Missing title, body, or scheduledAt"}),
            status_code=400,
            media_type="application/json",
        )

    now = datetime.now(timezone.utc).isoformat()
    pool = await get_pool()

    row = await pool.fetchrow(
        """
        INSERT INTO notification_campaigns
            (name, title, body, data, category, target_filter, scheduled_at, status, created_by, created_at)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, 'scheduled', $8, $9)
        RETURNING id
        """,
        body.get("name", title),
        title,
        msg_body,
        json.dumps(body.get("data")) if body.get("data") else None,
        body.get("category", "broadcast"),
        body.get("targetFilter", "all"),
        scheduled_at,
        admin["uid"],
        now,
    )

    return {"status": "ok", "id": row["id"]}


@router.get("/admin/campaigns")
async def list_campaigns(request: Request):
    """List notification campaigns (admin only)."""
    admin = await verify_admin(request)
    if not admin:
        return Response(
            content=json.dumps({"error": "Forbidden"}),
            status_code=403,
            media_type="application/json",
        )

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, name, title, body, category, target_filter,
               scheduled_at, sent_at, sent_count, status, created_by, created_at
        FROM notification_campaigns
        ORDER BY created_at DESC
        LIMIT 50
        """
    )

    return [
        {
            "id": r["id"],
            "name": r["name"],
            "title": r["title"],
            "body": r["body"],
            "category": r["category"],
            "targetFilter": r["target_filter"],
            "scheduledAt": r["scheduled_at"],
            "sentAt": r["sent_at"],
            "sentCount": r["sent_count"],
            "status": r["status"],
            "createdBy": r["created_by"],
            "createdAt": r["created_at"],
        }
        for r in rows
    ]


@router.delete("/admin/campaigns/{campaign_id}")
async def cancel_campaign(request: Request, campaign_id: int):
    """Cancel a scheduled campaign (admin only)."""
    admin = await verify_admin(request)
    if not admin:
        return Response(
            content=json.dumps({"error": "Forbidden"}),
            status_code=403,
            media_type="application/json",
        )

    pool = await get_pool()
    result = await pool.execute(
        """
        UPDATE notification_campaigns SET status = 'cancelled'
        WHERE id = $1 AND status = 'scheduled'
        """,
        campaign_id,
    )

    if result == "UPDATE 0":
        return Response(
            content=json.dumps({"error": "Campaign not found or not cancellable"}),
            status_code=404,
            media_type="application/json",
        )

    return {"status": "ok"}
