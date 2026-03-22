"""RSS 來源管理 — 定義所有 feed、抓取、過濾已處理項目。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser
import html2text

from models import RSSItem

logger = logging.getLogger(__name__)

# ── Feed 設定 ──────────────────────────────────────────────

FEEDS = [
    {
        "name": "橘鸦AI早報",
        "url": "https://imjuya.github.io/juya-ai-daily/rss.xml",
        "lang": "zh",
        "type": "digest",
    },
    {
        "name": "AI-Digest",
        "url": "https://ai-digest.liziran.com/en/feed.xml",
        "lang": "en",
        "type": "digest",
    },
    {
        "name": "AI-Brief",
        "url": "https://ai-brief.liziran.com/en/feed.xml",
        "lang": "en",
        "type": "research",
    },
    {
        "name": "OpenAI-Blog",
        "url": "https://openai.com/blog/rss.xml",
        "lang": "en",
        "type": "company",
    },
    {
        "name": "Google-AI-Blog",
        "url": "https://blog.google/technology/ai/rss/",
        "lang": "en",
        "type": "company",
    },
    {
        "name": "NVIDIA-Blog",
        "url": "https://blogs.nvidia.com/feed/",
        "lang": "en",
        "type": "company",
    },
]

# ── HTML → 純文字轉換器 ───────────────────────────────────

_h2t = html2text.HTML2Text()
_h2t.ignore_links = False
_h2t.ignore_images = True
_h2t.body_width = 0  # 不自動換行


def _strip_html(raw_html: str) -> str:
    """將 HTML 轉為乾淨的 Markdown/純文字。"""
    return _h2t.handle(raw_html).strip()


def _parse_date(entry: dict) -> datetime:
    """從 feedparser entry 解析出 datetime。"""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        from calendar import timegm

        return datetime.fromtimestamp(timegm(entry.published_parsed), tz=timezone.utc)
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        from calendar import timegm

        return datetime.fromtimestamp(timegm(entry.updated_parsed), tz=timezone.utc)
    return datetime.now(tz=timezone.utc)


# ── 主要抓取邏輯 ──────────────────────────────────────────


def fetch_all_feeds(processed_guids: set[str]) -> list[tuple[dict, list[RSSItem]]]:
    """
    抓取所有 RSS feeds，過濾已處理的項目。

    Returns:
        list of (feed_config, [RSSItem, ...]) 對，每個 feed 一組。
    """
    results = []

    for feed_cfg in FEEDS:
        name = feed_cfg["name"]
        url = feed_cfg["url"]
        logger.info(f"Fetching {name}: {url}")

        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            logger.warning(f"Failed to fetch {name}: {e}")
            continue

        if parsed.bozo and not parsed.entries:
            logger.warning(f"Feed {name} returned no entries (bozo: {parsed.bozo_exception})")
            continue

        # 限制每個 feed 最多取 20 個最新項目（避免首次執行時處理太多）
        entries = parsed.entries[:20]

        items = []
        for entry in entries:
            guid = entry.get("id") or entry.get("link", "")
            if guid in processed_guids:
                logger.debug(f"  Skipping already processed: {guid}")
                continue

            # 取得內容：優先 content:encoded，退回 description
            raw_content = ""
            if hasattr(entry, "content") and entry.content:
                raw_content = entry.content[0].get("value", "")
            if not raw_content:
                raw_content = entry.get("summary", "") or entry.get("description", "")

            content = _strip_html(raw_content)

            # 如果 content 太短，把 title 加進去讓 LLM 有更多上下文
            title = entry.get("title", "")
            if len(content) < 200 and title:
                content = f"Title: {title}\n\n{content}"

            if not content or len(content) < 20:
                logger.debug(f"  Skipping empty content: {guid}")
                continue

            items.append(
                RSSItem(
                    source_name=name,
                    guid=guid,
                    title=entry.get("title", "Untitled"),
                    link=entry.get("link", ""),
                    pub_date=_parse_date(entry),
                    content=content,
                )
            )

        logger.info(f"  {name}: {len(items)} new items")
        if items:
            results.append((feed_cfg, items))

    return results
