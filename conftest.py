import os
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# ★ 必须在 import main 之前设置：
#   llm_client.py 里的 LLM_MODE 是在【模块被 import 的那一刻】读进内存的，
#   之后再改环境变量它也不认（这就是为什么改 LLM_MODE 必须重启服务）。
#   测试永远跑 mock，不受 shell 里残留的 LLM_MODE=real 影响。
os.environ["LLM_MODE"] = "mock"

sys.path.insert(0, str(Path(__file__).parent))
from main import app
import secrets
import db
from sqlalchemy import text

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_redis():
    """
    每个测试开始前清掉 Redis 里的【缓存】和【限流计数】。

    ★ 为什么要这么做：
      缓存和限流计数都是「测试之外的状态」。不清掉会导致两类假结果：

      1. 缓存残留 → 请求命中缓存 → 【不调 LLM】
         → monkeypatch 注入的故障不会触发
         → test_chat_when_llm_down 会返回 200 而不是 502（测试名不副实）
         → 用量类测试也会因为"没写库"而失败

      2. 限流计数残留 → 累积到第 11 次 chat 调用就 429
         → 出现莫名其妙的失败

    → 这是「测试依赖外部状态」家族的第四类：
      ① 数据残留（MySQL）② 顺序依赖 ③ 环境残留（LLM_MODE）④ 缓存残留（Redis）
    """
    from ratelimit import r
    for pattern in ("cache:*", "rl:*"):
        keys = r.keys(pattern)
        if keys:
            r.delete(*keys)
    yield


@pytest.fixture
def temp_user(client,cleanup):
    name = "t_" + secrets.token_hex(5)
    cleanup.append(name)
    data = {'username':name,'password':"test12345"}
    r = client.post("/auth/register",json=data)
    assert r.status_code == 201,f"fixture 准备失败: {r.text}"
    return data

@pytest.fixture
def cleanup():
    names = []
    yield names
    with db.engine.begin() as conn:
        for n in names:
                        # ① 先删账本（外键 RESTRICT，顺序不能反）
            conn.execute(
                text(
                    "DELETE FROM api_calls WHERE user_id = "
                    "(SELECT id FROM users WHERE username = :u)"
                ),
                {"u": n},
            )
            # ② 再删用户
            conn.execute(text("DELETE FROM users WHERE username = :u"), {"u": n})

@pytest.fixture
def auth_user(client,cleanup):
    name = "t_" + secrets.token_hex(5)
    cleanup.append(name)
    data = {"username": name,"password":"test12345"}
    # ★ fixture 也要断言：不然后面 KeyError: 'access_token' 会把真正的失败原因藏起来
    reg = client.post("/auth/register",json=data)
    assert reg.status_code == 201, f"auth_user 注册失败: {reg.status_code} {reg.text}"
    r = client.post("/auth/login",json=data)
    assert r.status_code == 200, f"auth_user 登录失败: {r.status_code} {r.text}"
    token = r.json()["access_token"]
    return{
        "username": name,
        "headers": {"Authorization": f"Bearer {token}"}
    }

@pytest.fixture
def make_user(client,cleanup):
    def _make():
        name = "t_" + secrets.token_hex(5)
        cleanup.append(name)
        data = {"username": name ,"password": "test12345"}
        reg = client.post("/auth/register",json=data)
        assert reg.status_code == 201, f"make_user 注册失败: {reg.status_code} {reg.text}"
        r = client.post("/auth/login",json=data)
        assert r.status_code == 200, f"make_user 登录失败: {r.status_code} {r.text}"
        token = r.json()["access_token"]
        return {"username": name, "headers": {"Authorization": f"Bearer {token}"}}
    return _make

@pytest.fixture(autouse=True)
def clean_redis():
    """
    每个测试开始前清掉 Redis 里的【缓存】和【限流计数】。

    ★ 为什么要这么做：
      缓存和限流计数都是「测试之外的状态」。
      不清掉的话：
        · 上个测试/上次运行留下的缓存 → 本次请求命中缓存 → 不调 LLM
          → monkeypatch 注入的故障不会触发 → 测试名不副实
        · 限流计数累积 → 跑到第 11 个 chat 调用就 429 → 莫名其妙的失败
    """
    from ratelimit import r
    for pattern in ("cache:*", "rl:*"):
        keys = r.keys(pattern)
        if keys:
            r.delete(*keys)
    yield