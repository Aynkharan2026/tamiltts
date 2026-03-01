import logging
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.routes.auth_routes import router as auth_router
from app.routes.jobs import router as jobs_router
from app.routes.share import router as share_router

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.APP_NAME, docs_url=None, redoc_url=None)

app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(share_router)

templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse("/dashboard")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse(
        "base.html",
        {"request": request, "title": "404 Not Found", "error": "Page not found"},
        status_code=404,
    )


@app.exception_handler(500)
async def server_error(request: Request, exc):
    return templates.TemplateResponse(
        "base.html",
        {"request": request, "title": "Server Error", "error": "Internal server error"},
        status_code=500,
    )
