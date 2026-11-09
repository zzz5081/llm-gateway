"""LLM 回复缓存的测试。

对应 routers/chat.py 里的逻辑：
  · 只有 temperature == 0 才走缓存
  · 命中缓存时：cached=True，token 和 cost 都是 0，且【不写 api_calls】
"""

import secrets
from decimal import Decimal

import db
from sqlalchemy import select
from db import ApiCall


def test_chat_cache_hit(client, auth_user):
    """同一个 prompt + temperature=0，第二次应该命中缓存，且不记账"""
    # ★ 用唯一 prompt，避免撞上别的测试/上次运行留下的缓存
    p = "缓存测试_" + secrets.token_hex(4)

    # 第一次：未命中，正常调 LLM，写账
    r1 = client.post("/v1/chat", json={"prompt": p}, headers=auth_user["headers"])
    assert r1.status_code == 200
    assert r1.json()["cached"] is False
    assert r1.json()["prompt_tokens"] > 0
    assert Decimal(r1.json()["cost"]) > 0

    # 第二次：命中缓存
    r2 = client.post("/v1/chat", json={"prompt": p}, headers=auth_user["headers"])
    assert r2.status_code == 200
    assert r2.json()["cached"] is True
    assert r2.json()["prompt_tokens"] == 0        # 没消耗 token
    assert r2.json()["completion_tokens"] == 0
    assert Decimal(r2.json()["cost"]) == 0        # 没花钱
    assert r2.json()["reply"] == r1.json()["reply"]   # 回复一致

    # ★ 关键：第二次不记账，库里只应该有 1 条
    uid = client.get("/auth/me", headers=auth_user["headers"]).json()["id"]
    with db.SessionLocal() as s:
        rows = s.scalars(select(ApiCall).where(ApiCall.user_id == uid)).all()
    assert len(rows) == 1
    assert rows[0].cost > 0


def test_temperature_nonzero_not_cached(client, auth_user):
    """temperature > 0 时不该缓存：两次都不命中，且各记一笔账"""
    p = "温度测试_" + secrets.token_hex(4)

    r1 = client.post("/v1/chat", json={"prompt": p, "temperature": 1.0},
                     headers=auth_user["headers"])
    r2 = client.post("/v1/chat", json={"prompt": p, "temperature": 1.0},
                     headers=auth_user["headers"])

    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["cached"] is False
    assert r2.json()["cached"] is False          # ★ 两次都不该命中

    # 两次都调了 LLM，所以记了两笔账
    uid = client.get("/auth/me", headers=auth_user["headers"]).json()["id"]
    with db.SessionLocal() as s:
        rows = s.scalars(select(ApiCall).where(ApiCall.user_id == uid)).all()
    assert len(rows) == 2
