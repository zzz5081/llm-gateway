import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).parent))
from main import app
import secrets
import db
from sqlalchemy import text

@pytest.fixture
def client():
    return TestClient(app)


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