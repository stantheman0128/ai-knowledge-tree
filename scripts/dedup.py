"""去重邏輯 — 偵測跨來源的重複事件並合併。"""

from __future__ import annotations

import logging
from datetime import timedelta

from models import Event, ExtractedEvent, RSSItem

logger = logging.getLogger(__name__)


def make_fingerprint(company: str, product: str | None, action: str, date_str: str) -> str:
    """產生事件指紋，用於跨次執行的去重。"""
    prod = (product or "general").lower().replace(" ", "-")
    return f"{company.lower()}|{prod}|{action.lower()}|{date_str}"


def make_event_id(date_str: str, company: str, product: str | None, action: str) -> str:
    """產生 Obsidian 檔案友善的事件 ID。"""
    slug = product or action
    safe_company = company.replace(" ", "-")
    safe_slug = slug.replace(" ", "-").replace("/", "-")
    return f"{date_str}_{safe_company}_{safe_slug}"


# ── 規則式去重 ────────────────────────────────────────────


def _is_likely_duplicate(
    ev_a: ExtractedEvent,
    item_a: RSSItem,
    ev_b: ExtractedEvent,
    item_b: RSSItem,
) -> bool:
    """判斷兩個提取事件是否為同一事件。"""
    # 不同公司 → 不是同一事件
    if ev_a.company.lower() != ev_b.company.lower():
        return False

    # 日期差超過 2 天 → 不是同一事件
    delta = abs(item_a.pub_date - item_b.pub_date)
    if delta > timedelta(days=2):
        return False

    # 同一來源 → 不是重複（同一 feed 不會報兩次同一件事）
    if item_a.source_name == item_b.source_name:
        return False

    # Action 完全不同 → 可能不是同一事件
    if ev_a.action.lower() != ev_b.action.lower():
        return False

    # Product 匹配檢查
    prod_a = (ev_a.product or "").lower().strip()
    prod_b = (ev_b.product or "").lower().strip()

    # 兩個都有 product 且不同 → 不是同一事件
    if prod_a and prod_b and prod_a != prod_b:
        return False

    # 至少一個有 product，或兩個都沒有 → 可能是同一事件
    return True


def find_duplicate_groups(
    events: list[tuple[RSSItem, ExtractedEvent]],
) -> list[list[tuple[RSSItem, ExtractedEvent]]]:
    """
    將事件分組，每組內的事件被認為是同一事件的不同來源報導。

    Returns:
        list of groups，每組是 [(RSSItem, ExtractedEvent), ...] 的列表
    """
    used: set[int] = set()
    groups: list[list[tuple[RSSItem, ExtractedEvent]]] = []

    for i, (item_a, ev_a) in enumerate(events):
        if i in used:
            continue
        group = [(item_a, ev_a)]
        used.add(i)

        for j, (item_b, ev_b) in enumerate(events):
            if j in used:
                continue
            if _is_likely_duplicate(ev_a, item_a, ev_b, item_b):
                group.append((item_b, ev_b))
                used.add(j)

        groups.append(group)

    logger.info(f"Dedup: {len(events)} events -> {len(groups)} unique groups")
    return groups


# ── 合併邏輯 ──────────────────────────────────────────────


def merge_group(group: list[tuple[RSSItem, ExtractedEvent]]) -> Event:
    """
    將一組重複事件合併為一個 Event。

    策略：
    - 取最高的 significance
    - 聯集所有 tags
    - 用最詳細的摘要（最長的 summary）
    - 收集所有來源
    """
    # 按 summary 長度排序，最詳細的排最前面
    group_sorted = sorted(group, key=lambda x: len(x[1].summary), reverse=True)
    primary_item, primary_ev = group_sorted[0]

    # 收集所有來源
    sources = []
    seen_sources: set[str] = set()
    for item, _ in group:
        if item.source_name not in seen_sources:
            sources.append({"name": item.source_name, "link": item.link})
            seen_sources.add(item.source_name)

    # 聯集 tags
    all_tags = list(dict.fromkeys(tag for _, ev in group for tag in ev.tags))

    # 聯集 related_topics
    all_topics = list(dict.fromkeys(t for _, ev in group for t in ev.related_topics))

    # 最高 significance
    max_sig = max(ev.significance for _, ev in group)

    # 最早的日期
    earliest_date = min(item.pub_date for item, _ in group).date()
    date_str = earliest_date.isoformat()

    event_id = make_event_id(date_str, primary_ev.company, primary_ev.product, primary_ev.action)

    return Event(
        event_id=event_id,
        date=earliest_date,
        company=primary_ev.company,
        product=primary_ev.product,
        action=primary_ev.action,
        headline=primary_ev.headline,
        summary=primary_ev.summary,
        significance=max_sig,
        tags=all_tags,
        related_topics=all_topics,
        sources=sources,
    )


# ── 跨次執行去重 ─────────────────────────────────────────


def split_new_vs_update(
    events: list[tuple[RSSItem, ExtractedEvent]],
    existing_fingerprints: dict[str, str],
) -> tuple[list[tuple[RSSItem, ExtractedEvent]], list[tuple[dict, str]]]:
    """
    將事件分為「全新事件」和「已存在事件的新來源」。

    Args:
        events: 待處理的事件列表
        existing_fingerprints: 已知的事件指紋 → event_id 對應

    Returns:
        (new_events, updates)
        - new_events: 全新的事件
        - updates: [(source_info, event_id)] 需要追加來源的已存在事件
    """
    new_events = []
    updates = []

    for item, ev in events:
        date_str = item.pub_date.date().isoformat()
        fp = make_fingerprint(ev.company, ev.product, ev.action, date_str)

        if fp in existing_fingerprints:
            event_id = existing_fingerprints[fp]
            updates.append(({"name": item.source_name, "link": item.link}, event_id))
            logger.debug(f"  Known event, adding source: {ev.headline}")
        else:
            new_events.append((item, ev))

    logger.info(f"Split: {len(new_events)} new, {len(updates)} source additions")
    return new_events, updates
