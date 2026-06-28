"""管理員 CLI 工具，供 /add-scraper skill 與手動操作使用。

用法：
  python -m app.admin test <url>        # 跑分層萃取管線，印出結果（驗證 adapter）
  python -m app.admin pending           # 列出待新增爬蟲的網域
  python -m app.admin resolve <domain>  # 將某網域的待辦標記為已處理
  python -m app.admin domains           # 列出已註冊的 adapter 網域
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt

from sqlalchemy import select

from app.db import session_scope
from app.models import ProductStatus, RequestStatus, TrackedProduct, UnsupportedRequest


def cmd_test(url: str) -> None:
    from app.extraction.pipeline import extract_price

    result = asyncio.run(extract_price(url))
    print("萃取結果：")
    for k, v in dataclasses.asdict(result).items():
        print(f"  {k}: {v}")
    if not result.has_price:
        print("\n→ 未取得價格：此網站需要新增專屬 adapter（見 /add-scraper）。")


def cmd_pending() -> None:
    with session_scope() as s:
        rows = (
            s.query(UnsupportedRequest)
            .filter(UnsupportedRequest.status == RequestStatus.PENDING)
            .order_by(UnsupportedRequest.created_at.desc())
            .all()
        )
        if not rows:
            print("沒有待新增的網站。")
            return
        for r in rows:
            print(f"[{r.domain}] {r.url}")


def cmd_resolve(domain: str) -> None:
    """標記待辦完成，並（1）重新啟用該網域被標為 unsupported 的商品、
    立即排一次檢查，（2）通知當初請求的使用者「現在已支援」。
    """
    from app.alerts import send_message
    from app.tasks import check_product  # 延遲 import，避免無 broker 環境載入失敗

    notify_ids: set[int] = set()
    reactivated: list[int] = []
    with session_scope() as s:
        reqs = (
            s.execute(
                select(UnsupportedRequest).where(
                    UnsupportedRequest.domain == domain,
                    UnsupportedRequest.status == RequestStatus.PENDING,
                )
            )
            .scalars()
            .all()
        )
        for r in reqs:
            r.status = RequestStatus.RESOLVED
            r.resolved_at = dt.datetime.now(dt.timezone.utc)
            if r.requested_by:
                notify_ids.add(r.requested_by)

        # 重新啟用此網域仍是 unsupported 的追蹤商品
        prods = (
            s.query(TrackedProduct)
            .filter(
                TrackedProduct.domain == domain,
                TrackedProduct.status == ProductStatus.UNSUPPORTED,
            )
            .all()
        )
        for p in prods:
            p.status = ProductStatus.ACTIVE
            p.consecutive_failures = 0
            reactivated.append(p.id)
            notify_ids.add(p.user.telegram_id)
        n_reqs = len(reqs)

    # 立即排一次檢查，讓使用者馬上拿到價格
    for pid in reactivated:
        check_product.delay(pid)

    # 通知當初請求/受影響的使用者
    for uid in notify_ids:
        send_message(
            uid,
            f"✅ 你先前追蹤的網站「{domain}」現在已支援自動追蹤價格了，"
            "系統會開始為你監控，並在價格變動時通知你。",
        )

    print(
        f"已處理 {n_reqs} 筆待辦；重新啟用 {len(reactivated)} 個商品；"
        f"通知 {len(notify_ids)} 位使用者。"
    )


def cmd_domains() -> None:
    from app.extraction.adapters.registry import registered_domains

    domains = registered_domains()
    if not domains:
        print("尚無任何專屬 adapter（全靠通用結構化資料層）。")
        return
    for d in domains:
        print(d)


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.admin")
    sub = parser.add_subparsers(dest="command", required=True)

    p_test = sub.add_parser("test", help="跑萃取管線")
    p_test.add_argument("url")

    sub.add_parser("pending", help="列出待新增爬蟲的網域")

    p_resolve = sub.add_parser("resolve", help="標記某網域待辦為已處理")
    p_resolve.add_argument("domain")

    sub.add_parser("domains", help="列出已註冊 adapter 網域")

    args = parser.parse_args()
    if args.command == "test":
        cmd_test(args.url)
    elif args.command == "pending":
        cmd_pending()
    elif args.command == "resolve":
        cmd_resolve(args.domain)
    elif args.command == "domains":
        cmd_domains()


if __name__ == "__main__":
    main()
