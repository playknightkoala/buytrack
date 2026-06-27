---
name: add-scraper
description: 為「尚未支援」的購物網站新增價格爬蟲 adapter。當管理員提供一個無法自動追蹤價格的商品網址（或要處理 /pending、unsupported_requests 中的待辦網域）時使用。會檢查頁面、產生符合專案介面的 adapter、寫測試、跑通驗證並標記待辦完成。
---

# 新增網站爬蟲 adapter（add-scraper）

當使用者貼上的商品網址，三層自動萃取（專屬 adapter → 結構化資料 → Playwright 渲染）都拿不到價格時，系統會標記為「不支援」並記到 `unsupported_requests`。本 skill 引導你（Claude Code）半自動地補上該網站的專屬 adapter。

## 觸發與輸入
- `/add-scraper <商品網址>`：直接處理該網址。
- `/add-scraper`（不帶網址）：先跑 `python -m app.admin pending` 取出待辦，挑最新一筆的網址處理（並向使用者確認）。

## 界線（務必遵守）
- **不要在 adapter 程式碼裡呼叫任何外部 LLM API**。萃取必須是純解析邏輯（結構化資料 / DOM 選擇器）。
- **不要繞過反爬限流**：一律透過 `ctx`（FetchContext）取得頁面，不要自己 `httpx`/`requests` 另開連線。
- adapter 一定要回傳 `ExtractionResult`；拿不到價格回傳 `ExtractionResult.unsupported()`。
- 遵守專案型別與慣例（見根目錄 `CLAUDE.md`）。

## 步驟

### 1. 確認網域與重現問題
```bash
python -m app.admin test "<url>"
```
- 若輸出 `supported: True` 且有 price → 其實已可萃取（可能是當時暫時失敗或網站改版已修正）。確認後 `python -m app.admin resolve <domain>` 即可，**毋須**寫 adapter。
- 若 `未取得價格` → 繼續。

### 2. 檢查頁面是否其實有結構化資料（最省事）
很多站只是需要「渲染後」才有 JSON-LD/OG。先看渲染後 HTML 裡有沒有 `application/ld+json` 或 `og:price`：
```bash
python - <<'PY'
import asyncio
from app.extraction.context import build_context
async def main():
    async with build_context() as ctx:
        html = await ctx.fetch_rendered("<url>")
        import re
        print("has ld+json:", bool(re.search(r'application/ld\+json', html)))
        print("has og:price:", 'og:price' in html or 'product:price' in html)
        # 視需要把 html 存檔檢視： open("/tmp/page.html","w",encoding="utf-8").write(html)
asyncio.run(main())
PY
```
- 若有結構化資料但通用層沒抓到 → adapter 可以只負責「渲染後重用 `parse_structured`」，或先等待特定選擇器再解析。
- 若完全沒有 → 需要用 DOM 選擇器取價（步驟 3）。

### 3. 找出價格 / 標題 / 上下架的選擇器
用 Playwright 開頁面、檢視真實 DOM，定位價格元素的 CSS 選擇器（用 `app.admin test` 失敗的網址）。可在 `build_context()` 內用 `ctx.page(url)` 互動式試 `page.inner_text("選擇器")`。注意挑穩定的選擇器（語意化 class / data 屬性，避免雜湊化 class）。

### 4. 從樣板建立 adapter
- 複製 `app/extraction/adapters/_template.py` 成 `app/extraction/adapters/<domain>.py`（檔名用底線，如 `shopee_tw.py`）。
- 類別改名、填入 `domains`（例如 `["shopee.tw"]`，可含多個或母網域；子網域會自動比對）。
- 在 `extract()` 內：
  - 能重用結構化資料時：`html = await ctx.fetch_rendered(url, wait_selector="...")` 後 `return parse_structured(html, url, method_prefix="adapter:<domain>")`。
  - 需 DOM 取價時：`async with ctx.page(url, wait_selector=".price") as page:` 取出文字，自行 parse 成 `float`，回傳 `ExtractionResult(supported=True, price=..., currency="TWD", title=..., availability=..., method="adapter:<domain>")`。
- 價格字串記得清掉貨幣符號與千分位逗號再轉 `float`。

### 5. 寫測試
- 在 `tests/adapters/test_<domain>.py` 用真實網址寫一個測試（參考 `tests/adapters/test_pipeline_smoke.py` 的非同步寫法），斷言 `result.has_price` 為真、`price > 0`、`currency` 正確。
- 標記 `@pytest.mark.network`（會連外網），方便 CI 篩選。

### 6. 跑測試驗證
```bash
pytest tests/adapters/test_<domain>.py -q
# 或直接用管線端到端驗證：
python -m app.admin test "<url>"     # 這次應顯示 supported: True 且 method 以 adapter: 開頭
```
若仍失敗：回步驟 3 調整選擇器；若該站反爬擋住，於 adapter 內用 `wait_selector`、必要時在 `.env` 設定 `PROXY_POOL`。

### 7. 標記待辦完成
```bash
python -m app.admin resolve <domain>
```
adapter 檔案放進 `adapters/` 後會被 registry 自動探索掛載，**無需修改其他程式**，worker 重啟後即生效。

## 完成後回報
向管理員回報：新增了哪個 adapter、用哪種方式取價（結構化 / DOM）、測試是否通過、是否還有反爬風險。
