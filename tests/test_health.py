from main import app
from db import get_db

def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

def test_health_returns_503_when_redis_down(client, monkeypatch):
    def boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr("main.r.ping", boom)

    r = client.get("/health")
    assert r.status_code == 503
    assert "redis down" not in r.text

def test_health_returns_503_when_db_down(client):
    class BadSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("db down")

    def bad_db():
        yield BadSession()

    app.dependency_overrides[get_db] = bad_db
    try:
        r = client.get("/health")
        assert r.status_code == 503
        assert "db_down" not in r.text
    finally:
        app.dependency_overrides.clear()