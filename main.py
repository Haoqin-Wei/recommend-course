"""
UCI Course Recommendation Assistant — FastAPI Entry Point
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.routers import chat, system_info, memory, sessions, onboarding, auth
from app.memory import get_memory_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Memory provider self-initializes per session on first request.
    # Warm the Anteater all-courses cache in the background so the
    # first user to hit Step 4 of the wizard doesn't pay a ~40s wait
    # for the ~90-page cursor-paginated fetch.
    import threading
    def _warm():
        try:
            from app.data.uci_general.anteater_programs import list_all_courses
            list_all_courses()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("courses cache warmup failed: %s", e)
    threading.Thread(target=_warm, daemon=True, name="anteater-warmup").start()

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
app.include_router(onboarding.router)
app.include_router(auth.router)

# ── Static files ─────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")
