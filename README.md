# buytrack — 購物網站價格追蹤 + Telegram 提醒

貼上商品網址即可追蹤價格，變動時用 Telegram 通知。多使用者、可擴充、本地 Docker 啟動。

## 特色
- **分層萃取管線**：多數網站靠結構化資料（JSON-LD / OpenGraph / microdata）免費取得價格，零專屬程式碼。
- **執行時不串 LLM**：不支援的網站會通知使用者並列入管理員待辦。
- **可擴充**：管理員用 Claude Code CLI（`/add-scraper <url>`）快速、一致地新增網站爬蟲。
- **白名單授權**：只有管理員/白名單使用者能用；可由管理員用指令即時開通。
- **互動式指令**：指令出現在輸入框旁選單，採「先下指令、再輸入內容」的多步驟對話，30 秒未回應自動取消。
- 反爬：per-domain 限流 + jitter、輪換 UA、選用 proxy、失敗退避。

## 快速開始
```bash
cp .env.example .env          # 填入 TELEGRAM_BOT_TOKEN、ADMIN_IDS（見下方）
docker compose up -d postgres redis
docker compose run --rm initdb       # 建立資料表
docker compose up -d bot worker beat
```
在 Telegram 對你的 bot 送 `/start`（任何人皆可，僅記錄不回應），管理員再用 `/allow` 開通使用者。

## 環境變數（`.env`）
| 變數 | 說明 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token（必填） |
| `ADMIN_IDS` | 逗號分隔的管理員 telegram id；自動納入白名單，可用管理指令 |
| `ALLOWED_USER_IDS` | 逗號分隔的靜態白名單（選用；另可用 `/allow` 動態開通） |
| `DATABASE_URL` / `REDIS_URL` | DB 與 Redis 連線 |
| `PROXY_POOL` | 逗號分隔的 proxy（選用） |
| `DEFAULT_CHECK_INTERVAL_SEC` | 預設每商品檢查間隔（預設 3600 秒＝1 小時） |
| `MIN_DOMAIN_INTERVAL_SEC` | 同網域兩次請求最小間隔（預設 8 秒，含 jitter） |
| `MAX_CONSECUTIVE_FAILURES` | 連續失敗幾次後暫停告警 |
| `ENQUEUE_PERIOD_SEC` | Beat 掃描到期商品的週期（預設 60 秒） |

> 查自己的 telegram id：對 `@userinfobot` 傳訊息。

## 指令
**一般使用者**（皆為多步驟對話，可隨時 `/cancel`，30 秒逾時自動取消）
- `/start` — 記錄你的 id 與 username（不回應，且不受白名單限制）
- `/track` — 新增追蹤（接著貼網址）
- `/list` — 我的追蹤清單
- `/untrack` — 先列清單，再輸入編號取消
- `/interval` — 先列清單，輸入編號 → 輸入分鐘數
- `/status` — 先列清單，再輸入編號查看狀態、價格走勢圖（含最高/最低）與漲跌紀錄
- `/watch` — 訂閱網站**目錄**（分類列表頁；支援 Cyberbiz/Shopify 系網站）：每日自動比對，
  有新品或調價時傳送 PDF 報告（新增區／調價區／完整目錄區）
- `/watchlist`、`/unwatch` — 查看／取消目錄訂閱

**管理員**（只在管理員自己的選單顯示）
- `/allow` — 開通使用者白名單；開通後立即私訊對方歡迎訊息
- `/users` — 列出所有使用者（id / username / 狀態：👑管理員、✅已開通、⛔未開通）
- `/pending` — 待新增爬蟲的網站清單

## 授權模型（白名單）
一個使用者「已授權」= 符合任一：
1. `.env` 的 `ADMIN_IDS`（管理員，永遠可用）
2. `.env` 的 `ALLOWED_USER_IDS`（靜態白名單）
3. 資料庫 `is_whitelisted=True`（由管理員 `/allow` 動態開通，免重啟）

`/start` 不受限（任何人可送，僅靜默記錄）；其餘指令對未授權者**完全不回應**。
典型流程：陌生人 `/start` → 管理員 `/users` 看到 ⛔未開通 → `/allow` 輸入其 id → 對方收到歡迎訊息、立即可用。

## 架構
- `bot`：Telegram 指令（python-telegram-bot, async；對話逾時需 job-queue extra）
- `worker` / `beat`：Celery 輪詢、價格 diff、提醒
- `postgres` / `redis`：資料與佇列/限流
- 萃取管線：`app/extraction/`（`pipeline` → adapter / 結構化 / Playwright）

詳見 [CLAUDE.md](CLAUDE.md)。

## 新增一個網站（管理員）
1. 使用者追蹤到不支援的網站時，會列入 `/pending`（或 `python -m app.admin pending`）。
2. 在專案目錄開 `claude`，執行 `/add-scraper <該網址>`，由 Claude Code 依 `.claude/skills/add-scraper/` 流程產生 adapter、寫測試、驗證。
3. adapter 放進 `app/extraction/adapters/` 即被自動掛載，重啟 worker 生效。

## 測試
```bash
pytest -q                 # 單元測試（不連網）
pytest -q --run-network   # 含端到端煙霧測試（需 BUYTRACK_TEST_URL）
```

## 資料庫 migration
快速開發用 `python -m app.init_db`（`create_all`，不會修改既有欄位）。
**新增欄位到既有資料庫**請用 Alembic，或手動 `ALTER TABLE`：
```bash
alembic revision --autogenerate -m "add column"
alembic upgrade head
```
