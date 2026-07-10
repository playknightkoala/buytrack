"""Telegram bot：使用者貼網址追蹤、列表、設定間隔；管理員看待新增清單。

互動式設計：
- 指令會出現在輸入框旁的 menu。
- /track、/untrack、/interval、/status 採「先下指令、再輸入內容」的多步驟對話，
  30 秒未回應自動取消；/untrack、/interval、/status 會先列出清單方便挑選。

bot 為非同步；同步的 DB 操作以 ``asyncio.to_thread`` 包裝呼叫。
bot 不直接跑萃取，新增/重查都交給 Celery 的 check_product。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from telegram import (
    BotCommand,
    BotCommandScopeChat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from app.broadcast import broadcast_if_new, changelog_for
from app.config import settings
from app.db import session_scope
from app.extraction.context import domain_of
from app.sites import short_link, site_label
from app.version import __version__
from app.models import (
    PriceHistory,
    ProductStatus,
    RequestStatus,
    TrackedProduct,
    UnsupportedRequest,
    User,
)

_TZ = ZoneInfo("Asia/Taipei")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONVERSATION_TIMEOUT = 30  # 秒

# 對話狀態
(
    ASK_URL,
    ASK_ID,
    ASK_INTERVAL_SCOPE,
    ASK_INTERVAL_IDS,
    ASK_INTERVAL_MIN,
    ASK_STATUS_ID,
    ASK_ALLOW_ID,
) = range(7)

# 開通白名單後，傳給新使用者的歡迎訊息（也就是原本 /start 會回的內容）
WELCOME_TEXT = (
    "🎉 你已被開通，可以開始使用價格追蹤機器人了！\n\n"
    "點選輸入框旁的選單，或使用指令：\n"
    "/track — 新增追蹤（接著貼網址）\n"
    "/list — 我的追蹤清單\n"
    "/untrack — 取消追蹤\n"
    "/interval — 設定檢查頻率（分鐘／整點）\n"
    "/refresh — 立即重爬我追蹤的所有商品\n"
    "/status — 查看狀態與價格歷史\n"
    "/cancel — 取消目前操作"
)


# ----------------------- 同步 DB 操作 -----------------------

def _get_or_create_user(
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> int:
    with session_scope() as s:
        user = s.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                is_admin=telegram_id in settings.admin_id_set,
            )
            s.add(user)
            s.flush()
        else:
            # 名稱可能變更，每次更新為最新
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
        return user.id


def _list_all_users() -> list[dict]:
    with session_scope() as s:
        users = s.query(User).order_by(User.created_at.asc()).all()
        return [
            {
                "telegram_id": u.telegram_id,
                "username": u.username,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "is_admin": u.is_admin,
                "is_whitelisted": u.is_whitelisted,
            }
            for u in users
        ]


def _display_name(row: dict) -> str:
    """優先顯示 @username；沒有則用 first_name + last_name；都沒有才顯示「沒有任何名稱」。"""
    if row.get("username"):
        return f"@{row['username']}"
    full = " ".join(x for x in (row.get("first_name"), row.get("last_name")) if x).strip()
    return full or "(沒有任何名稱)"


def _is_whitelisted_db(telegram_id: int) -> bool:
    with session_scope() as s:
        u = s.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        return bool(u and u.is_whitelisted)


def _set_whitelisted(telegram_id: int) -> bool:
    """將使用者加入白名單；回傳是否為「本來不在白名單、這次才開通」。"""
    with session_scope() as s:
        u = s.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if u is None:
            s.add(
                User(
                    telegram_id=telegram_id,
                    is_admin=telegram_id in settings.admin_id_set,
                    is_whitelisted=True,
                )
            )
            return True
        was_allowed = u.is_whitelisted
        u.is_whitelisted = True
        return not was_allowed


def _add_product(telegram_id: int, url: str) -> tuple[int, bool]:
    """新增追蹤。回傳 (product_id, is_duplicate)。

    重複判定：同一使用者、正規化後相同的 URL（同網站不同商品不算重複）。
    若重複則不新增，回傳既有商品 id 與 True。
    """
    user_id = _get_or_create_user(telegram_id)
    target_key = _normalize_url(url)
    with session_scope() as s:
        existing = (
            s.query(TrackedProduct)
            .filter(TrackedProduct.user_id == user_id)
            .all()
        )
        for p in existing:
            if _normalize_url(p.url) == target_key:
                return p.id, True
        product = TrackedProduct(
            user_id=user_id,
            url=url,
            domain=domain_of(url),
            status=ProductStatus.ACTIVE,
        )
        s.add(product)
        s.flush()
        return product.id, False


def _list_products(telegram_id: int) -> list[dict]:
    with session_scope() as s:
        user = s.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None:
            return []
        return [
            {
                "id": p.id,
                "title": p.title,
                "url": p.url,
                "domain": p.domain,
                "price": p.current_price,
                "currency": p.currency,
                "status": p.status.value,
                "last_checked_at": p.last_checked_at,
                "schedule_mode": p.schedule_mode,
                "check_interval_sec": p.check_interval_sec,
            }
            for p in sorted(user.products, key=lambda x: x.id)
        ]


def _remove_product(telegram_id: int, product_id: int) -> bool:
    with session_scope() as s:
        product = (
            s.query(TrackedProduct)
            .join(User)
            .filter(TrackedProduct.id == product_id, User.telegram_id == telegram_id)
            .one_or_none()
        )
        if product is None:
            return False
        s.delete(product)
        return True


def _set_schedule(
    telegram_id: int,
    mode: str,
    minutes: int | None = None,
    product_ids: list[int] | None = None,
) -> int:
    """設定排程並喚醒因失敗暫停的商品。

    product_ids=None 表示套用該使用者所有商品；否則只套用清單內（且屬於該使用者）的商品。
    回傳實際更新的商品數。
    """
    with session_scope() as s:
        user = s.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None:
            return 0
        products = list(user.products)
        if product_ids is not None:
            idset = set(product_ids)
            products = [p for p in products if p.id in idset]
        for p in products:
            p.schedule_mode = mode
            if mode == "interval" and minutes:
                p.check_interval_sec = max(60, minutes * 60)
            if p.status == ProductStatus.ERROR:
                p.status = ProductStatus.ACTIVE
                p.consecutive_failures = 0
        return len(products)


def _manual_refresh(telegram_id: int) -> tuple[str, object]:
    """手動重爬。回傳 (kind, payload)：
    'ok'→payload=商品 id 清單；'cooldown'→payload=剩餘秒數；'empty'→payload=None。
    """
    with session_scope() as s:
        user = s.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None or not user.products:
            return "empty", None
        now = dt.datetime.now(dt.timezone.utc)
        cd = settings.manual_refresh_cooldown_sec
        last = user.last_manual_refresh_at
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed < cd:
                return "cooldown", int(cd - elapsed)
        user.last_manual_refresh_at = now
        return "ok", [p.id for p in user.products]


def _price_history(telegram_id: int, product_id: int) -> dict | None:
    with session_scope() as s:
        product = (
            s.query(TrackedProduct)
            .join(User)
            .filter(TrackedProduct.id == product_id, User.telegram_id == telegram_id)
            .one_or_none()
        )
        if product is None:
            return None
        rows = (
            s.query(PriceHistory)
            .filter(PriceHistory.product_id == product_id, PriceHistory.price.isnot(None))
            .order_by(PriceHistory.checked_at.asc())
            .all()
        )
        return {
            "title": product.title or product.url,
            "url": product.url,
            "domain": product.domain,
            "status": product.status.value,
            "currency": product.currency,
            "current": product.current_price,
            "last_checked_at": product.last_checked_at,
            "schedule_mode": product.schedule_mode,
            "check_interval_sec": product.check_interval_sec,
            "points": [(r.checked_at, r.price) for r in rows],
        }


def _list_pending() -> list[dict]:
    with session_scope() as s:
        rows = (
            s.query(UnsupportedRequest)
            .filter(UnsupportedRequest.status == RequestStatus.PENDING)
            .order_by(UnsupportedRequest.created_at.desc())
            .limit(50)
            .all()
        )
        return [{"domain": r.domain, "url": r.url} for r in rows]


# ----------------------- 工具 -----------------------

def _valid_url(text: str) -> bool:
    parts = urlsplit(text)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


# 行銷/追蹤用的 query 參數（比對重複時忽略，避免同商品因連結帶不同 utm 而漏判）
_TRACKING_KEYS = {
    "gclid", "fbclid", "yclid", "msclkid", "igshid", "_ga",
    "gbraid", "wbraid", "mc_cid", "mc_eid", "dclid",
}


def _is_tracking_param(key: str) -> bool:
    k = key.lower()
    return k.startswith("utm_") or k in _TRACKING_KEYS


def _normalize_url(url: str) -> str:
    """正規化 URL 作為「是否為同一商品」的比較鍵（不影響實際抓取用的原始 URL）。

    - host 轉小寫、去掉開頭 www.
    - 移除追蹤參數、其餘 query 依字母排序
    - 去掉結尾斜線與 fragment
    （注意：保留其他 query 參數，因 momo 等站以 query 識別商品）
    """
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    netloc = f"{host}:{p.port}" if p.port else host
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not _is_tracking_param(k)
    ]
    query_pairs.sort()
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), netloc, path, urlencode(query_pairs), ""))


def _enqueue_check(product_id: int) -> None:
    from app.tasks import check_product  # 延遲 import 避免啟動時相依 broker

    check_product.delay(product_id)


def _format_products(products: list[dict]) -> str:
    """組出 /list 內容（HTML 模式：文字已跳脫；網址過長會縮短顯示、仍可點擊）。"""
    lines = []
    for p in products:
        price = "—"
        if p["price"] is not None:
            price = f"{p['price']:,.0f} {p['currency'] or ''}".strip()
        title = html.escape(p["title"]) if p["title"] else "（尚未取得商品名稱）"
        site = html.escape(site_label(p.get("domain")))
        checked = _fmt_checked(p.get("last_checked_at"))
        freq = _fmt_freq(p.get("schedule_mode"), p.get("check_interval_sec"))
        lines.append(
            f"#{p['id']}｜{site}｜{p['status']}｜{price}\n{title}\n"
            f"🔗 {short_link(p['url'])}\n"
            f"🕒 最近爬文：{checked}｜⏱ {freq}"
        )
    return "\n\n".join(lines)


async def _show_list_or_end(update: Update, uid: int) -> list[dict] | None:
    """列出清單；若沒有任何商品則回覆提示並回傳 None。"""
    products = await asyncio.to_thread(_list_products, uid)
    if not products:
        await update.message.reply_text("目前沒有追蹤任何商品。用 /track 新增。")
        return None
    await update.message.reply_text(
        _format_products(products), parse_mode="HTML", disable_web_page_preview=True
    )
    return products


_HINT = "（30 秒未回應將自動取消，或輸入 /cancel 取消）"


def _fmt_checked(checked_at) -> str:
    """最近檢查時間（轉台北時間顯示）。"""
    if checked_at is None:
        return "尚未檢查"
    return checked_at.astimezone(_TZ).strftime("%m/%d %H:%M")


def _fmt_freq(mode: str | None, interval_sec: int | None) -> str:
    if mode == "hourly":
        return "每整點"
    minutes = (interval_sec or 0) // 60
    return f"每 {minutes} 分鐘"


def _fmt_remain(seconds: int) -> str:
    m, s = divmod(max(0, seconds), 60)
    return f"{m} 分 {s} 秒" if m else f"{s} 秒"


def _fmt_price(price: float | None, currency: str | None) -> str:
    if price is None:
        return "—"
    return f"{price:,.0f} {currency or ''}".strip()


def _format_changes(points: list[tuple], currency: str | None, limit: int = 12) -> list[str]:
    """從歷史點位整理出「價格有變動」的事件，最新在前。"""
    events: list[tuple] = []
    prev: float | None = None
    for checked_at, price in points:
        if prev is None or price != prev:
            delta = None if prev is None else price - prev
            events.append((checked_at, price, delta))
            prev = price
    lines = []
    for checked_at, price, delta in reversed(events[-limit:]):
        ts = checked_at.astimezone(_TZ).strftime("%Y-%m-%d %H:%M")
        if delta is None:
            mark = ""
        elif delta > 0:
            mark = f"  🔺{abs(delta):,.0f}"
        elif delta < 0:
            mark = f"  🔻{abs(delta):,.0f}"
        else:
            mark = ""
        lines.append(f"{ts}  {_fmt_price(price, currency)}{mark}")
    return lines


# ----------------------- 白名單守門 -----------------------

async def _authorized(telegram_id: int) -> bool:
    """env 設定的管理員/白名單，或 DB 動態白名單，皆視為已授權。"""
    if telegram_id in settings.authorized_id_set:
        return True
    return await asyncio.to_thread(_is_whitelisted_db, telegram_id)


def _is_start_command(text: str | None) -> bool:
    if not text:
        return False
    head = text.strip().split()[0].split("@")[0]
    return head == "/start"


async def _auth_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if user is None:
        raise ApplicationHandlerStop

    # /start 一律放行（由 start handler 記錄、且不回應），不受白名單限制
    if msg is not None and _is_start_command(msg.text):
        return

    if await _authorized(user.id):
        return

    # 未開通者：完全不回應，直接靜默忽略
    logger.info("忽略未授權使用者：%s", user.id)
    raise ApplicationHandlerStop


# ----------------------- 簡單指令 -----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # 依需求：/start 只記錄使用者（含 username / 姓名），不回應任何訊息。
    user = update.effective_user
    await asyncio.to_thread(
        _get_or_create_user, user.id, user.username, user.first_name, user.last_name
    )
    logger.info("/start 記錄使用者：%s (@%s)", user.id, user.username)


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    products = await asyncio.to_thread(_list_products, update.effective_user.id)
    if not products:
        await update.message.reply_text("目前沒有追蹤任何商品。用 /track 新增。")
        return
    await update.message.reply_text(
        _format_products(products), parse_mode="HTML", disable_web_page_preview=True
    )


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in settings.admin_id_set:
        await update.message.reply_text("此指令僅限管理員。")
        return
    rows = await asyncio.to_thread(_list_all_users)
    if not rows:
        await update.message.reply_text("目前沒有任何使用者紀錄。")
        return
    lines = [f"目前使用者（共 {len(rows)} 位）："]
    for r in rows:
        if r["is_admin"]:
            tag = " 👑管理員"
        elif r["is_whitelisted"]:
            tag = " ✅已開通"
        else:
            tag = " ⛔未開通"
        lines.append(f"• {r['telegram_id']} {_display_name(r)}{tag}")
    await update.message.reply_text("\n".join(lines))


async def refresh_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kind, payload = await asyncio.to_thread(_manual_refresh, update.effective_user.id)
    if kind == "empty":
        await update.message.reply_text("目前沒有追蹤任何商品。用 /track 新增。")
        return
    if kind == "cooldown":
        await update.message.reply_text(
            f"⏳ 剛剛才手動重爬過，請 {_fmt_remain(int(payload))} 後再試"
            f"（每 {settings.manual_refresh_cooldown_sec // 60} 分鐘限一次）。"
        )
        return
    ids = payload
    for pid in ids:
        _enqueue_check(pid)
    await update.message.reply_text(
        f"🔄 已手動觸發重爬 {len(ids)} 個商品，有變動會再通知你。"
    )


async def version_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    notes = changelog_for(__version__)
    text = f"目前版本：v{__version__}"
    if notes:
        text += f"\n\n{notes}"
    await update.message.reply_text(text)


async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in settings.admin_id_set:
        await update.message.reply_text("此指令僅限管理員。")
        return
    rows = await asyncio.to_thread(_list_pending)
    if not rows:
        await update.message.reply_text("目前沒有待新增的網站。")
        return
    lines = ["待新增爬蟲（用 Claude CLI：/add-scraper <網址>）："]
    for r in rows:
        lines.append(f"• {r['domain']}\n  {r['url']}")
    await update.message.reply_text("\n".join(lines), disable_web_page_preview=True)


# ----------------------- 對話：共用收尾 -----------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("已取消目前操作。")
    return ConversationHandler.END


async def on_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat = update.effective_chat if update else None
    if chat is not None:
        await context.bot.send_message(chat.id, "⏱ 已逾時，操作自動取消。")
    return ConversationHandler.END


# ----------------------- 對話：/track -----------------------

async def track_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(f"請貼上要追蹤的商品網址。\n{_HINT}")
    return ASK_URL


async def track_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = update.message.text.strip()
    if not _valid_url(url):
        await update.message.reply_text(f"這不是有效的 http(s) 網址，請重貼。\n{_HINT}")
        return ASK_URL
    product_id, is_duplicate = await asyncio.to_thread(
        _add_product, update.effective_user.id, url
    )
    if is_duplicate:
        await update.message.reply_text(
            f"⚠️ 你已經在追蹤這個商品了（編號 #{product_id}），不需重複加入。\n"
            "可用 /status 查看，或 /list 看全部。"
        )
        return ConversationHandler.END
    _enqueue_check(product_id)
    await update.message.reply_text(
        f"已加入追蹤（編號 {product_id}），正在抓取首次價格，稍後通知你…"
    )
    return ConversationHandler.END


# ----------------------- 對話：/untrack -----------------------

async def untrack_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _show_list_or_end(update, update.effective_user.id) is None:
        return ConversationHandler.END
    await update.message.reply_text(f"請輸入要「取消追蹤」的編號。\n{_HINT}")
    return ASK_ID


async def untrack_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lstrip("#")
    if not text.isdigit():
        await update.message.reply_text(f"請輸入數字編號。\n{_HINT}")
        return ASK_ID
    ok = await asyncio.to_thread(_remove_product, update.effective_user.id, int(text))
    await update.message.reply_text("已取消追蹤。" if ok else "找不到該編號的商品。")
    return ConversationHandler.END


# ----------------------- 對話：/status -----------------------

async def status_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _show_list_or_end(update, update.effective_user.id) is None:
        return ConversationHandler.END
    await update.message.reply_text(f"請輸入要查看的編號（狀態 + 價格歷史）。\n{_HINT}")
    return ASK_STATUS_ID


async def status_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lstrip("#")
    if not text.isdigit():
        await update.message.reply_text(f"請輸入數字編號。\n{_HINT}")
        return ASK_STATUS_ID
    data = await asyncio.to_thread(_price_history, update.effective_user.id, int(text))
    if data is None:
        await update.message.reply_text("找不到該編號的商品。")
        return ConversationHandler.END

    points = data["points"]
    currency = data["currency"]
    lines = [
        f"#{int(text)}　📊 {data['title']}",
        f"購物網：{site_label(data.get('domain'))}",
        f"狀態：{data['status']}",
        f"現在：{_fmt_price(data['current'], currency)}",
        f"🕒 最近爬文：{_fmt_checked(data.get('last_checked_at'))}",
        f"⏱ 頻率：{_fmt_freq(data.get('schedule_mode'), data.get('check_interval_sec'))}",
    ]
    if points:
        ys = [p[1] for p in points]
        lines.append(f"最高：{_fmt_price(max(ys), currency)}　最低：{_fmt_price(min(ys), currency)}")
    lines.append(data["url"])
    summary = "\n".join(lines)

    if len(points) >= 2:
        from app.charts import render_price_history  # 延遲 import，避免啟動載入 matplotlib

        png = await asyncio.to_thread(render_price_history, points, currency)
        await update.message.reply_photo(photo=png, caption=summary)
    else:
        await update.message.reply_text(summary, disable_web_page_preview=True)

    changes = _format_changes(points, currency)
    if changes:
        await update.message.reply_text(
            "漲跌紀錄（最新在前）：\n" + "\n".join(changes),
            disable_web_page_preview=True,
        )
    return ConversationHandler.END


# ----------------------- 對話：/interval（按鈕選項式）-----------------------

# 頻率預設選項（分鐘）
_FREQ_PRESETS = [
    [("15 分", 15), ("30 分", 30), ("1 小時", 60)],
    [("3 小時", 180), ("6 小時", 360), ("12 小時", 720)],
    [("24 小時", 1440)],
]


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def _scope_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_btn("全部商品", "scope:all"), _btn("指定商品", "scope:specific")],
            [_btn("✖ 取消", "iv:cancel")],
        ]
    )


def _ids_keyboard(products: list[tuple[int, str]], selected: set[int]) -> InlineKeyboardMarkup:
    rows = [
        [_btn(f"{'✅' if pid in selected else '▫️'} {label}", f"tg:{pid}")]
        for pid, label in products
    ]
    rows.append([_btn("✔ 完成", "ids:done"), _btn("✖ 取消", "iv:cancel")])
    return InlineKeyboardMarkup(rows)


def _freq_keyboard() -> InlineKeyboardMarkup:
    rows = [[_btn(t, f"fq:{m}") for t, m in row] for row in _FREQ_PRESETS]
    rows.append([_btn("每整點", "fq:hourly")])
    rows.append([_btn("✖ 取消", "iv:cancel")])
    return InlineKeyboardMarkup(rows)


def _short_label(p: dict) -> str:
    title = p.get("title") or p.get("url") or ""
    return f"#{p['id']} {title[:16]}"


async def interval_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "要調整哪些商品的檢查頻率？", reply_markup=_scope_keyboard()
    )
    return ASK_INTERVAL_SCOPE


async def interval_scope_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if q.data == "scope:all":
        context.user_data["interval_target"] = "all"
        await q.edit_message_text("範圍：全部商品")
        await q.message.reply_text("請選擇檢查頻率：", reply_markup=_freq_keyboard())
        return ASK_INTERVAL_MIN

    products = await asyncio.to_thread(_list_products, q.from_user.id)
    if not products:
        await q.edit_message_text("目前沒有追蹤任何商品。用 /track 新增。")
        return ConversationHandler.END
    context.user_data["interval_products"] = [(p["id"], _short_label(p)) for p in products]
    context.user_data["interval_sel"] = set()
    await q.edit_message_text(
        "請選擇要調整的商品（可多選），選好按「完成」：",
        reply_markup=_ids_keyboard(context.user_data["interval_products"], set()),
    )
    return ASK_INTERVAL_IDS


async def interval_toggle_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[1])
    sel: set[int] = context.user_data.setdefault("interval_sel", set())
    sel.discard(pid) if pid in sel else sel.add(pid)
    await q.edit_message_reply_markup(
        reply_markup=_ids_keyboard(context.user_data.get("interval_products", []), sel)
    )
    return ASK_INTERVAL_IDS


async def interval_ids_done_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    sel = context.user_data.get("interval_sel") or set()
    if not sel:
        await q.answer("尚未選擇任何商品", show_alert=True)
        return ASK_INTERVAL_IDS
    await q.answer()
    context.user_data["interval_target"] = list(sel)
    await q.edit_message_text(f"已選擇 {len(sel)} 個商品。")
    await q.message.reply_text("請選擇檢查頻率：", reply_markup=_freq_keyboard())
    return ASK_INTERVAL_MIN


async def interval_freq_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    target = context.user_data.get("interval_target")
    if target is None:
        await q.edit_message_text("操作已失效，請重新使用 /interval。")
        return ConversationHandler.END
    data = q.data.split(":")[1]
    if data == "hourly":
        mode, minutes, freq_desc = "hourly", None, "每小時整點"
    else:
        mode, minutes = "interval", int(data)
        freq_desc = f"每 {minutes} 分鐘"
    product_ids = None if target == "all" else target
    n = await asyncio.to_thread(_set_schedule, q.from_user.id, mode, minutes, product_ids)
    scope_desc = "全部商品" if target == "all" else f"{n} 個指定商品"
    context.user_data.clear()
    await q.edit_message_text(f"✅ 已將{scope_desc}設為{freq_desc}檢查。")
    return ConversationHandler.END


async def interval_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await q.edit_message_text("已取消。")
    return ConversationHandler.END


# ----------------------- 對話：/allow（管理員開通白名單）-----------------------

async def allow_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in settings.admin_id_set:
        await update.message.reply_text("此指令僅限管理員。")
        return ConversationHandler.END
    rows = await asyncio.to_thread(_list_all_users)
    pending = [r for r in rows if not r["is_admin"] and not r["is_whitelisted"]]
    if pending:
        lines = ["尚未開通的使用者："]
        for r in pending:
            lines.append(f"• {r['telegram_id']} {_display_name(r)}")
        await update.message.reply_text("\n".join(lines))
    else:
        await update.message.reply_text("（目前沒有未開通的使用者，仍可手動輸入任意 ID）")
    await update.message.reply_text(f"請輸入要開通的使用者 ID。\n{_HINT}")
    return ASK_ALLOW_ID


async def allow_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.lstrip("-").isdigit():
        await update.message.reply_text(f"請輸入數字 ID。\n{_HINT}")
        return ASK_ALLOW_ID
    target_id = int(text)
    newly = await asyncio.to_thread(_set_whitelisted, target_id)

    # 傳送原本 /start 會給的歡迎訊息給該使用者
    dm_ok = True
    try:
        await context.bot.send_message(target_id, WELCOME_TEXT)
    except Exception:
        dm_ok = False
        logger.warning("無法私訊使用者 %s（可能尚未對機器人 /start）", target_id)

    if not newly:
        note = "（該使用者原本就已在白名單）"
    elif dm_ok:
        note = "已私訊通知對方。"
    else:
        note = "但無法私訊對方——對方需先對機器人送一次 /start，才能收到訊息。"
    await update.message.reply_text(f"✅ 已開通 {target_id}。{note}")
    return ConversationHandler.END


# ----------------------- 組裝 -----------------------

def _conversation(entry_cmd: str, entry_cb, states: dict) -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler(entry_cmd, entry_cb)],
        states={
            **states,
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, on_timeout)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=CONVERSATION_TIMEOUT,
        allow_reentry=True,
    )


_TEXT = filters.TEXT & ~filters.COMMAND

COMMANDS = [
    BotCommand("track", "新增追蹤商品"),
    BotCommand("list", "我的追蹤清單"),
    BotCommand("untrack", "取消追蹤"),
    BotCommand("interval", "設定檢查頻率（分鐘／整點）"),
    BotCommand("refresh", "立即重爬我追蹤的所有商品"),
    BotCommand("status", "查看狀態與價格歷史"),
    BotCommand("version", "查看版本與更新內容"),
    BotCommand("cancel", "取消目前操作"),
]


async def _post_init(app: Application) -> None:
    logger.info("Bot 版本 v%s 啟動", __version__)
    # 一般使用者選單
    await app.bot.set_my_commands(COMMANDS)
    # 管理員額外提供 /pending（以聊天室範圍設定，不影響其他人）
    admin_commands = COMMANDS + [
        BotCommand("allow", "開通使用者白名單（管理員）"),
        BotCommand("users", "列出所有使用者（管理員）"),
        BotCommand("pending", "待新增爬蟲清單（管理員）"),
    ]
    for admin_id in settings.admin_id_set:
        try:
            await app.bot.set_my_commands(
                admin_commands, scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception:
            logger.warning("設定管理員指令選單失敗：%s", admin_id)

    # 若目前版本尚未公告過，推播改版資訊給已開通使用者（DB 記錄避免重複）
    try:
        await asyncio.to_thread(broadcast_if_new)
    except Exception:
        logger.exception("版本公告推播失敗")


def build_application() -> Application:
    if not settings.telegram_bot_token:
        raise RuntimeError("未設定 TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(settings.telegram_bot_token).post_init(_post_init).build()

    # 白名單守門：先於所有指令執行（/start 不受限）
    app.add_handler(TypeHandler(Update, _auth_guard), group=-1)
    if not settings.admin_id_set:
        logger.warning(
            "未設定 ADMIN_IDS：將沒有人能使用受限指令或開通白名單，請於 .env 設定。"
        )

    # 簡單指令
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("refresh", refresh_cmd))
    app.add_handler(CommandHandler("version", version_cmd))
    app.add_handler(CommandHandler("pending", pending_cmd))
    app.add_handler(CommandHandler("users", users_cmd))

    # 多步驟對話
    app.add_handler(_conversation("track", track_start, {ASK_URL: [MessageHandler(_TEXT, track_url)]}))
    app.add_handler(_conversation("untrack", untrack_start, {ASK_ID: [MessageHandler(_TEXT, untrack_id)]}))
    app.add_handler(_conversation("status", status_start, {ASK_STATUS_ID: [MessageHandler(_TEXT, status_id)]}))
    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("interval", interval_start)],
            states={
                ASK_INTERVAL_SCOPE: [
                    CallbackQueryHandler(interval_scope_cb, pattern="^scope:")
                ],
                ASK_INTERVAL_IDS: [
                    CallbackQueryHandler(interval_toggle_cb, pattern="^tg:"),
                    CallbackQueryHandler(interval_ids_done_cb, pattern="^ids:done$"),
                ],
                ASK_INTERVAL_MIN: [
                    CallbackQueryHandler(interval_freq_cb, pattern="^fq:")
                ],
                ConversationHandler.TIMEOUT: [
                    MessageHandler(filters.ALL, on_timeout),
                    CallbackQueryHandler(on_timeout),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(interval_cancel_cb, pattern="^iv:cancel$"),
            ],
            conversation_timeout=CONVERSATION_TIMEOUT,
            allow_reentry=True,
        )
    )
    app.add_handler(_conversation("allow", allow_start, {ASK_ALLOW_ID: [MessageHandler(_TEXT, allow_id)]}))
    return app


def main() -> None:
    app = build_application()
    logger.info("Bot 啟動中…")
    app.run_polling()


if __name__ == "__main__":
    main()
