"""
Stock Talk - Daily Value Stock Analysis
Main FastAPI application entry point.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.core.database import init_db, get_db
from app.api.routes import router as api_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Stock Talk...")
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        logger.warning("App will start but database features won't work until DATABASE_URL is configured")
    yield
    # Shutdown
    logger.info("Shutting down Stock Talk...")


app = FastAPI(
    title="Stock Talk",
    description="Daily value stock analysis from Reddit sentiment and market data",
    version="1.0.0",
    lifespan=lifespan,
)

# Get the directory where this file is located
import os
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Mount static files
app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")

# Templates
templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))

# Include API routes
app.include_router(api_router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the main dashboard."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/report/{report_id}", response_class=HTMLResponse)
async def report_page(request: Request, report_id: int):
    """Render a specific report page."""
    return templates.TemplateResponse(
        "report.html",
        {"request": request, "report_id": report_id}
    )


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    """Render the historical reports page."""
    return templates.TemplateResponse("history.html", {"request": request})


@app.get("/stock/{ticker}", response_class=HTMLResponse)
async def stock_page(request: Request, ticker: str):
    """Render a stock detail page."""
    return templates.TemplateResponse(
        "stock.html",
        {"request": request, "ticker": ticker.upper()}
    )


@app.get("/glossary", response_class=HTMLResponse)
async def glossary_page(request: Request):
    """Render the glossary page."""
    return templates.TemplateResponse("glossary.html", {"request": request})


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "environment": settings.ENVIRONMENT}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
