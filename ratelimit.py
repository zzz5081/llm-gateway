"""基于 Redis 的限流：固定窗口计数器。

为什么用 Redis 而不是 MySQL:
    MySQL 每次要 UPDATE 一行 → 高频下会把数据库打爆
    Redis 的 INCR 是内存里的原子操作 → 几乎零成本
"""
import os
import time
import redis

REDIS_HOST = os.environ.get("REDIS_HOST","localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT",6379))
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def allow(user_id: int, limit: int = 10, window: int = 60) -> tuple[bool, int]:
    """
    返回 (是否放行, 当前窗口内已用了多少次)

    ★ 桶号放在 key 里 —— 换窗口自动换 key，旧 key 自己过期，不需要手动清理
    """
    # TODO 1: 算桶号
    bucket = int(time.time()) // window
    # TODO 2: 拼 key
    key = f"rl:{user_id},{bucket}"
    # TODO 3: INCR
    n = r.incr(key)
    # TODO 4: 只在 n == 1 时 EXPIRE
    if n == 1:
        r.expire(key,window)
    # TODO 5: 返回 (n <= limit, n)
    return (n <= limit,n)