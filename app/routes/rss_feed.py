from __future__ import annotations
import logging
import time
from email.utils import formatdate
import httpx
from fastapi import APIRouter
from fastapi.responses import Response
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rss", tags=["RSS Feed"])

EPISODES_QUERY = '*[_type == "podcastEpisode"] | order(pubDate desc) [0...100] {_id, title, audioUrl, dialect, filename, pubDate}'

@router.get("/feed.xml", response_class=Response)
async def podcast_rss_feed():
    episodes = await _fetch_episodes()
    xml = _build_rss(episodes)
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

async def _fetch_episodes() -> list[dict]:
    url = f"https://{settings.SANITY_PROJECT_ID}.api.sanity.io/v2021-10-21/data/query/{settings.SANITY_DATASET}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url,
                headers={"Authorization": f"Bearer {settings.SANITY_API_TOKEN}"},
                params={"query": EPISODES_QUERY})
            resp.raise_for_status()
            return resp.json().get("result", [])
    except Exception as e:
        logger.error(f"Failed to fetch episodes: {e}")
        return []

def _build_rss(episodes: list[dict]) -> str:
    feed_url = f"https://{settings.RSS_BASE_DOMAIN}/api/rss/feed.xml"
    now_rfc  = formatdate(usegmt=True)
    items = ""
    for ep in episodes:
        pub_ts  = int(ep.get("pubDate", 0) or 0)
        pub_rfc = formatdate(pub_ts, usegmt=True) if pub_ts else now_rfc
        title   = _x(ep.get("title", "Untitled"))
        audio   = ep.get("audioUrl", "")
        ep_id   = ep.get("_id", "")
        items  += f"""
    <item>
      <title>{title}</title>
      <enclosure url="{audio}" type="audio/mpeg" length="0"/>
      <guid isPermaLink="false">{ep_id}</guid>
      <pubDate>{pub_rfc}</pubDate>
      <itunes:title>{title}</itunes:title>
      <itunes:episodeType>full</itunes:episodeType>
    </item>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Tamil TTS Studio</title>
    <description>Audio versions of Tamil articles — powered by VoxTN</description>
    <link>https://voxtn.com</link>
    <language>ta</language>
    <lastBuildDate>{now_rfc}</lastBuildDate>
    <atom:link href="{feed_url}" rel="self" type="application/rss+xml"/>
    <itunes:author>VoxTN — 17488149 CANADA CORP.</itunes:author>
    <itunes:category text="News"/>
    <itunes:explicit>false</itunes:explicit>{items}
  </channel>
</rss>"""

def _x(t: str) -> str:
    return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")


# ── Tenant + category feeds (VaaS Phase 4) ───────────────────────────────────
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Job, JobStatus
from fastapi import Depends
from app.services.r2_storage import R2StorageService
import json

@router.get("/feeds/{tenant_slug}.xml", response_class=Response)
async def tenant_feed(tenant_slug: str, db: Session = Depends(get_db)):
    xml = await _build_tenant_feed(tenant_slug, None, db)
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@router.get("/feeds/{tenant_slug}/{category}.xml", response_class=Response)
async def tenant_category_feed(tenant_slug: str, category: str, db: Session = Depends(get_db)):
    xml = await _build_tenant_feed(tenant_slug, category, db)
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


async def _build_tenant_feed(tenant_slug: str, category: str | None, db: Session) -> str:
    from sqlalchemy import text
    from email.utils import formatdate

    # Resolve tenant
    tenant = db.execute(
        text("SELECT id, name FROM tenants WHERE slug = :slug AND is_active = true"),
        {"slug": tenant_slug},
    ).fetchone()
    if not tenant:
        return _empty_feed(tenant_slug)

    # Query jobs
    query = text("""
        SELECT id, title, r2_key, dialect, created_at, article_id,
               routing_tags
        FROM jobs
        WHERE tenant_id = :tid
          AND status = 'done'
          AND r2_key IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 100
    """)
    rows = db.execute(query, {"tid": str(tenant.id)}).fetchall()

    if category:
        rows = [r for r in rows
                if r.routing_tags and
                isinstance(r.routing_tags, dict) and
                r.routing_tags.get("section") == category]

    r2 = R2StorageService()
    now_rfc = formatdate(usegmt=True)
    items = ""
    for row in rows:
        try:
            signed = r2.generate_signed_url(row.r2_key)
            audio_url = signed["url"]
        except Exception:
            continue
        title   = _x(row.title or row.id)
        pub_rfc = formatdate(row.created_at.timestamp(), usegmt=True) if row.created_at else now_rfc
        guid    = f"https://{settings.RSS_BASE_DOMAIN}/jobs/{row.id}"
        items  += f"""
    <item>
      <title>{title}</title>
      <enclosure url="{audio_url}" type="audio/mpeg" length="0"/>
      <guid isPermaLink="false">{guid}</guid>
      <pubDate>{pub_rfc}</pubDate>
      <itunes:title>{title}</itunes:title>
      <itunes:episodeType>full</itunes:episodeType>
    </item>"""

    cat_label = f" — {category}" if category else ""
    feed_url  = f"https://{settings.RSS_BASE_DOMAIN}/feeds/{tenant_slug}"
    feed_url += f"/{category}.xml" if category else ".xml"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{_x(tenant.name)}{cat_label}</title>
    <description>Audio feed for {_x(tenant.name)}{cat_label} — powered by VoxTN</description>
    <link>https://{settings.RSS_BASE_DOMAIN}</link>
    <language>ta</language>
    <lastBuildDate>{now_rfc}</lastBuildDate>
    <atom:link href="{feed_url}" rel="self" type="application/rss+xml"/>
    <itunes:author>VoxTN — 17488149 CANADA CORP.</itunes:author>
    <itunes:explicit>false</itunes:explicit>{items}
  </channel>
</rss>"""


def _empty_feed(slug: str) -> str:
    from email.utils import formatdate
    now_rfc = formatdate(usegmt=True)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{slug}</title>
    <description>No content found</description>
    <lastBuildDate>{now_rfc}</lastBuildDate>
  </channel>
</rss>"""
