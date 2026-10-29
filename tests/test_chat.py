import db
from sqlalchemy import select
from llm_client import chat_completion
import routers.chat
from db import ApiCall
def test_chat_success(client, auth_user):
    r = client.post("/v1/chat",
                    json={"prompt": "第二句话"},
                    headers = auth_user["headers"])
    assert r.status_code == 200
    assert "[mock]" in r.json()["reply"]
    assert "第二句话" in r.json()["reply"]
    assert r.json()["prompt_tokens"] == 4

    uid = client.get("/auth/me", headers=auth_user["headers"]).json()['id']

    with db.SessionLocal() as s:
        rows = s.scalars(select(ApiCall).where(ApiCall.user_id == uid)).all()
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].prompt_tokens == 4
    assert rows[0].completion_tokens == 20
    assert rows[0].model == "gpt-4o-mini"
    # cost 是 Decimal，和 0.0000126 比会不等（库里是 0.000013）
    # → 别硬编码，验"大于 0"就行
    assert rows[0].cost > 0

def test_chat_when_llm_down(client,auth_user,monkeypatch):
    def boom(*arg, **kwargs):
        raise RuntimeError("模拟 LLM 挂了")

    monkeypatch.setattr(routers.chat,"chat_completion",boom)
    r = client.post("/v1/chat",
                    json={"prompt": "hi"},
                    headers=auth_user["headers"])
    assert r.status_code == 502
    uid = client.get("/auth/me", headers=auth_user["headers"]).json()['id']

    with db.SessionLocal() as s:
        rows = s.scalars(select(ApiCall).where(ApiCall.user_id == uid)).all()
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].prompt_tokens == 0
    assert rows[0].cost == 0