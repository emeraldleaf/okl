"""The orders-api HTTP routes. From the project folder: serve with `uvicorn app.main:app`, test with `pytest`."""
from fastapi import Depends, FastAPI, Header, HTTPException

from .store import ORDERS, USERS

app = FastAPI(title="orders-api")


def current_user(x_user_token: str = Header(...)) -> str:
    """Resolve the caller from a bearer-like header. Deliberately simple."""
    for user_id, token in USERS.items():
        if token == x_user_token:
            return user_id
    raise HTTPException(status_code=401, detail="unknown token")


@app.get("/health")
def health() -> dict:
    """Report that the service is up."""
    return {"ok": True}


@app.get("/orders")
def list_orders(user: str = Depends(current_user)) -> list[dict]:
    """The caller's own orders only."""
    return [o for o in ORDERS.values() if o["owner"] == user]
