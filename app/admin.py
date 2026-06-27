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
from app.models import RequestStatus, UnsupportedRequest


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
    with session_scope() as s:
        rows = s.execute(
            select(UnsupportedRequest).where(
                UnsupportedRequest.domain == domain,
                UnsupportedRequest.status == RequestStatus.PENDING,
            )
        ).scalars().all()
        for r in rows:
            r.status = RequestStatus.RESOLVED
            r.resolved_at = dt.datetime.now(dt.timezone.utc)
        print(f"已將 {len(rows)} 筆 {domain} 的待辦標記為已處理。")


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
