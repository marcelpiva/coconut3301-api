import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .auth import debug_auth_info
from .limiter import limiter
from .database import get_pool, close_pool
from .routes.progress import router as progress_router
from .routes.leaderboard import router as leaderboard_router
from .routes.content import router as content_router
from .routes.admin import router as admin_router
from .routes.notifications import router as notifications_router
from .routes.decoder import router as decoder_router


async def _decoder_queue_loop():
    """Periodic loop: expire activations, process queue, send push notifications."""
    from .database import get_pool
    from .services.notification_sender import send_to_user

    while True:
        try:
            await asyncio.sleep(30)
            pool = await get_pool()
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()

            # 1. Expire active activations past their expiry
            await pool.execute(
                """UPDATE decoder_activations SET status = 'expired', deactivated_at = $1
                   WHERE status = 'active' AND expires_at <= $1""",
                now_iso,
            )

            # 2. Get config for grace period
            config_row = await pool.fetchrow("SELECT * FROM app_config WHERE key = 'main'")
            grace_period = 120
            max_slots = 5
            activation_duration = 300
            if config_row:
                grace_period = config_row.get("decoder_grace_period_secs", 120)
                max_slots = config_row.get("decoder_max_slots", 5)
                activation_duration = config_row.get("decoder_activation_duration_secs", 300)

            # 3. Expire notified users who didn't activate within grace period
            grace_cutoff = (now - timedelta(seconds=grace_period)).isoformat()
            await pool.execute(
                """UPDATE decoder_queue SET status = 'expired'
                   WHERE status = 'notified' AND notified_at IS NOT NULL AND notified_at < $1""",
                grace_cutoff,
            )

            # 4. Count available slots
            active_count_row = await pool.fetchrow(
                "SELECT COUNT(*) as cnt FROM decoder_activations WHERE status = 'active' AND expires_at > $1",
                now_iso,
            )
            active_count = active_count_row["cnt"] if active_count_row else 0
            available_slots = max(0, max_slots - active_count)

            if available_slots > 0:
                # 5. Pop from queue
                waiting = await pool.fetch(
                    """SELECT * FROM decoder_queue
                       WHERE status = 'waiting'
                       ORDER BY queued_at ASC LIMIT $1""",
                    available_slots,
                )

                for entry in waiting:
                    # Send push notification
                    try:
                        await send_to_user(
                            uid=entry["uid"],
                            title="Decoder Tools Ready!",
                            body="Your decoder tools slot is available. Open the app to activate!",
                            data={"type": "decoder_tools_ready"},
                            category="decoder_tools",
                        )
                    except Exception as e:
                        print(f"[Decoder] Failed to notify {entry['uid']}: {e}")

                    # Update queue status
                    await pool.execute(
                        "UPDATE decoder_queue SET status = 'notified', notified_at = $1 WHERE id = $2",
                        now_iso, entry["id"],
                    )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[Decoder Queue Loop] Error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create connection pool
    await get_pool()
    task = asyncio.create_task(_decoder_queue_loop())
    yield
    # Shutdown: cancel background task and close pool
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await close_pool()


app = FastAPI(
    title="Coconut 3301 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://coconut3301.com", "https://www.coconut3301.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Session-Cookie"],
)

app.include_router(progress_router, prefix="/api/v1")
app.include_router(leaderboard_router, prefix="/api/v1")
app.include_router(content_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(decoder_router, prefix="/api/v1")


@app.get("/")
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/debug/auth")
async def debug_auth(request: Request):
    return await debug_auth_info(request)
