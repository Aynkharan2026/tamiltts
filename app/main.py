import logging
import structlog
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from app.database import get_db
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.routes.auth_routes import router as auth_router
from app.routes.jobs import router as jobs_router
from app.routes.share import router as share_router
from app.routes.cms_integration import router as cms_router
from app.routes.rss_feed import router as rss_router
from app.routes.voices import router as voices_router
from app.routes.conversations import router as conversations_router
from app.routes.consent import router as consent_router
from app.routes.webhooks.stripe import router as stripe_webhook_router
from app.routes.webhooks.publish import router as vaas_publish_router
from app.routes.webhooks.clerk import router as clerk_webhook_router
from app.routes.webhooks.sanity import router as sanity_webhook_router
from app.routes.admin_keys import router as admin_keys_router
from app.routes.admin import router as admin_router

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
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(share_router)
app.include_router(cms_router)
app.include_router(rss_router)
app.include_router(voices_router)
app.include_router(conversations_router)
app.include_router(consent_router)
app.include_router(stripe_webhook_router)
app.include_router(vaas_publish_router)
app.include_router(clerk_webhook_router)
app.include_router(sanity_webhook_router)
app.include_router(admin_keys_router)
app.include_router(admin_router)

templates = Jinja2Templates(directory="app/templates")



@app.get("/health")
async def health():
    return {"status": "ok", "service": "tamiltts-studio"}

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, db: Session = Depends(get_db)):
    from app.auth import get_admin_user
    import os
    try:
        user = get_admin_user(request, db)
    except Exception:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login")
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "admin_secret": admin_secret,
    })


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse("/dashboard")

@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("User-agent: *\nDisallow: /admin\nDisallow: /api/\n")

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
