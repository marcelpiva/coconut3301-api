from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import get_pool, close_pool
from .routes.progress import router as progress_router
from .routes.leaderboard import router as leaderboard_router


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
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(progress_router, prefix="/api/v1")
app.include_router(leaderboard_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
