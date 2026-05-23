import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.database import engine, Base
from backend.models import *  # registers all models
from backend.routes import creators, sources, content, settings, style, analysis, intelligence, write, fetch, youtube, trends, engage
from backend.scraper_tool.routes import router as scraper_router

Base.metadata.create_all(bind=engine)

# Incremental migrations for SQLite (create_all won't add new columns)
from sqlalchemy import text
_migrations = [
    "ALTER TABLE creators ADD COLUMN scrape_max_posts INTEGER",
    "ALTER TABLE creators ADD COLUMN scrape_linkedin_actor VARCHAR(200)",
    "ALTER TABLE creators ADD COLUMN scrape_twitter_actor VARCHAR(200)",
    "ALTER TABLE creators ADD COLUMN scrape_include_replies BOOLEAN",
    "ALTER TABLE creators ADD COLUMN scrape_include_retweets BOOLEAN",
    "ALTER TABLE sources ADD COLUMN fetch_from_date DATETIME",
    "ALTER TABLE content_items ADD COLUMN transcript TEXT",
    "ALTER TABLE content_items ADD COLUMN image_url VARCHAR(1000)",
    "ALTER TABLE creators ADD COLUMN instagram_handle VARCHAR(100)",
    "ALTER TABLE creators ADD COLUMN tiktok_handle VARCHAR(100)",
    "ALTER TABLE creators ADD COLUMN priority INTEGER",
    "ALTER TABLE hook_library ADD COLUMN source VARCHAR(50) DEFAULT 'extracted'",
    "ALTER TABLE hook_library ADD COLUMN source_label VARCHAR(200)",
    "ALTER TABLE sources ADD COLUMN priority INTEGER DEFAULT 3",
    "ALTER TABLE sources ADD COLUMN category VARCHAR(200)",
    "ALTER TABLE sources ADD COLUMN tags JSON DEFAULT '[]'",
    "ALTER TABLE source_items ADD COLUMN user_tags JSON DEFAULT '[]'",
]
with engine.connect() as _conn:
    for _sql in _migrations:
        try:
            _conn.execute(text(_sql))
            _conn.commit()
        except Exception as _e:
            if "duplicate column" not in str(_e).lower() and "already exists" not in str(_e).lower():
                logger.warning("Migration step failed: %s | %s", _sql, _e)

app = FastAPI(title="Shadi Personal Branding System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(creators.router)
app.include_router(sources.router)
app.include_router(content.router)
app.include_router(settings.router)
app.include_router(style.router)
app.include_router(analysis.router)
app.include_router(intelligence.router)
app.include_router(write.router)
app.include_router(fetch.router)
app.include_router(youtube.router)
app.include_router(trends.router)
app.include_router(engage.router)
app.include_router(scraper_router)

# Serve frontend
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
