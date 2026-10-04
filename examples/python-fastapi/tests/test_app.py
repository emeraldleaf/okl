from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"ok": True}


def test_list_orders_is_scoped_to_the_caller():
    mine = client.get("/orders", headers={"x-user-token": "token-bob"}).json()
    assert [o["id"] for o in mine] == [3]
