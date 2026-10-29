def test_health_body(client):
    r = client.get("/health")
    assert r.json() == {"status":"ok"}

def test_response_has_process_time(client):
    r = client.get("/health")
    assert "X-process-Time" in r.headers

def test_unknown_path_returns_404(client):
    r = client.get("/this-path-does-not-exist")
    assert r.status_code == 404