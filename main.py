"""
UCI Course Recommendation Assistant — FastAPI Entry Point
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.routers import chat

app = FastAPI(
    title="UCI Course Advisor",
    description="Initial demo for course recommendation assistant",
    version="0.1.0",
)

# ── Routers ──────────────────────────────────────────────
app.include_router(chat.router, prefix="/api")

# ── Static files ─────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")
