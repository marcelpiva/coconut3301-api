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
    except Exception:
        return None
