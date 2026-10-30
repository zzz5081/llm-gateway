from decimal import Decimal
import routers.chat

def test_usage_for_new_user(client,auth_user):
    r = client.get("/v1/usage",headers=auth_user["headers"])
    assert r.status_code == 200
    j = r.json()
    assert j["today_success"] == 0
    assert j["today_failed"] == 0
    assert j["month_success"] == 0
    assert j["month_failed"] == 0
    assert j["total_prompt_tokens"] == 0
    assert j["total_completion_tokens"] == 0
    assert Decimal(j["total_cost"]) == 0

def test_usage_after_one_chat(client,auth_user):
    chat = client.post("/v1/chat",
                    json = {"prompt": "第二句话"},
                    headers = auth_user["headers"])
    assert chat.status_code == 200

    r = client.get("/v1/usage",headers = auth_user["headers"])
    assert r.status_code == 200
    j = r.json()
    assert j["today_success"] == 1
    assert j["today_failed"] == 0
    assert j["month_success"] == 1
    assert j["month_failed"] == 0
    assert j["total_prompt_tokens"] == 4
    assert j["total_completion_tokens"] == 20
    assert Decimal(j["total_cost"]) > 0

def test_usage_counts_failed(client,auth_user,monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("模拟 LLM 挂了")
    
    monkeypatch.setattr(routers.chat, "chat_completion",boom) 

    r = client.post("/v1/chat",json={"prompt": "hi"},headers=auth_user["headers"])
    assert r.status_code == 502

    r = client.get("/v1/usage",headers=auth_user["headers"])
    assert r.status_code == 200
    j = r.json()
    assert j["today_success"] == 0
    assert j["today_failed"] == 1
    assert j["month_success"] == 0
    assert j["month_failed"] == 1
    assert j["total_prompt_tokens"] == 0
    assert j["total_completion_tokens"] == 0
    assert Decimal(j["total_cost"]) == 0