"""
UCI Course Recommendation Assistant — FastAPI Entry Point
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.routers import chat, system_info, memory, sessions
from app.memory import get_memory_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Memory provider self-initializes per session on first request.
    yield
    # On shutdown, flush any in-memory state to disk.
    get_memory_manager().shutdown()


app = FastAPI(
    title="UCI Course Advisor",
    description="Initial demo for course recommendation assistant",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Routers ──────────────────────────────────────────────
app.include_router(chat.router, prefix="/api")
app.include_router(system_info.router)
app.include_router(memory.router)
app.include_router(sessions.router)

# ── Static files ─────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")
