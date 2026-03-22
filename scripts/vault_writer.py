"""Obsidian Vault 寫入器 — 產生 Event、Company、Daily 的 Markdown 筆記。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from models import Event

logger = logging.getLogger(__name__)


def _sanitize_filename(s: str) -> str:
    """移除檔案名稱中不安全的字元。"""
    s = re.sub(r'[<>:"/\\|?*]', "-", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


# ── Event 筆記 ────────────────────────────────────────────


def write_event(event: Event, vault_path: Path) -> Path:
    """寫入一個 Event 筆記到 vault/Events/。"""
    filename = f"{_sanitize_filename(event.event_id)}.md"
    filepath = vault_path / "Events" / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # YAML frontmatter
    frontmatter = {
        "date": str(event.date),
        "company": f"[[{event.company}]]",
        "product": event.product,
        "action": event.action,
        "significance": event.significance,
        "tags": event.tags,
        "sources": [s["name"] for s in event.sources],
    }

    # Markdown body
    body_parts = [
        f"## {event.headline}",
        "",
        event.summary,
        "",
        "## Sources",
    ]
    for s in event.sources:
        body_parts.append(f"- [{s['name']}]({s['link']})")

    body_parts.append("")
    body_parts.append("## Related")
    for topic in event.related_topics:
        body_parts.append(f"- [[{topic}]]")

    body = "\n".join(body_parts)

    # 組合完整內容
    fm_str = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False)
    content = f"---\n{fm_str}---\n\n{body}\n"

    filepath.write_text(content, encoding="utf-8")
    logger.debug(f"  Wrote event: {filepath.name}")
    return filepath


# ── Company 索引筆記 ──────────────────────────────────────


def update_company_index(company: str, vault_path: Path) -> None:
    """
    建立或更新公司索引筆記。

    使用 Obsidian 的 backlinks 功能 — 所有連結到 [[Company]] 的 Event
    都會自動出現在公司頁面的 backlinks 面板中。
    """
    filename = f"{_sanitize_filename(company)}.md"
    filepath = vault_path / "Companies" / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # 只在檔案不存在時建立
    if filepath.exists():
        return

    content = f"""---
type: company
name: "{company}"
---

# {company}

> 此頁面透過 Obsidian 的 Backlinks 面板自動顯示所有相關事件。
> 點擊右側面板的「Backlinks」即可查看 [[{company}]] 的完整時間線。
"""
    filepath.write_text(content, encoding="utf-8")
    logger.debug(f"  Created company index: {company}")


# ── Daily Digest 筆記 ─────────────────────────────────────


def write_daily_digest(date_str: str, events: list[Event], vault_path: Path) -> None:
    """寫入每日摘要筆記，按重要性分組。"""
    filepath = vault_path / "Daily" / f"{date_str}.md"
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # 按重要性分組
    key_events = [e for e in events if e.significance >= 4]
    notable_events = [e for e in events if 2 <= e.significance <= 3]
    other_events = [e for e in events if e.significance <= 1]

    parts = [
        f"---\ndate: {date_str}\ntype: daily-digest\n---\n",
        f"# AI News — {date_str}\n",
    ]

    if key_events:
        parts.append("## Key Events (significance 4-5)")
        for e in key_events:
            parts.append(f"- [[{_sanitize_filename(e.event_id)}|{e.headline}]] — {e.company}")
        parts.append("")

    if notable_events:
        parts.append("## Notable (significance 2-3)")
        for e in notable_events:
            parts.append(f"- [[{_sanitize_filename(e.event_id)}|{e.headline}]] — {e.company}")
        parts.append("")

    if other_events:
        parts.append("## Other")
        for e in other_events:
            parts.append(f"- [[{_sanitize_filename(e.event_id)}|{e.headline}]] — {e.company}")
        parts.append("")

    if not events:
        parts.append("_No new events today._\n")

    content = "\n".join(parts)
    filepath.write_text(content, encoding="utf-8")
    logger.info(f"  Wrote daily digest: {date_str} ({len(events)} events)")


# ── 追加來源到已存在的 Event ──────────────────────────────


def append_source_to_event(source_info: dict, event_id: str, vault_path: Path) -> None:
    """將新的來源追加到已存在的 Event 筆記中。"""
    filename = f"{_sanitize_filename(event_id)}.md"
    filepath = vault_path / "Events" / filename

    if not filepath.exists():
        logger.warning(f"  Event file not found for source append: {filename}")
        return

    content = filepath.read_text(encoding="utf-8")
    source_line = f"- [{source_info['name']}]({source_info['link']})"

    # 在 ## Sources 區塊末尾插入新來源
    if source_line in content:
        return  # 已存在

    # 找到 ## Sources 區塊的結尾（下一個 ## 之前）
    sources_match = re.search(r"(## Sources\n(?:- .+\n)*)", content)
    if sources_match:
        insert_pos = sources_match.end()
        content = content[:insert_pos] + source_line + "\n" + content[insert_pos:]
        filepath.write_text(content, encoding="utf-8")
        logger.debug(f"  Appended source to: {filename}")
