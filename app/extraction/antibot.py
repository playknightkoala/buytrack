"""反爬輔助：真實 headers、輪換 User-Agent、proxy 選擇、per-domain 限流。

限流以 Redis 實作「每個網域最小請求間隔 + jitter」，避免規律高頻請求被偵測。
"""
from __future__ import annotations

import random

import redis.asyncio as aioredis

from app.config import settings

# 一組常見的桌面瀏覽器 UA，輪換使用
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# 每個網域兩次請求之間的最小間隔（毫秒），含隨機 jitter 上限
_MIN_INTERVAL_MS = int(settings.min_domain_interval_sec * 1000)

# 原子化計算「還要等多久（毫秒）」並推進下一次允許時間
_RATE_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local interval = tonumber(ARGV[2])
local next_allowed = tonumber(redis.call('get', key) or '0')
local wait = 0
if now < next_allowed then
  wait = next_allowed - now
  next_allowed = next_allowed + interval
else
  next_allowed = now + interval
end
local ttl = (next_allowed - now) + interval + 1000
redis.call('set', key, next_allowed, 'PX', math.ceil(ttl))
return wait
"""


class AntiBot:
    def __init__(self, redis_url: str | None = None) -> None:
        self._redis = aioredis.from_url(redis_url or settings.redis_url)
        self._rate_script = self._redis.register_script(_RATE_LUA)

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        if extra:
            h.update(extra)
        return h

    def user_agent(self) -> str:
        return random.choice(USER_AGENTS)

    def pick_proxy(self) -> str | None:
        proxies = settings.proxies
        return random.choice(proxies) if proxies else None

    async def throttle(self, domain: str) -> float:
        """阻擋直到該網域可再次請求，回傳實際等待秒數。"""
        import asyncio
        import time

        now_ms = int(time.time() * 1000)
        wait_ms = int(
            await self._rate_script(keys=[f"rl:{domain}"], args=[now_ms, _MIN_INTERVAL_MS])
        )
        # 加上 0~40% 的 jitter，打散規律性
        jitter_ms = random.uniform(0, _MIN_INTERVAL_MS * 0.4)
        total_s = (wait_ms + jitter_ms) / 1000.0
        if total_s > 0:
            await asyncio.sleep(total_s)
        return total_s

    async def aclose(self) -> None:
        await self._redis.aclose()
