import random
import string

from locust import HttpUser, task, between

class GatewayUser(HttpUser):
    wait_time = between(0.1, 0.3)

    def on_start(self):
        name = "load_" + "".join(random.choices(string.ascii_lowercase, k=8))
        self.client.post("/auth/register",
                         json={"username": name, "password": "load12345"})
        r = self.client.post("/auth/login",
                             json={"username": name,"password": "load12345"})
        self.headers = {"Authorization": "Bearer " + r.json()["access_token"]}

    @task
    def usage(self):
        self.client.get("/v1/usage", headers = self.headers)