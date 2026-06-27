"""快速建立資料表（開發用）。

正式環境建議改用 Alembic migration（見 alembic/ 與 README）。
"""
from __future__ import annotations

from app.db import engine
from app.models import Base


def main() -> None:
    Base.metadata.create_all(engine)
    print("資料表已建立完成。")


if __name__ == "__main__":
    main()
