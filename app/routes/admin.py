"""
Admin CRUD endpoints — protected by Firebase auth + role verification.

Supports CRUD for seasons, stages, puzzles, reveals, and app config.
All mutations are logged to admin_audit_log.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response

from ..auth import verify_admin
from ..database import get_pool

router = APIRouter()

ROLES_EDITOR_PLUS = {"editor", "admin", "super_admin"}
ROLES_ADMIN_PLUS = {"admin", "super_admin"}
ROLES_SUPER_ADMIN = {"super_admin"}


def _unauthorized():
    return Response(
        content=json.dumps({"error": "Unauthorized"}),
        status_code=401,
        media_type="application/json",
    )


def _forbidden():
    return Response(
        content=json.dumps({"error": "Forbidden"}),
        status_code=403,
        media_type="application/json",
    )


def _not_found(entity: str):
    return Response(
        content=json.dumps({"error": f"{entity} not found"}),
        status_code=404,
        media_type="application/json",
    )


async def _audit_log(
    admin: dict,
    action: str,
    target_type: str,
    target_id: str,
    before: dict | None = None,
    after: dict | None = None,
):
    pool = await get_pool()
    now = datetime.now(timezone.utc).isoformat()
    await pool.execute(
        """
        INSERT INTO admin_audit_log
            (action, target_type, target_id, admin_uid, admin_email, before_data, after_data, timestamp)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        action,
        target_type,
        target_id,
        admin["uid"],
        admin["email"],
        json.dumps(before) if before else None,
        json.dumps(after) if after else None,
        now,
    )


# ═══════════════════════════════════════════════════════════════════════════
# SEASONS
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/admin/seasons")
async def list_seasons(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    pool = await get_pool()
    rows = await pool.fetch('SELECT * FROM seasons ORDER BY "order" ASC')

    return [
        {
            "id": r["id"],
            "order": r["order"],
            "stageIds": r["stage_ids"] or [],
            "requiredSeasonId": r["required_season_id"],
            "unlockDate": r["unlock_date"],
            "translations": r["translations"] if isinstance(r["translations"], dict) else json.loads(r["translations"]),
            "isActive": r["is_active"],
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        }
        for r in rows
    ]


@router.post("/admin/seasons")
async def create_season(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()
    pool = await get_pool()

    await pool.execute(
        """
        INSERT INTO seasons (id, "order", stage_ids, required_season_id, unlock_date,
                             translations, is_active, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        body["id"],
        body["order"],
        body.get("stageIds", []),
        body.get("requiredSeasonId"),
        body.get("unlockDate"),
        json.dumps(body.get("translations", {})),
        body.get("isActive", True),
        now,
        now,
    )

    await _audit_log(admin, "create", "season", body["id"], after=body)
    return {"success": True}


@router.put("/admin/seasons/{season_id}")
async def update_season(season_id: str, request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    pool = await get_pool()
    existing = await pool.fetchrow("SELECT * FROM seasons WHERE id = $1", season_id)
    if not existing:
        return _not_found("Season")

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()

    await pool.execute(
        """
        UPDATE seasons SET "order" = $2, stage_ids = $3, required_season_id = $4,
            unlock_date = $5, translations = $6, is_active = $7, updated_at = $8
        WHERE id = $1
        """,
        season_id,
        body.get("order", existing["order"]),
        body.get("stageIds", existing["stage_ids"]),
        body.get("requiredSeasonId", existing["required_season_id"]),
        body.get("unlockDate", existing["unlock_date"]),
        json.dumps(body.get("translations", existing["translations"])),
        body.get("isActive", existing["is_active"]),
        now,
    )

    await _audit_log(admin, "update", "season", season_id, before=dict(existing), after=body)
    return {"success": True}


@router.delete("/admin/seasons/{season_id}")
async def delete_season(season_id: str, request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_SUPER_ADMIN:
        return _forbidden()

    pool = await get_pool()
    existing = await pool.fetchrow("SELECT * FROM seasons WHERE id = $1", season_id)
    if not existing:
        return _not_found("Season")

    await pool.execute("DELETE FROM seasons WHERE id = $1", season_id)
    await _audit_log(admin, "delete", "season", season_id, before=dict(existing))
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════
# STAGES
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/admin/stages")
async def list_stages(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    pool = await get_pool()
    rows = await pool.fetch('SELECT * FROM stages ORDER BY "order" ASC')

    return [
        {
            "id": r["id"],
            "seasonId": r["season_id"],
            "order": r["order"],
            "requiredPuzzles": r["required_puzzles"],
            "puzzleIds": r["puzzle_ids"] or [],
            "translations": r["translations"] if isinstance(r["translations"], dict) else json.loads(r["translations"]),
            "isActive": r["is_active"],
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        }
        for r in rows
    ]


@router.post("/admin/stages")
async def create_stage(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()
    pool = await get_pool()

    await pool.execute(
        """
        INSERT INTO stages (id, season_id, "order", required_puzzles, puzzle_ids,
                            translations, is_active, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        body["id"],
        body.get("seasonId", "season_1"),
        body["order"],
        body.get("requiredPuzzles", 0),
        body.get("puzzleIds", []),
        json.dumps(body.get("translations", {})),
        body.get("isActive", True),
        now,
        now,
    )

    await _audit_log(admin, "create", "stage", body["id"], after=body)
    return {"success": True}


@router.put("/admin/stages/{stage_id}")
async def update_stage(stage_id: str, request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    pool = await get_pool()
    existing = await pool.fetchrow("SELECT * FROM stages WHERE id = $1", stage_id)
    if not existing:
        return _not_found("Stage")

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()

    await pool.execute(
        """
        UPDATE stages SET season_id = $2, "order" = $3, required_puzzles = $4,
            puzzle_ids = $5, translations = $6, is_active = $7, updated_at = $8
        WHERE id = $1
        """,
        stage_id,
        body.get("seasonId", existing["season_id"]),
        body.get("order", existing["order"]),
        body.get("requiredPuzzles", existing["required_puzzles"]),
        body.get("puzzleIds", existing["puzzle_ids"]),
        json.dumps(body.get("translations", existing["translations"])),
        body.get("isActive", existing["is_active"]),
        now,
    )

    await _audit_log(admin, "update", "stage", stage_id, before=dict(existing), after=body)
    return {"success": True}


@router.delete("/admin/stages/{stage_id}")
async def delete_stage(stage_id: str, request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_SUPER_ADMIN:
        return _forbidden()

    pool = await get_pool()
    existing = await pool.fetchrow("SELECT * FROM stages WHERE id = $1", stage_id)
    if not existing:
        return _not_found("Stage")

    await pool.execute("DELETE FROM stages WHERE id = $1", stage_id)
    await _audit_log(admin, "delete", "stage", stage_id, before=dict(existing))
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════
# PUZZLES
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/admin/puzzles")
async def list_puzzles(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    pool = await get_pool()
    rows = await pool.fetch('SELECT * FROM puzzles ORDER BY stage_id, "order" ASC')

    return [
        {
            "id": r["id"],
            "type": r["type"],
            "stageId": r["stage_id"],
            "order": r["order"],
            "translations": r["translations"] if isinstance(r["translations"], dict) else json.loads(r["translations"]),
            "isActive": r["is_active"],
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
            "createdBy": r["created_by"],
            "updatedBy": r["updated_by"],
            "version": r["version"],
        }
        for r in rows
    ]


@router.post("/admin/puzzles")
async def create_puzzle(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()
    pool = await get_pool()

    await pool.execute(
        """
        INSERT INTO puzzles (id, type, stage_id, "order", translations, is_active,
                             created_at, updated_at, created_by, updated_by, version)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        body["id"],
        body["type"],
        body["stageId"],
        body["order"],
        json.dumps(body.get("translations", {})),
        body.get("isActive", True),
        now,
        now,
        admin["email"],
        admin["email"],
        1,
    )

    await _audit_log(admin, "create", "puzzle", body["id"], after=body)
    return {"success": True}


@router.put("/admin/puzzles/{puzzle_id}")
async def update_puzzle(puzzle_id: str, request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    pool = await get_pool()
    existing = await pool.fetchrow("SELECT * FROM puzzles WHERE id = $1", puzzle_id)
    if not existing:
        return _not_found("Puzzle")

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()

    await pool.execute(
        """
        UPDATE puzzles SET type = $2, stage_id = $3, "order" = $4, translations = $5,
            is_active = $6, updated_at = $7, updated_by = $8, version = $9
        WHERE id = $1
        """,
        puzzle_id,
        body.get("type", existing["type"]),
        body.get("stageId", existing["stage_id"]),
        body.get("order", existing["order"]),
        json.dumps(body.get("translations", existing["translations"])),
        body.get("isActive", existing["is_active"]),
        now,
        admin["email"],
        (existing["version"] or 0) + 1,
    )

    await _audit_log(admin, "update", "puzzle", puzzle_id, before=dict(existing), after=body)
    return {"success": True}


@router.delete("/admin/puzzles/{puzzle_id}")
async def delete_puzzle(puzzle_id: str, request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_SUPER_ADMIN:
        return _forbidden()

    pool = await get_pool()
    existing = await pool.fetchrow("SELECT * FROM puzzles WHERE id = $1", puzzle_id)
    if not existing:
        return _not_found("Puzzle")

    await pool.execute("DELETE FROM puzzles WHERE id = $1", puzzle_id)
    await _audit_log(admin, "delete", "puzzle", puzzle_id, before=dict(existing))
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════
# REVEALS
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/admin/reveals")
async def list_reveals(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM reveals ORDER BY puzzle_id")

    return [
        {
            "puzzleId": r["puzzle_id"],
            "loreUnlock": r["lore_unlock"],
            "translations": r["translations"] if isinstance(r["translations"], dict) else json.loads(r["translations"]),
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        }
        for r in rows
    ]


@router.post("/admin/reveals")
async def upsert_reveal(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()
    pool = await get_pool()

    existing = await pool.fetchrow(
        "SELECT * FROM reveals WHERE puzzle_id = $1", body["puzzleId"]
    )

    if existing:
        await pool.execute(
            """
            UPDATE reveals SET lore_unlock = $2, translations = $3, updated_at = $4
            WHERE puzzle_id = $1
            """,
            body["puzzleId"],
            body.get("loreUnlock"),
            json.dumps(body.get("translations", {})),
            now,
        )
        await _audit_log(
            admin, "update", "reveal", body["puzzleId"],
            before=dict(existing), after=body,
        )
    else:
        await pool.execute(
            """
            INSERT INTO reveals (puzzle_id, lore_unlock, translations, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            """,
            body["puzzleId"],
            body.get("loreUnlock"),
            json.dumps(body.get("translations", {})),
            now,
            now,
        )
        await _audit_log(admin, "create", "reveal", body["puzzleId"], after=body)

    return {"success": True}


@router.put("/admin/reveals/{puzzle_id}")
async def update_reveal(puzzle_id: str, request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    pool = await get_pool()
    existing = await pool.fetchrow("SELECT * FROM reveals WHERE puzzle_id = $1", puzzle_id)
    if not existing:
        return _not_found("Reveal")

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()

    await pool.execute(
        """
        UPDATE reveals SET lore_unlock = $2, translations = $3, updated_at = $4
        WHERE puzzle_id = $1
        """,
        puzzle_id,
        body.get("loreUnlock", existing["lore_unlock"]),
        json.dumps(body.get("translations", existing["translations"])),
        now,
    )

    await _audit_log(admin, "update", "reveal", puzzle_id, before=dict(existing), after=body)
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════
# APP CONFIG
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/admin/config")
async def get_config(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_ADMIN_PLUS:
        return _unauthorized()

    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM app_config WHERE key = 'main'")
    if not row:
        return {"puzzleSource": "remote", "maintenanceMode": False, "minAppVersion": "1.0.0"}

    return {
        "puzzleSource": row["puzzle_source"],
        "maintenanceMode": row["maintenance_mode"],
        "minAppVersion": row["min_app_version"],
    }


@router.put("/admin/config")
async def update_config(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_ADMIN_PLUS:
        return _unauthorized()

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()
    pool = await get_pool()

    existing = await pool.fetchrow("SELECT * FROM app_config WHERE key = 'main'")

    if existing:
        await pool.execute(
            """
            UPDATE app_config SET puzzle_source = $1, maintenance_mode = $2,
                min_app_version = $3, updated_at = $4
            WHERE key = 'main'
            """,
            body.get("puzzleSource", existing["puzzle_source"]),
            body.get("maintenanceMode", existing["maintenance_mode"]),
            body.get("minAppVersion", existing["min_app_version"]),
            now,
        )
    else:
        await pool.execute(
            """
            INSERT INTO app_config (key, puzzle_source, maintenance_mode, min_app_version, updated_at)
            VALUES ('main', $1, $2, $3, $4)
            """,
            body.get("puzzleSource", "remote"),
            body.get("maintenanceMode", False),
            body.get("minAppVersion", "1.0.0"),
            now,
        )

    await _audit_log(
        admin, "update", "app_config", "main",
        before=dict(existing) if existing else None,
        after=body,
    )
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════
# GLOSSARY
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/admin/glossary")
async def list_glossary(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    pool = await get_pool()
    rows = await pool.fetch('SELECT * FROM glossary ORDER BY "order" ASC')

    return [
        {
            "id": r["id"],
            "order": r["order"],
            "isActive": r["is_active"],
            "translations": r["translations"] if isinstance(r["translations"], dict) else json.loads(r["translations"]),
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        }
        for r in rows
    ]


@router.post("/admin/glossary")
async def create_glossary_entry(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()
    pool = await get_pool()

    await pool.execute(
        """
        INSERT INTO glossary (id, "order", is_active, translations, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        body["id"],
        body.get("order", 0),
        body.get("isActive", True),
        json.dumps(body.get("translations", {})),
        now,
        now,
    )

    await _audit_log(admin, "create", "glossary", body["id"], after=body)
    return {"success": True}


@router.put("/admin/glossary/{entry_id}")
async def update_glossary_entry(entry_id: str, request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    pool = await get_pool()
    existing = await pool.fetchrow("SELECT * FROM glossary WHERE id = $1", entry_id)
    if not existing:
        return _not_found("Glossary entry")

    body = await request.json()
    now = datetime.now(timezone.utc).isoformat()

    await pool.execute(
        """
        UPDATE glossary SET "order" = $2, is_active = $3, translations = $4, updated_at = $5
        WHERE id = $1
        """,
        entry_id,
        body.get("order", existing["order"]),
        body.get("isActive", existing["is_active"]),
        json.dumps(body.get("translations", existing["translations"])),
        now,
    )

    await _audit_log(admin, "update", "glossary", entry_id, before=dict(existing), after=body)
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════
# TTS FILES
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/admin/tts-files")
async def list_tts_files(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_EDITOR_PLUS:
        return _unauthorized()

    locale = request.query_params.get("locale")
    pool = await get_pool()

    if locale:
        rows = await pool.fetch(
            "SELECT * FROM tts_files WHERE locale = $1 ORDER BY narration_id",
            locale,
        )
    else:
        rows = await pool.fetch("SELECT * FROM tts_files ORDER BY locale, narration_id")

    return [
        {
            "id": r["id"],
            "narrationId": r["narration_id"],
            "locale": r["locale"],
            "type": r["type"],
            "durationSecs": r["duration_secs"],
            "createdAt": r["created_at"],
        }
        for r in rows
    ]


@router.post("/admin/tts-files/sync")
async def sync_tts_files(request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_ADMIN_PLUS:
        return _unauthorized()

    body = await request.json()
    files = body.get("files", [])

    if not files:
        return {"success": True, "upserted": 0}

    pool = await get_pool()
    now = datetime.now(timezone.utc).isoformat()
    upserted = 0

    for f in files:
        await pool.execute(
            """
            INSERT INTO tts_files (narration_id, locale, type, duration_secs, created_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (narration_id, locale) DO UPDATE
            SET type = $3, duration_secs = $4
            """,
            f["narrationId"],
            f["locale"],
            f.get("type", "unknown"),
            f.get("durationSecs"),
            now,
        )
        upserted += 1

    await _audit_log(
        admin, "sync", "tts_files", f"bulk_{len(files)}",
        after={"count": len(files), "locale": files[0]["locale"] if files else None},
    )

    return {"success": True, "upserted": upserted}


@router.delete("/admin/glossary/{entry_id}")
async def delete_glossary_entry(entry_id: str, request: Request):
    admin = await verify_admin(request)
    if not admin or admin["role"] not in ROLES_SUPER_ADMIN:
        return _forbidden()

    pool = await get_pool()
    existing = await pool.fetchrow("SELECT * FROM glossary WHERE id = $1", entry_id)
    if not existing:
        return _not_found("Glossary entry")

    await pool.execute("DELETE FROM glossary WHERE id = $1", entry_id)
    await _audit_log(admin, "delete", "glossary", entry_id, before=dict(existing))
    return {"success": True}
