import json
from datetime import datetime, timezone

from firebase_admin import messaging

from ..auth import _get_firebase_app
from ..database import get_pool


async def send_to_user(
    uid: str,
    title: str,
    body: str,
    data: dict | None = None,
    category: str = "general",
) -> int:
    """Send a push notification to all devices of a specific user.

    Returns the number of successfully sent messages.
    """
    _get_firebase_app()
    pool = await get_pool()

    # Check user preferences
    prefs = await pool.fetchrow(
        "SELECT * FROM notification_preferences WHERE uid = $1", uid
    )
    if prefs and not _should_send(prefs, category):
        return 0

    # Get all FCM tokens for this user
    rows = await pool.fetch(
        "SELECT id, token FROM fcm_tokens WHERE uid = $1", uid
    )
    if not rows:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    sent_count = 0
    invalid_token_ids: list[int] = []

    for row in rows:
        token = row["token"]
        try:
            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=data or {},
                token=token,
            )
            messaging.send(message)
            sent_count += 1
        except messaging.UnregisteredError:
            invalid_token_ids.append(row["id"])
        except messaging.SenderIdMismatchError:
            invalid_token_ids.append(row["id"])
        except Exception as e:
            print(f"[FCM] Failed to send to {uid}: {e}")

    # Remove invalid tokens
    if invalid_token_ids:
        await pool.execute(
            "DELETE FROM fcm_tokens WHERE id = ANY($1::int[])",
            invalid_token_ids,
        )

    # Log the notification
    await pool.execute(
        """
        INSERT INTO notification_log (uid, type, title, body, data, sent_at, status)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
        """,
        uid,
        category,
        title,
        body,
        json.dumps(data) if data else None,
        now,
        "sent" if sent_count > 0 else "no_tokens",
    )

    return sent_count


async def send_to_all(
    title: str,
    body: str,
    data: dict | None = None,
    category: str = "broadcast",
) -> int:
    """Send a push notification to all registered users.

    Returns the number of successfully sent messages.
    """
    _get_firebase_app()
    pool = await get_pool()
    now = datetime.now(timezone.utc).isoformat()

    # Get all unique UIDs with tokens
    uid_rows = await pool.fetch(
        "SELECT DISTINCT uid FROM fcm_tokens"
    )

    total_sent = 0
    for uid_row in uid_rows:
        count = await send_to_user(
            uid=uid_row["uid"],
            title=title,
            body=body,
            data=data,
            category=category,
        )
        total_sent += count

    return total_sent


def _should_send(prefs: dict, category: str) -> bool:
    """Check if user preferences allow this notification category."""
    category_map = {
        "game_reminder": "game_reminders",
        "progress": "progress_updates",
        "competition": "competition",
        "inactivity": "inactivity",
        "new_content": "new_content",
        "broadcast": None,  # Always send broadcasts
        "general": None,
    }
    pref_key = category_map.get(category)
    if pref_key is None:
        return True  # No preference gate for this category
    return prefs.get(pref_key, True)
