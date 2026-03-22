"""事件提取器 — 用 LLM 從 RSS 內容中提取結構化事件資料。"""

from __future__ import annotations

import logging

from llm import call_llm
from models import ExtractedEvent, ExtractedEventList, RSSItem

logger = logging.getLogger(__name__)

# ── 公司名稱正規化 ────────────────────────────────────────

COMPANY_ALIASES: dict[str, str] = {
    "openai": "OpenAI",
    "open ai": "OpenAI",
    "google deepmind": "Google DeepMind",
    "deepmind": "Google DeepMind",
    "google": "Google",
    "meta ai": "Meta",
    "meta": "Meta",
    "facebook": "Meta",
    "microsoft": "Microsoft",
    "microsoft research": "Microsoft",
    "nvidia": "NVIDIA",
    "anthropic": "Anthropic",
    "apple": "Apple",
    "amazon": "Amazon",
    "aws": "Amazon",
    "xai": "xAI",
    "x.ai": "xAI",
    "baidu": "Baidu",
    "百度": "Baidu",
    "alibaba": "Alibaba",
    "阿里巴巴": "Alibaba",
    "阿里": "Alibaba",
    "tencent": "Tencent",
    "腾讯": "Tencent",
    "騰訊": "Tencent",
    "bytedance": "ByteDance",
    "字节跳动": "ByteDance",
    "字節跳動": "ByteDance",
    "deepseek": "DeepSeek",
    "mistral": "Mistral",
    "mistral ai": "Mistral",
    "stability ai": "Stability AI",
    "stability": "Stability AI",
    "hugging face": "Hugging Face",
    "huggingface": "Hugging Face",
    "minimax": "MiniMax",
    "zhipu": "Zhipu AI",
    "智谱": "Zhipu AI",
    "moonshot": "Moonshot AI",
    "月之暗面": "Moonshot AI",
    "cohere": "Cohere",
    "perplexity": "Perplexity",
    "cursor": "Cursor",
    "anysphere": "Cursor",
    "midjourney": "Midjourney",
    "runway": "Runway",
    "adobe": "Adobe",
    "samsung": "Samsung",
    "xiaomi": "Xiaomi",
    "小米": "Xiaomi",
}


def normalize_company(name: str) -> str:
    """將公司名稱正規化為統一格式。"""
    return COMPANY_ALIASES.get(name.lower().strip(), name.strip())


# ── Prompt 模板 ───────────────────────────────────────────

DIGEST_PROMPT = """You are an AI news analyst. Extract ALL distinct news events from this daily digest.

For each event, extract:
- company: The primary company involved (use canonical English name, e.g., "OpenAI" not "open ai", "Google DeepMind" not "deepmind")
- product: The specific product/model if mentioned (null if general company news)
- action: One word verb from this set: release, update, acquire, announce, partner, publish, invest, regulate, deprecate, open-source
- headline: One-line summary in English
- summary: 2-3 sentence summary in English explaining what happened and why it matters
- significance: 1-5 scale (1=minor update, 2=notable for niche audience, 3=broadly notable, 4=major industry event, 5=paradigm shift)
- tags: 2-4 tags from: model-release, acquisition, partnership, policy, research, open-source, safety, pricing, developer-tools, robotics, hardware, funding, coding-tools, multimodal, agents
- related_topics: 1-3 broader topic names this connects to (e.g., "Reasoning Models", "AI Safety", "Coding Tools", "Computer Vision", "Robotics")

Source: {source_name}
Date: {pub_date}
Content:
{content}
"""

COMPANY_BLOG_PROMPT = """You are an AI news analyst. Extract structured data from this company blog post.

Company hint: {company_hint}

Extract:
- company: The company that published this (use canonical English name)
- product: The specific product/model if mentioned (null if general news)
- action: One word verb from: release, update, acquire, announce, partner, publish, invest, regulate, deprecate, open-source
- headline: One-line summary in English
- summary: 2-3 sentence summary in English explaining what happened and why it matters
- significance: 1-5 scale (1=minor update, 2=notable for niche audience, 3=broadly notable, 4=major industry event, 5=paradigm shift)
- tags: 2-4 tags from: model-release, acquisition, partnership, policy, research, open-source, safety, pricing, developer-tools, robotics, hardware, funding, coding-tools, multimodal, agents
- related_topics: 1-3 broader topic names this connects to

Title: {title}
Date: {pub_date}
Content:
{content}
"""

# 公司 Blog → 公司名稱對應
FEED_COMPANY_HINTS = {
    "OpenAI-Blog": "OpenAI",
    "Google-AI-Blog": "Google",
    "NVIDIA-Blog": "NVIDIA",
}


# ── 提取邏輯 ──────────────────────────────────────────────


def extract_events(feed_cfg: dict, item: RSSItem) -> list[ExtractedEvent]:
    """
    從一則 RSS 項目中提取事件。

    Digest 類 feed 可能回傳多個事件，Company blog 回傳一個。
    """
    feed_type = feed_cfg["type"]
    # 限制內容長度以節省 token
    content = item.content[:8000]

    try:
        if feed_type in ("digest", "research"):
            return _extract_from_digest(item, content)
        else:
            return _extract_from_blog(feed_cfg, item, content)
    except Exception as e:
        logger.error(f"Failed to extract from {item.source_name} [{item.guid}]: {e}")
        return []


def _extract_from_digest(item: RSSItem, content: str) -> list[ExtractedEvent]:
    """從 digest 類 feed 提取多個事件。"""
    prompt = DIGEST_PROMPT.format(
        source_name=item.source_name,
        pub_date=item.pub_date.strftime("%Y-%m-%d"),
        content=content,
    )
    result = call_llm(prompt, ExtractedEventList)

    # 正規化公司名稱
    for ev in result.events:
        ev.company = normalize_company(ev.company)

    logger.info(f"  Extracted {len(result.events)} events from {item.source_name}")
    return result.events


def _extract_from_blog(feed_cfg: dict, item: RSSItem, content: str) -> list[ExtractedEvent]:
    """從公司 blog feed 提取單一事件。"""
    company_hint = FEED_COMPANY_HINTS.get(feed_cfg["name"], "Unknown")
    prompt = COMPANY_BLOG_PROMPT.format(
        company_hint=company_hint,
        title=item.title,
        pub_date=item.pub_date.strftime("%Y-%m-%d"),
        content=content,
    )
    result = call_llm(prompt, ExtractedEvent)
    result.company = normalize_company(result.company)

    logger.info(f"  Extracted 1 event from {item.source_name}: {result.headline}")
    return [result]
