"""In-memory data: two users, orders that belong to each. Order ids are guessable on
purpose — that is what an ownership check exists to make harmless."""

USERS = {"alice": "token-alice", "bob": "token-bob"}

ORDERS = {
    1: {"id": 1, "owner": "alice", "item": "widget", "quantity": 2, "unit_price": 9.99},
    2: {"id": 2, "owner": "alice", "item": "gadget", "quantity": 1, "unit_price": 24.50},
    3: {"id": 3, "owner": "bob", "item": "gizmo", "quantity": 5, "unit_price": 3.25},
}

PRODUCTS = {"widget": 9.99, "gadget": 24.50, "gizmo": 3.25}
