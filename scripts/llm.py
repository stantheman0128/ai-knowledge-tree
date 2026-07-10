"""LLM 客戶端 — Gemini 主力 + Groq 備用，統一的呼叫介面。"""

from __future__ import annotations

import json
import logging
import os
import time

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── 全域設定 ──────────────────────────────────────────────

# 預設值是預覽版 model，可能被下線。用 GEMINI_MODEL 環境變數覆寫成穩定版，
# 不必改程式。下線時 Gemini 會呼叫失敗並落到 Groq 備援（見 call_llm 的告警）。
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
GROQ_MODEL = "llama-3.3-70b-versatile"
CALL_DELAY = 1.0  # 每次 API 呼叫間隔（秒）
REQUEST_TIMEOUT = 60.0  # 單一 API 請求的 timeout（秒）
RETRY_ATTEMPTS = 3  # 每個 provider 最多嘗試次數（含第一次）
RETRY_BASE_DELAY = 2.0  # 重試等待基數（秒），指數退避 2s → 4s

_gemini_client = None
_groq_client = None

# .env.example 的佔位字串，等同於沒設定
GROQ_PLACEHOLDER_KEY = "your_groq_api_key_here"


def _groq_configured() -> bool:
    """GROQ_API_KEY 有設定且不是 .env.example 的佔位字串才算可用。"""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    return bool(api_key) and api_key != GROQ_PLACEHOLDER_KEY


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        from google.genai import types

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in .env")
        _gemini_client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(REQUEST_TIMEOUT * 1000)),  # 毫秒
        )
    return _gemini_client


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        from groq import Groq

        if not _groq_configured():
            raise ValueError("GROQ_API_KEY not configured in .env (missing or placeholder)")
        # max_retries=0：重試統一由 _with_retry 控制，避免 SDK 內建重試疊加
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=REQUEST_TIMEOUT, max_retries=0)
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


# ── 重試 ──────────────────────────────────────────────────

# 錯誤訊息/類名中出現這些字樣視為暫時性錯誤，值得重試
_TRANSIENT_MARKERS = (
    "429", "500", "502", "503", "504",
    "timeout", "timed out", "connection", "unavailable", "overloaded", "rate limit",
)


def _is_transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def _with_retry(fn, label: str):
    """執行 fn()，遇暫時性錯誤最多重試 RETRY_ATTEMPTS-1 次（指數退避）。"""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == RETRY_ATTEMPTS or not _is_transient(e):
                raise
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                f"{label} transient error (attempt {attempt}/{RETRY_ATTEMPTS}): {e}. "
                f"Retrying in {delay:.0f}s..."
            )
            time.sleep(delay)


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
        result = _with_retry(lambda: _call_gemini(prompt, schema), f"Gemini ({GEMINI_MODEL})")
        logger.debug(f"Gemini OK: {schema.__name__}")
        return result
    except Exception as e:
        gemini_error = e
        logger.error(
            f"Gemini ({GEMINI_MODEL}) failed: {e}. Falling back to Groq ({GROQ_MODEL}) "
            f"— verify the Gemini model id is still available (set GEMINI_MODEL to override)."
        )

    # 備用 Groq：key 沒設定就別打注定失敗的 API call
    if not _groq_configured():
        logger.error("Groq fallback unavailable: GROQ_API_KEY not configured")
        raise RuntimeError(
            f"All LLM providers failed for {schema.__name__}: "
            f"Gemini ({GEMINI_MODEL}) failed with: {gemini_error}; "
            f"Groq fallback unavailable because GROQ_API_KEY is missing or still the "
            f"placeholder '{GROQ_PLACEHOLDER_KEY}'. Fix GEMINI_API_KEY/GEMINI_MODEL "
            f"or set a real GROQ_API_KEY in .env."
        ) from gemini_error

    try:
        result = _with_retry(lambda: _call_groq(prompt, schema), f"Groq ({GROQ_MODEL})")
        logger.debug(f"Groq OK: {schema.__name__}")
        return result
    except Exception as e:
        logger.error(f"Groq also failed: {e}")
        raise RuntimeError(
            f"All LLM providers failed for {schema.__name__}: "
            f"Gemini ({GEMINI_MODEL}): {gemini_error}; Groq ({GROQ_MODEL}): {e}. "
            f"Check GEMINI_API_KEY/GEMINI_MODEL and GROQ_API_KEY in .env."
        ) from e
