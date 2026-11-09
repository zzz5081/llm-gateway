"""Redis 第一次上手：验证中文没问题、把今天要用的命令各跑一遍。

跑法：
    python redis_demo.py
需要：Memurai（或别的 Redis）已在 localhost:6379 运行
"""

import redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

print("=== 0. 连上了吗 ===")
print("  ping ->", r.ping())

print()
print("=== 1. 中文到底能不能存（你刚才在 CLI 里失败的那个） ===")
r.set("demo:chinese", "钟京林")
got = r.get("demo:chinese")
print("  SET demo:chinese 钟京林")
print("  GET ->", repr(got))
print("  字节长度 ->", len(got.encode("utf-8")), "（UTF-8 下 3 个汉字 = 9 字节）")
print("  ★ 结论：Redis 存中文完全没问题，是 memurai-cli 的控制台编码不认")

print()
print("=== 2. string：计数（限流会用到） ===")
r.delete("demo:counter")
r.set("demo:counter", 0)
print("  连敲 5 次 INCR：", end=" ")
for _ in range(5):
    print(r.incr("demo:counter"), end=" ")
print()
print("  当前值 ->", r.get("demo:counter"), "（类型是 str，不是 int）")

print()
print("=== 3. 过期：数据会自己消失（Redis 的魔法） ===")
r.set("demo:tmp", "我会消失", ex=3)
print("  SET demo:tmp 我会消失 EX 3")
print("  TTL ->", r.ttl("demo:tmp"), "秒")
print("  GET ->", repr(r.get("demo:tmp")))
import time
time.sleep(3.2)
print("  等了 3 秒之后：")
print("  TTL ->", r.ttl("demo:tmp"), "（-2 = key 已经不存在）")
print("  GET ->", repr(r.get("demo:tmp")))

print()
print("=== 4. hash：一个对象（对比你项目里的 users 表一行） ===")
r.delete("demo:user:1")
r.hset("demo:user:1", mapping={"name": "钟京林", "age": 21, "city": "成都"})
print("  HGETALL ->", r.hgetall("demo:user:1"))
print("  HGET name ->", r.hget("demo:user:1", "name"))

print()
print("=== 5. 顺便看看 key 的命名 = 冒号分层 ===")
print("  ", r.keys("demo:*"))

# 清理
r.delete("demo:chinese", "demo:counter", "demo:tmp", "demo:user:1")
print()
print("（demo keys 已清理）")
