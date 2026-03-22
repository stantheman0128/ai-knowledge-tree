"""資料模型 — 定義 RSS 項目、LLM 提取結果、最終事件的結構。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class RSSItem(BaseModel):
    """從 RSS feed 解析出的原始項目。"""

    source_name: str
    guid: str
    title: str
    link: str
    pub_date: datetime
    content: str  # HTML 已剝離的純文字


class ExtractedEvent(BaseModel):
    """LLM 從一則新聞中提取出的結構化事件。"""

    company: str = Field(description="公司名稱 (canonical English name, e.g. 'OpenAI')")
    product: str | None = Field(default=None, description="產品或模型名稱")
    action: str = Field(description="動作: release, update, acquire, announce, partner, publish, invest, regulate, deprecate, open-source")
    headline: str = Field(description="一行英文摘要")
    summary: str = Field(description="2-3 句英文摘要")
    significance: int = Field(ge=1, le=5, description="重要性 1-5")
    tags: list[str] = Field(description="標籤, e.g. model-release, acquisition, safety")
    related_topics: list[str] = Field(default_factory=list, description="相關主題, e.g. Reasoning Models, Coding Tools")


class ExtractedEventList(BaseModel):
    """LLM 從 digest 類 feed 中提取出的多個事件。"""

    events: list[ExtractedEvent]


class Event(BaseModel):
    """去重合併後的最終事件，用於寫入 Obsidian vault。"""

    event_id: str  # e.g. "2026-03-22_OpenAI_GPT-5"
    date: date
    company: str
    product: str | None = None
    action: str
    headline: str
    summary: str
    significance: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    related_topics: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)  # [{"name": ..., "link": ...}]
