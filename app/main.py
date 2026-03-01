from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .auth import debug_auth_info
from .database import get_pool, close_pool
from .routes.progress import router as progress_router
from .routes.leaderboard import router as leaderboard_router
from .routes.content import router as content_router
from .routes.admin import router as admin_router
from .routes.notifications import router as notifications_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create connection pool
    await get_pool()
    yield
    # Shutdown: close pool
    await close_pool()


app = FastAPI(
    title="Coconut 3301 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(progress_router, prefix="/api/v1")
app.include_router(leaderboard_router, prefix="/api/v1")
app.include_router(content_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")


@app.get("/")
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/debug/auth")
async def debug_auth(request: Request):
    return await debug_auth_info(request)
