# CLAUDE.md — 專案開發指南

購物網站價格追蹤 + Telegram 提醒服務。給 Claude Code 與人類開發者的快速上手文件。

## 這個專案怎麼運作
- 使用者在 Telegram 貼商品網址 → 寫入 Postgres。
- Celery Beat 定時把到期商品排進佇列；Worker 跑**分層萃取管線**取得價格，與舊價比較後用 Telegram 提醒（只通知該商品的擁有者）。
- **執行時不串接任何 LLM**。三層自動萃取都失敗時，標記商品為 `unsupported`、寫入 `unsupported_requests` 待辦、通知使用者「請管理員新增」。
- 「新增網站支援」由**管理員用 Claude Code CLI** 完成：`/add-scraper <url>`（見 `.claude/skills/add-scraper/`）。
- **白名單授權**：只有管理員/白名單使用者能用指令；`/start` 例外（任何人可送、僅靜默記錄）。

## 分層萃取管線（`app/extraction/pipeline.py`）
`extract_price(url) -> ExtractionResult`，依序：
1. **L_adapter**：該網域若有註冊專屬 adapter，先用它。
2. **L0**：`httpx` 抓靜態 HTML → `parse_structured`（JSON-LD / microdata / OpenGraph / RDFa）。
3. **L1**：Playwright 渲染後 → 再跑一次 `parse_structured`。
4. 全部失敗 → `ExtractionResult.unsupported()`。

大多數電商有結構化資料，L0/L1 即可命中，**不需要寫 adapter**。adapter 只給少數需要 DOM 操作或重度反爬的網站。

## Adapter 擴充模式（主要擴充點）
- 介面在 `app/extraction/adapters/base.py`：繼承 `BaseAdapter`、設 `domains`、實作 `async def extract(url, ctx)`。
- 子類別被 import 時**自動註冊**（`__init_subclass__`）；`registry.py` 啟動時掃描 `adapters/` 套件觸發註冊。**新增檔案即生效，不需改其他程式。**
- 樣板：`app/extraction/adapters/_template.py`（`domains` 空 → 不註冊）。
- 命名：檔名用底線（`shopee_tw.py`），`domains` 用真實網域（`["shopee.tw"]`），子網域自動比對。

### `FetchContext`（`app/extraction/context.py`）— adapter 可用的工具
- `await ctx.fetch_static_html(url)` — 靜態 HTML（含反爬限流）
- `await ctx.fetch_rendered(url, wait_selector=None)` — Playwright 渲染後 HTML
- `async with ctx.page(url, wait_selector=None) as page:` — 直接操作 DOM
- 共用解析器：`from app.extraction.structured import parse_structured`
> 一律透過 `ctx` 取得頁面（已內建 per-domain 限流與 UA/proxy），**不要**自己另開連線繞過限流。

## 反爬（`app/extraction/antibot.py`）
- per-domain 最小請求間隔（Redis）+ jitter；輪換 User-Agent；`PROXY_POOL` 選用。
- 失敗指數退避；`consecutive_failures` 達 `MAX_CONSECUTIVE_FAILURES` 才暫停並告警。

## Telegram bot 與授權（`app/bot.py`）
- 互動式：指令會出現在輸入框旁選單；`/track /untrack /interval /status /allow` 都是**多步驟對話**（`ConversationHandler`），先下指令再輸入內容，**30 秒逾時自動取消**（需 `python-telegram-bot[job-queue]`，已在 requirements）。
- `/untrack /interval /status` 會**先列出清單**再請使用者輸入編號。
- `/status`：顯示狀態 + 現價/最高/最低 + 價格走勢圖 + 漲跌紀錄。走勢圖用 `price_history` 畫（`app/charts.py`，matplotlib step 圖，圖內只用英數避免中文字型亂碼，商品名放 caption），`reply_photo` 直接送 PNG bytes；歷史不足 2 筆則只回文字。
- **授權守門**：`_auth_guard`（`TypeHandler`，`group=-1`）先於所有指令執行。
  - `/start` 一律放行 → 只記錄 `telegram_id`+`username`（每次更新最新），**不回應**。
  - 其餘指令：未授權者**完全靜默忽略**（不回訊息，只記 log）。
- **「已授權」= 任一**：① `.env` `ADMIN_IDS`（管理員）② `.env` `ALLOWED_USER_IDS`（靜態）③ DB `users.is_whitelisted`（管理員用 `/allow` 動態開通，免重啟）。判定見 `_authorized()` 與 `settings.authorized_id_set`。
- **管理員指令**（`/allow`、`/users`、`/pending`）只在管理員自己的選單顯示（`BotCommandScopeChat`），且 handler 內再次驗證 `admin_id_set`。`/allow` 開通後會立即私訊對方 `WELCOME_TEXT`。
- 改動 `.env` 的 `ADMIN_IDS` 後需重啟 `bot` 讓 `_post_init` 重設選單。

## 資料模型（`app/models.py`）
- `users`：`telegram_id`、`username`、`is_admin`、`is_whitelisted`（動態白名單）
- `tracked_products`：`status`、`check_interval_sec`、`consecutive_failures`、`current_price`…
- `price_history`：**價格或上下架狀態變動時**才記錄一筆（非每次檢查；首次取得價格也會記）
- `unsupported_requests`：管理員待辦（三層都失敗的網域）

> 新增/變更欄位：`init_db`（`create_all`）**不會**修改既有資料表，需用 Alembic 或手動 `ALTER TABLE`。

## 常用指令
```bash
# 跑分層萃取管線看結果（驗證 adapter 是否生效）
python -m app.admin test "<url>"
# 待新增爬蟲清單 / 標記完成 / 已註冊 adapter 網域
python -m app.admin pending
python -m app.admin resolve <domain>
python -m app.admin domains

# 測試（網路測試預設略過）
pytest -q
pytest -q --run-network        # 含需要連外網的測試

# 改完程式後重新部署（程式 COPY 進映像，需 rebuild）
docker compose up -d --build bot       # 或 worker / beat
```

## 慣例
- 全專案使用**同步** SQLAlchemy；非同步的 bot 以 `asyncio.to_thread` 呼叫 DB 函式。
- 萃取管線是 async；Celery 任務內用 `asyncio.run(extract_price(url))`。
- adapter / 解析器一律回傳 `ExtractionResult`；價格清掉貨幣符號與千分位逗號再轉 `float`。
- **執行時不可呼叫外部 LLM API。**

## 目錄
```
app/
  bot.py            Telegram 指令、對話流程、白名單守門
  tasks.py          Celery beat + check_product（diff/提醒/不支援流程）
  alerts.py         發送 Telegram 訊息
  admin.py          管理 CLI（test/pending/resolve/domains）
  config.py         設定（含 ADMIN_IDS / ALLOWED_USER_IDS 解析與授權判定）
  extraction/
    pipeline.py     分層調度
    structured.py   結構化資料解析（L0/L1）
    browser.py      Playwright
    context.py      FetchContext + build_context
    antibot.py      限流/UA/proxy
    adapters/       base / registry / _template / <各網站>.py
.claude/skills/add-scraper/SKILL.md   新增爬蟲的引導流程
```
