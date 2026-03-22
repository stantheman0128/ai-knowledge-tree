"""LLM 客戶端 — Gemini 主力 + Groq 備用，統一的呼叫介面。"""

from __future__ import annotations

import json
import logging
import os
import time

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── 全域設定 ──────────────────────────────────────────────

GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
GROQ_MODEL = "llama-3.3-70b-versatile"
CALL_DELAY = 1.0  # 每次 API 呼叫間隔（秒）

_gemini_client = None
_groq_client = None


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in .env")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        from groq import Groq

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in .env")
        _groq_client = Groq(api_key=api_key)
    return _groq_client


# ── Gemini 呼叫 ──────────────────────────────────────────


def _call_gemini(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """用 Gemini 的 structured output 功能直接輸出 JSON。"""
    client = _get_gemini_client()
    from google.genai import types

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2,
        ),
    )
    return schema.model_validate_json(response.text)


# ── Groq 呼叫 ────────────────────────────────────────────


def _call_groq(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """用 Groq 的 JSON mode + Pydantic 驗證。"""
    client = _get_groq_client()

    # 在 prompt 中加入 schema 說明
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    full_prompt = (
        f"{prompt}\n\n"
        f"Respond with valid JSON matching this schema:\n```json\n{schema_json}\n```"
    )

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": full_prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return schema.model_validate_json(response.choices[0].message.content)


# ── 統一介面 ──────────────────────────────────────────────


def call_llm(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """
    呼叫 LLM 提取結構化資料。先試 Gemini，失敗則用 Groq。

    Args:
        prompt: 完整的 prompt 文字
        schema: Pydantic model class，定義回傳的 JSON 結構

    Returns:
        填好資料的 Pydantic model instance
    """
    time.sleep(CALL_DELAY)

    # 嘗試 Gemini
    try:
        result = _call_gemini(prompt, schema)
        logger.debug(f"Gemini OK: {schema.__name__}")
        return result
    except Exception as e:
        logger.warning(f"Gemini failed ({e}), falling back to Groq...")

    # 備用 Groq
    try:
        result = _call_groq(prompt, schema)
        logger.debug(f"Groq OK: {schema.__name__}")
        return result
    except Exception as e:
        logger.error(f"Groq also failed: {e}")
        raise RuntimeError(f"All LLM providers failed for {schema.__name__}") from e
