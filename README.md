# AI Knowledge Tree

RSS 新聞來源 → LLM 結構化提取 → Obsidian vault 的自動化管線。

從多個 AI 新聞 feed（每日 digest 與公司官方 blog）抓取新文章，用 LLM 提取成結構化事件（公司、產品、動作、重要性、標籤），做跨來源與跨次執行的去重，最後寫成 Obsidian 友善的 Markdown 檔：`vault/Events/` 每事件一檔、`vault/Companies/` 公司索引、每日摘要。

## 使用方式

```
pip install -r requirements.txt
copy .env.example .env   # 填入 API key
python scripts/fetch.py            # 完整執行：抓取 → 提取 → 去重 → 寫入 vault
python scripts/fetch.py --dry-run  # 只提取並列出結果，不寫檔、不更新狀態
python scripts/fetch.py --verbose  # 顯示 DEBUG 日誌
```

處理進度存在 `state/processed.json`（已處理的 GUID 與事件指紋），提取失敗的項目不會標記為已處理，下次執行會自動重試。

## 環境變數（.env）

| 變數 | 必要性 | 說明 |
|------|--------|------|
| `GEMINI_API_KEY` | 必要 | 主力 LLM（Gemini）。取得：https://aistudio.google.com/apikey |
| `GROQ_API_KEY` | 選用 | 備援 LLM（Groq）。沒設或留著佔位字串時會直接跳過備援，Gemini 掛掉就整批失敗。取得：https://console.groq.com |
| `GEMINI_MODEL` | 選用 | 覆寫 Gemini model id。預設值 `gemini-3.1-flash-lite-preview` 是預覽版，隨時可能被 Google 下線；下線時 Gemini 呼叫會失敗並落到 Groq 備援。遇到這種情況不必改程式，設這個變數指到穩定版 model 即可，例如 `GEMINI_MODEL=gemini-3.1-flash`。 |

## 測試

離線測試（不打任何 LLM API）：

```
python tests/test_fetch_state.py
```

## 專案結構

```
scripts/
  fetch.py         主程式與狀態管理（entry point）
  rss_sources.py   feed 清單、抓取與 HTML 清洗
  extractor.py     LLM 提取 prompt 與公司名稱正規化
  llm.py           Gemini 主力 + Groq 備援、timeout 與重試
  dedup.py         同批與跨次執行的事件去重
  vault_writer.py  Obsidian Markdown 寫入
  models.py        Pydantic 資料模型
vault/             產出的 Obsidian vault
state/             processed.json 處理狀態（gitignored）
```
