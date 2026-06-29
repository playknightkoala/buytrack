---
name: release
description: 發布新版本。當要「發版 / 出新版本 / release / 升版號 / 改版並通知使用者」時使用：bump app/version.py、更新 CHANGELOG.md、commit + push + 打 git tag、重建 bot；bot 啟動會自動把該版改版資訊推播給已開通使用者。
---

# 發布新版本（release）

本專案版本號採 SemVer（`vMAJOR.MINOR.PATCH`）。發版流程會：bump `app/version.py` → 在 `CHANGELOG.md` 新增該版區段 → commit + push + 打 tag → 重建 bot。bot 啟動時若偵測該版尚未公告，會讀 CHANGELOG 對應段落，**自動推播給已開通使用者**（白名單 + 管理員，見 `app/broadcast.py`），並記錄到 `announced_versions` 表避免重複。

## ⚠️ 發版前務必知道
- **發一個新版 = 會真的推播訊息給所有已開通使用者**。版號與 CHANGELOG 內容確定無誤、並向使用者確認後，才 push + 重建。
- 版本是 baked 進 Docker 映像：重建 bot **一定要 `--build`**，否則跑的是舊版號，不會觸發推播。
- CHANGELOG 該版段落會**原文推播**給使用者 → 用使用者看得懂的話描述，不要寫內部實作細節。

## 步驟

### 1. 盤點變更、決定版號
```bash
git fetch origin -q
git describe --tags --abbrev=0                              # 上一個 tag
git log "$(git describe --tags --abbrev=0)"..HEAD --oneline # 自上版以來的提交
git status --short                                          # 確認沒有未預期的未提交檔案
```
依變更性質決定 SemVer：破壞性變更→MAJOR；新增相容功能→MINOR；只有修正/小調整→PATCH。
若使用者已指定版號就用指定的。**先向使用者確認「版號 + 本次改版重點」再往下做**（因為會推播）。

### 2. bump 版號
編輯 `app/version.py`，把 `__version__` 改成新版號（如 `1.1.0`）。

### 3. 寫 CHANGELOG
在 `CHANGELOG.md` 最上方（說明文字之後、舊版區段之前）新增：
```markdown
## [1.1.0] - <date>
- 改版重點 1（使用者角度）
- 改版重點 2
```
日期用 `date +%F` 取得。重點可參考步驟 1 的 commit 清單，但要改寫成使用者語言。

### 4. commit + push
```bash
git add -A
git commit -m "release: v1.1.0"   # 結尾加 Co-Authored-By 行
git push origin main
```
（若直接推 main 被權限擋下，改推 feature 分支再開 PR 合併。）

### 5. 打 tag 並 push
```bash
git tag -a v1.1.0 -m "v1.1.0"
git push origin v1.1.0
```

### 6. 重建 bot（觸發自動推播）
```bash
docker compose up -d --build bot
```

### 7. 驗證
```bash
# 啟動日誌應出現「版本 vX.Y.Z 已推播給 N 位…」
docker compose logs --tail 15 bot 2>&1 | grep -E '版本|推播'
# DB 應記錄此版本
docker compose exec -T postgres psql -U buytrack -d buytrack -c \
  "SELECT * FROM announced_versions ORDER BY announced_at DESC LIMIT 3;"
```
- 若顯示「已公告過，略過推播」→ 版號沒變或已公告：確認 `app/version.py` 真的 bump 了、且重建有加 `--build`。
- 推播對象在 `app/broadcast.py` 的 `_recipients()`（預設：已開通使用者）。

## 完成後回報
向使用者回報：發布版號、git tag、推播送達人數、CHANGELOG 重點。
