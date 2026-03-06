from __future__ import annotations
import logging
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

ROUTING_RULES_QUERY = '*[_type == "ttsRoutingRule" && enabled == true] | order(priority asc) {_id, name, priority, conditions, actions}'

async def fetch_routing_rules() -> list[dict]:
    url = f"https://{settings.SANITY_PROJECT_ID}.api.sanity.io/v2021-10-21/data/query/{settings.SANITY_DATASET}"
    headers = {"Authorization": f"Bearer {settings.SANITY_API_TOKEN}"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers, params={"query": ROUTING_RULES_QUERY})
        resp.raise_for_status()
        return resp.json().get("result", [])

def evaluate_rule(rule: dict, routing_tags: dict) -> bool:
    conditions = rule.get("conditions", [])
    if not conditions:
        return True
    for cond in conditions:
        field = cond.get("field", "")
        operator = cond.get("operator", "equals")
        value = cond.get("value", "")
        if field == "tag":
            actual = routing_tags.get("tags", [])
        elif field == "section":
            actual = routing_tags.get("section", "")
        elif field == "author_role":
            actual = routing_tags.get("author_role", "")
        elif field == "dialect":
            actual = routing_tags.get("dialect", "")
        else:
            actual = ""
        if operator == "equals":
            match = (actual == value) if isinstance(actual, str) else (value in actual)
        elif operator == "contains":
            match = (value in actual) if isinstance(actual, str) else (value in actual)
        elif operator == "startsWith":
            match = actual.startswith(value) if isinstance(actual, str) else False
        else:
            match = False
        if not match:
            return False
    return True

def resolve_channels(rules: list[dict], routing_tags: dict) -> list[str]:
    channels = set()
    for rule in rules:
        if evaluate_rule(rule, routing_tags):
            for action in rule.get("actions", []):
                channels.add(action)
    channels.add("website_embed")
    return list(channels)

class RoutingEngine:
    def __init__(self, job_id, article_id, audio_url, output_filename, title, dialect, preset):
        self.job_id = job_id
        self.article_id = article_id
        self.audio_url = audio_url
        self.output_filename = output_filename
        self.title = title
        self.dialect = dialect
        self.preset = preset

    async def dispatch(self, routing_tags: dict) -> dict:
        results = {}
        try:
            rules = await fetch_routing_rules()
        except Exception as e:
            logger.error(f"Failed to fetch routing rules: {e}")
            rules = []
        channels = resolve_channels(rules, routing_tags)
        logger.info(f"Job {self.job_id}: dispatching to {channels}")
        for channel in channels:
            try:
                results[channel] = await self._dispatch_channel(channel)
            except Exception as e:
                logger.error(f"Channel [{channel}] failed: {e}")
                results[channel] = "failed"
        return results

    async def _dispatch_channel(self, channel: str) -> str:
        dispatcher = {
            "website_embed":    self._dispatch_website_embed,
            "whatsapp":         self._dispatch_whatsapp,
            "telegram":         self._dispatch_telegram,
            "podcast_rss":      self._dispatch_podcast_rss,
            "apple_podcasts":   self._dispatch_podcast_rss,
            "spotify":          self._dispatch_podcast_rss,
            "email_newsletter": self._dispatch_email_newsletter,
            "youtube_audio":    self._dispatch_youtube,
            "perdomo":          self._dispatch_perdomo,
        }.get(channel)
        if not dispatcher:
            return "skipped"
        return await dispatcher()

    async def _dispatch_website_embed(self) -> str:
        url = f"https://{settings.SANITY_PROJECT_ID}.api.sanity.io/v2021-10-21/data/mutate/{settings.SANITY_DATASET}"
        headers = {"Authorization": f"Bearer {settings.SANITY_API_TOKEN}", "Content-Type": "application/json"}
        mutation = {"mutations": [{"patch": {"id": self.article_id, "set": {
            "ttsAudio.audioUrl": self.audio_url, "ttsAudio.status": "complete",
            "ttsAudio.jobId": self.job_id, "ttsAudio.outputFilename": self.output_filename,
        }}}]}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=mutation)
            resp.raise_for_status()
        return "delivered"

    async def _dispatch_telegram(self) -> str:
        if not getattr(settings, "TELEGRAM_BOT_TOKEN", None):
            return "skipped"
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendAudio"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json={
                "chat_id": settings.TELEGRAM_CHANNEL_ID, "audio": self.audio_url,
                "title": self.title, "caption": f"🎙 {self.title}",
            })
            resp.raise_for_status()
        return "delivered"

    async def _dispatch_whatsapp(self) -> str:
        if not getattr(settings, "WHATSAPP_API_TOKEN", None):
            return "skipped"
        url = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        headers = {"Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json={
                "messaging_product": "whatsapp", "to": settings.WHATSAPP_BROADCAST_NUMBER,
                "type": "audio", "audio": {"link": self.audio_url},
            })
            resp.raise_for_status()
        return "delivered"

    async def _dispatch_podcast_rss(self) -> str:
        import time
        url = f"https://{settings.SANITY_PROJECT_ID}.api.sanity.io/v2021-10-21/data/mutate/{settings.SANITY_DATASET}"
        headers = {"Authorization": f"Bearer {settings.SANITY_API_TOKEN}", "Content-Type": "application/json"}
        mutation = {"mutations": [{"create": {
            "_type": "podcastEpisode", "_id": f"episode-{self.job_id}",
            "title": self.title, "audioUrl": self.audio_url,
            "articleId": self.article_id, "dialect": self.dialect,
            "filename": self.output_filename, "pubDate": str(int(time.time())),
        }}]}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=mutation)
            resp.raise_for_status()
        return "delivered"

    async def _dispatch_email_newsletter(self) -> str:
        if not getattr(settings, "NEWSLETTER_PROVIDER", None):
            return "skipped"
        return "queued"

    async def _dispatch_youtube(self) -> str:
        if not getattr(settings, "YOUTUBE_OAUTH_TOKEN", None):
            return "skipped"
        return "queued"

    async def _dispatch_perdomo(self) -> str:
        return "skipped"
