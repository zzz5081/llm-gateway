import secrets
def test_register_new_user(client,cleanup):
    name = "t_" + secrets.token_hex(5)
    cleanup.append(name)
    r = client.post("/auth/register",json={'username':name,"password":"12345678"})
    assert r.status_code == 201

def test_register_duplicate(client,temp_user):
    r = client.post("/auth/register",json=temp_user) 
    assert r.status_code == 409

def test_login_ok(client,temp_user):
    r = client.post("/auth/login",json=temp_user)
    assert r.status_code == 200
    assert r.json()["access_token"] is not None

def test_login_wrong_password(client):
    r = client.post("/auth/login",json={"username":"testuser1","password":"123312"})
    assert r.status_code == 401

def test_me_without_token(client):
    r = client.get("/auth/me")
    assert r.status_code == 401