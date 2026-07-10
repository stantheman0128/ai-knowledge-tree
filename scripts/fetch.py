"""主程式 — 抓取 RSS、提取事件、去重、寫入 Obsidian vault。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

# 載入 .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from dedup import find_duplicate_groups, make_fingerprint, merge_group, split_new_vs_update
from extractor import extract_events
from rss_sources import fetch_all_feeds
from vault_writer import append_source_to_event, update_company_index, write_daily_digest, write_event

logger = logging.getLogger(__name__)

# ── 路徑設定 ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "state"
STATE_FILE = STATE_DIR / "processed.json"
VAULT_PATH = PROJECT_ROOT / "vault"


# ── State 管理 ────────────────────────────────────────────


def load_state() -> dict:
    """載入處理狀態。"""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {
        "processed_guids": [],
        "event_fingerprints": {},
        "last_run": None,
    }


def save_state(state: dict) -> None:
    """儲存處理狀態。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone

    state["last_run"] = datetime.now(tz=timezone.utc).isoformat()
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"State saved ({len(state['processed_guids'])} GUIDs tracked)")


# ── 主要流程 ──────────────────────────────────────────────


def main(dry_run: bool = False) -> None:
    """執行完整的抓取 → 提取 → 去重 → 寫入流程。"""

    # 1. 載入狀態
    state = load_state()
    processed_guids = set(state["processed_guids"])
    event_fingerprints: dict[str, str] = state.get("event_fingerprints", {})

    # 2. 抓取 RSS feeds
    logger.info("=" * 60)
    logger.info("Step 1: Fetching RSS feeds...")
    feed_results = fetch_all_feeds(processed_guids)

    if not feed_results:
        logger.info("No new items to process. Done!")
        return

    total_items = sum(len(items) for _, items in feed_results)
    logger.info(f"Total new items: {total_items}")

    # 3. 用 LLM 提取事件
    logger.info("=" * 60)
    logger.info("Step 2: Extracting events via LLM...")
    all_extracted: list[tuple] = []  # [(RSSItem, ExtractedEvent), ...]
    new_guids: list[str] = []
    failed_count = 0

    for feed_cfg, items in feed_results:
        for item in items:
            logger.info(f"Processing: [{item.source_name}] {item.title[:60]}")
            events = extract_events(feed_cfg, item)
            if events is None:
                # 提取失敗（extract_events 已記錄原因）：不標記為已處理，下次重試
                failed_count += 1
                continue
            for ev in events:
                all_extracted.append((item, ev))
            new_guids.append(item.guid)

    logger.info(f"Extracted {len(all_extracted)} events total")
    if failed_count:
        logger.warning(f"{failed_count} item(s) failed extraction — left unmarked, will retry next run")

    if not all_extracted:
        logger.info("No events extracted. Updating state and exiting.")
        state["processed_guids"].extend(new_guids)
        if not dry_run:
            save_state(state)
        return

    # 4. 跨次執行去重（檢查是否已知事件的新來源）
    logger.info("=" * 60)
    logger.info("Step 3: Cross-run deduplication...")
    new_events, source_updates = split_new_vs_update(all_extracted, event_fingerprints)

    # 5. 同次執行去重（同一批新聞中的重複）
    logger.info("Step 4: Intra-batch deduplication...")
    groups = find_duplicate_groups(new_events)
    merged_events = [merge_group(g) for g in groups]

    # 6. 統計
    logger.info("=" * 60)
    logger.info(f"Results: {len(merged_events)} new events, {len(source_updates)} source additions")

    if dry_run:
        logger.info("[DRY RUN] Would write the following events:")
        for ev in merged_events:
            logger.info(f"  [{ev.significance}/5] {ev.company} — {ev.headline}")
            logger.info(f"    Sources: {', '.join(s['name'] for s in ev.sources)}")
        return

    # 7. 寫入 Vault
    logger.info("Step 5: Writing to Obsidian vault...")

    # 寫入新事件
    for event in merged_events:
        write_event(event, VAULT_PATH)
        update_company_index(event.company, VAULT_PATH)

    # 追加新來源到已存在事件
    for source_info, event_id in source_updates:
        append_source_to_event(source_info, event_id, VAULT_PATH)

    # 產生每日摘要
    events_by_date: dict[str, list] = defaultdict(list)
    for ev in merged_events:
        events_by_date[str(ev.date)].append(ev)
    for date_str, day_events in events_by_date.items():
        write_daily_digest(date_str, day_events, VAULT_PATH)

    # 8. 更新狀態
    logger.info("Step 6: Updating state...")
    state["processed_guids"].extend(new_guids)

    for ev in merged_events:
        fp = make_fingerprint(ev.company, ev.product, ev.action, str(ev.date))
        event_fingerprints[fp] = ev.event_id
    state["event_fingerprints"] = event_fingerprints

    save_state(state)

    logger.info("=" * 60)
    logger.info("Done!")


# ── CLI ───────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Knowledge Tree — RSS → Obsidian")
    parser.add_argument("--verbose", "-v", action="store_true", help="顯示詳細日誌")
    parser.add_argument("--dry-run", action="store_true", help="只提取不寫入檔案")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        main(dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
