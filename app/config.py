"""集中式設定。所有環境變數從這裡讀取。"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram
    telegram_bot_token: str = ""
    admin_ids: str = ""  # 逗號分隔的 telegram user id（管理員）
    allowed_user_ids: str = ""  # 逗號分隔的白名單 telegram user id

    # 基礎設施
    database_url: str = "postgresql+psycopg://buytrack:buytrack@postgres:5432/buytrack"
    redis_url: str = "redis://redis:6379/0"

    # 反爬 / proxy
    proxy_pool: str = ""  # 逗號分隔

    # 輪詢
    default_check_interval_sec: int = 3600
    min_domain_interval_sec: float = 8.0
    max_consecutive_failures: int = 5
    enqueue_period_sec: int = 60
    manual_refresh_cooldown_sec: int = 300  # /refresh 每人冷卻時間

    # 萃取
    request_timeout_sec: float = 20.0
    render_timeout_sec: float = 30.0

    @staticmethod
    def _parse_ids(raw: str) -> set[int]:
        out: set[int] = set()
        for part in raw.split(","):
            part = part.strip()
            if part:
                try:
                    out.add(int(part))
                except ValueError:
                    continue
        return out

    @property
    def admin_id_set(self) -> set[int]:
        return self._parse_ids(self.admin_ids)

    @property
    def authorized_id_set(self) -> set[int]:
        """可使用機器人的 user id（白名單 ∪ 管理員）。"""
        return self._parse_ids(self.allowed_user_ids) | self.admin_id_set

    def is_authorized(self, user_id: int) -> bool:
        """白名單檢查。若白名單與管理員皆未設定 → 開放模式（回 True）。"""
        allowed = self.authorized_id_set
        if not allowed:
            return True
        return user_id in allowed

    @property
    def proxies(self) -> list[str]:
        return [p.strip() for p in self.proxy_pool.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
