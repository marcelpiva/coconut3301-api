import json
import os

import firebase_admin
from firebase_admin import auth, credentials
from fastapi import Request

_app: firebase_admin.App | None = None


def _get_firebase_app() -> firebase_admin.App:
    global _app
    if _app is not None:
        return _app

    service_account_key = os.environ.get("FIREBASE_SERVICE_ACCOUNT_KEY")
    if service_account_key:
        cred = credentials.Certificate(json.loads(service_account_key))
        _app = firebase_admin.initialize_app(cred)
    else:
        _app = firebase_admin.initialize_app()
    return _app


async def verify_token(request: Request) -> str | None:
    """
    Extract and verify a Firebase ID token from the Authorization header.
    Returns the user's UID or None if invalid.
    """
    _get_firebase_app()

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    try:
        decoded = auth.verify_id_token(token)
        return decoded["uid"]
    except Exception as e:
        print(f"[AUTH] Token verification failed: {e}")
        return None


async def verify_admin(request: Request) -> dict | None:
    """Verify Firebase token AND check admin role in admin_users table.

    Returns {"uid": str, "role": str, "email": str} or None.
    """
    uid = await verify_token(request)
    if not uid:
        return None

    from .database import get_pool

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT role, email FROM admin_users WHERE uid = $1", uid
    )
    if not row:
        return None
    return {"uid": uid, "role": row["role"], "email": row["email"]}


async def debug_auth_info(request: Request) -> dict:
    """Debug endpoint to diagnose auth issues."""
    info: dict = {}

    # Check env vars
    info["has_service_account_key"] = bool(
        os.environ.get("FIREBASE_SERVICE_ACCOUNT_KEY")
    )
    info["has_google_cloud_project"] = bool(
        os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")
    )

    # Check Firebase Admin init
    try:
        app = _get_firebase_app()
        info["firebase_initialized"] = True
        info["project_id"] = app.project_id
    except Exception as e:
        info["firebase_initialized"] = False
        info["firebase_error"] = str(e)

    # Try verifying token if provided
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            decoded = auth.verify_id_token(token)
            info["token_valid"] = True
            info["token_uid"] = decoded["uid"]
        except Exception as e:
            info["token_valid"] = False
            info["token_error"] = str(e)
    else:
        info["token_provided"] = False

    return info
