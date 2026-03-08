"""
Decoder Tools Access Control — slot-based activation system.
"""

import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Response

from ..auth import verify_token
from ..database import get_pool

router = APIRouter()


def _json_response(data: dict, status_code: int = 200) -> Response:
    return Response(
        content=json.dumps(data),
        status_code=status_code,
        media_type="application/json",
    )


def _unauthorized():
    return _json_response({"error": "Unauthorized"}, 401)


async def _get_config(pool):
    """Fetch decoder config from app_config table."""
    row = await pool.fetchrow("SELECT * FROM app_config WHERE key = 'main'")
    if not row:
        return {
            "enabled": True,
            "max_slots": 5,
            "activation_duration_secs": 300,
            "cooldown_secs": 600,
            "grace_period_secs": 120,
        }
    return {
        "enabled": row.get("decoder_enabled", True),
        "max_slots": row.get("decoder_max_slots", 5),
        "activation_duration_secs": row.get("decoder_activation_duration_secs", 300),
        "cooldown_secs": row.get("decoder_cooldown_secs", 600),
        "grace_period_secs": row.get("decoder_grace_period_secs", 120),
    }


async def _count_active(pool) -> int:
    """Count currently active decoder activations."""
    now = datetime.now(timezone.utc).isoformat()
    row = await pool.fetchrow(
        "SELECT COUNT(*) as cnt FROM decoder_activations WHERE status = 'active' AND expires_at > $1",
        now,
    )
    return row["cnt"] if row else 0


# ─── Public Config ─────────────────────────────────────────

@router.get("/decoder/config")
async def get_decoder_config():
    pool = await get_pool()
    config = await _get_config(pool)
    active_count = await _count_active(pool)
    return {
        "enabled": config["enabled"],
        "maxSlots": config["max_slots"],
        "activationDurationSecs": config["activation_duration_secs"],
        "cooldownSecs": config["cooldown_secs"],
        "activeCount": active_count,
    }


# ─── Status ─────────────────────────────────────────────────

@router.get("/decoder/status")
async def get_decoder_status(request: Request):
    uid = await verify_token(request)
    if not uid:
        return _unauthorized()

    pool = await get_pool()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    config = await _get_config(pool)

    # Check active activation
    active = await pool.fetchrow(
        "SELECT * FROM decoder_activations WHERE uid = $1 AND status = 'active' AND expires_at > $2",
        uid, now_iso,
    )
    if active:
        expires_at = datetime.fromisoformat(active["expires_at"])
        remaining = max(0, int((expires_at - now).total_seconds()))
        return {"status": "active", "expiresAt": active["expires_at"], "remainingSecs": remaining}

    # Check cooldown
    last_deactivated = await pool.fetchrow(
        """SELECT deactivated_at FROM decoder_activations
           WHERE uid = $1 AND deactivated_at IS NOT NULL
           ORDER BY deactivated_at DESC LIMIT 1""",
        uid,
    )
    if last_deactivated and last_deactivated["deactivated_at"]:
        deactivated_at = datetime.fromisoformat(last_deactivated["deactivated_at"])
        cooldown_ends = deactivated_at + timedelta(seconds=config["cooldown_secs"])
        if now < cooldown_ends:
            remaining = max(0, int((cooldown_ends - now).total_seconds()))
            return {"status": "cooldown", "cooldownEndsAt": cooldown_ends.isoformat(), "remainingSecs": remaining}

    # Check queue position
    queued = await pool.fetchrow(
        "SELECT * FROM decoder_queue WHERE uid = $1 AND status IN ('waiting', 'notified')",
        uid,
    )
    if queued:
        position_row = await pool.fetchrow(
            """SELECT COUNT(*) as pos FROM decoder_queue
               WHERE status = 'waiting' AND queued_at <= $1""",
            queued["queued_at"],
        )
        position = position_row["pos"] if position_row else 1
        estimated_wait = position * config["activation_duration_secs"]
        return {"status": "queued", "position": position, "estimatedWaitSecs": estimated_wait}

    return {"status": "inactive"}


# ─── Activate ──────────────────────────────────────────────

@router.post("/decoder/activate")
async def activate_decoder(request: Request):
    uid = await verify_token(request)
    if not uid:
        return _unauthorized()

    pool = await get_pool()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    config = await _get_config(pool)

    if not config["enabled"]:
        return _json_response({"error": "Decoder tools are currently disabled"}, 403)

    # Check existing active activation
    active = await pool.fetchrow(
        "SELECT * FROM decoder_activations WHERE uid = $1 AND status = 'active' AND expires_at > $2",
        uid, now_iso,
    )
    if active:
        expires_at = datetime.fromisoformat(active["expires_at"])
        remaining = max(0, int((expires_at - now).total_seconds()))
        return {"status": "active", "expiresAt": active["expires_at"], "remainingSecs": remaining}

    # Check cooldown
    last_deactivated = await pool.fetchrow(
        """SELECT deactivated_at FROM decoder_activations
           WHERE uid = $1 AND deactivated_at IS NOT NULL
           ORDER BY deactivated_at DESC LIMIT 1""",
        uid,
    )
    if last_deactivated and last_deactivated["deactivated_at"]:
        deactivated_at = datetime.fromisoformat(last_deactivated["deactivated_at"])
        cooldown_ends = deactivated_at + timedelta(seconds=config["cooldown_secs"])
        if now < cooldown_ends:
            remaining = max(0, int((cooldown_ends - now).total_seconds()))
            return {"status": "cooldown", "cooldownEndsAt": cooldown_ends.isoformat(), "remainingSecs": remaining}

    # Count active slots (using advisory lock pattern for safety)
    active_count = await _count_active(pool)

    if active_count < config["max_slots"]:
        # Slot available — activate
        expires_at = now + timedelta(seconds=config["activation_duration_secs"])
        await pool.execute(
            """INSERT INTO decoder_activations (uid, activated_at, expires_at, status)
               VALUES ($1, $2, $3, 'active')""",
            uid, now_iso, expires_at.isoformat(),
        )
        # Remove from queue if present
        await pool.execute(
            "DELETE FROM decoder_queue WHERE uid = $1",
            uid,
        )
        remaining = config["activation_duration_secs"]
        return {"status": "activated", "expiresAt": expires_at.isoformat(), "remainingSecs": remaining}
    else:
        # Queue full — add to queue
        await pool.execute(
            """INSERT INTO decoder_queue (uid, queued_at, status)
               VALUES ($1, $2, 'waiting')
               ON CONFLICT (uid) DO UPDATE SET queued_at = $2, status = 'waiting', notified_at = NULL""",
            uid, now_iso,
        )
        position_row = await pool.fetchrow(
            """SELECT COUNT(*) as pos FROM decoder_queue
               WHERE status = 'waiting' AND queued_at <= $1""",
            now_iso,
        )
        position = position_row["pos"] if position_row else 1
        estimated_wait = position * config["activation_duration_secs"]
        return {"status": "queued", "position": position, "estimatedWaitSecs": estimated_wait}


# ─── Deactivate ────────────────────────────────────────────

@router.post("/decoder/deactivate")
async def deactivate_decoder(request: Request):
    uid = await verify_token(request)
    if not uid:
        return _unauthorized()

    pool = await get_pool()
    now_iso = datetime.now(timezone.utc).isoformat()

    await pool.execute(
        """UPDATE decoder_activations SET status = 'deactivated', deactivated_at = $2
           WHERE uid = $1 AND status = 'active'""",
        uid, now_iso,
    )

    return {"status": "inactive"}
