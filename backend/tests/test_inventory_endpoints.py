"""Endpoint tests for inventory routes using an in-memory fake DB.

These exercise the FastAPI endpoints end-to-end (request -> response) without
requiring a Postgres instance. The fake cursor implements just enough of the
psycopg interface to validate the inventory workflow described in ticket 1.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

from fastapi.testclient import TestClient  # noqa: E402

from backend import server  # noqa: E402


class FakeCursor:
    def __init__(self, store: "FakeStore"):
        self.store = store
        self.result: List[Dict[str, Any]] = []
        self.rowcount: int = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str, params: Optional[Tuple] = None):
        params = tuple(params or ())
        self.result = []
        self.rowcount = 0
        q = " ".join(query.split())
        self.store.handle(self, q, params)

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return list(self.result)


class FakeConn:
    def __init__(self, store: "FakeStore"):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        return None


def _parse_where_pairs(where_clause: str, params: Tuple) -> Dict[str, Any]:
    """Map column name -> bound parameter value by scanning the WHERE clause."""
    keys = re.findall(r"(\w+)\s*=\s*%s", where_clause)
    # Skip placeholders that are not equality params (e.g. LIKE, IS NULL handled separately).
    return dict(zip(keys, params))


class FakeStore:
    """Pretends to be Postgres for the tables server.py touches."""

    def __init__(self):
        self.households: Dict[str, Dict[str, Any]] = {}
        self.inventory: Dict[str, Dict[str, Any]] = {}
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def handle(self, cur: FakeCursor, query: str, params: Tuple):
        # household_defaults
        if query.startswith("SELECT * FROM household_defaults WHERE owner_id = %s"):
            row = self.households.get(params[0])
            cur.result = [row] if row else []
            return
        if query.startswith("SELECT * FROM household_defaults"):
            cur.result = list(self.households.values())
            return
        m = re.match(r"INSERT INTO household_defaults \((.+?)\) VALUES \((.+?)\)$", query)
        if m:
            columns = [c.strip() for c in m.group(1).split(",")]
            values = list(params)
            row = dict(zip(columns, values))
            row.setdefault("expiring_soon_days", server.DEFAULT_EXPIRING_SOON_DAYS)
            row.setdefault("last_inventory_location", "pantry")
            self.households[row["owner_id"]] = row
            cur.rowcount = 1
            return
        if query.startswith("UPDATE household_defaults SET last_inventory_location"):
            location, owner_id = params
            if owner_id in self.households:
                self.households[owner_id]["last_inventory_location"] = location
                cur.rowcount = 1
            return
        if query.startswith("UPDATE household_defaults SET"):
            cur.rowcount = 1
            return

        # inventory_items
        m = re.match(r"INSERT INTO inventory_items \((.+?)\) VALUES \(.+\)$", query)
        if m:
            columns = [c.strip() for c in m.group(1).split(",")]
            row = dict(zip(columns, params))
            self.inventory[row["id"]] = row
            cur.rowcount = 1
            return
        if "FROM inventory_items WHERE" in query and query.startswith("SELECT"):
            where_clause = query.split(" WHERE ")[1].split(" ORDER BY ")[0]
            # Locate positional bindings in order: identify column for each %s.
            ordered_keys = re.findall(r"(\w+)\s*(?:=|LIKE)\s*%s", where_clause)
            bindings = dict(zip(ordered_keys, params))
            rows = list(self.inventory.values())
            if "owner_id" in bindings:
                rows = [r for r in rows if r["owner_id"] == bindings["owner_id"]]
            if "archived_at IS NULL" in where_clause:
                rows = [r for r in rows if r.get("archived_at") is None]
            if "location" in bindings and "location =" in where_clause:
                rows = [r for r in rows if r["location"] == bindings["location"]]
            if "normalized_name" in bindings and "normalized_name =" in where_clause:
                rows = [r for r in rows if r.get("normalized_name") == bindings["normalized_name"]]
            if "normalized_name" in bindings and "normalized_name LIKE" in where_clause:
                like = bindings["normalized_name"].strip("%")
                rows = [r for r in rows if like in (r.get("normalized_name") or "")]
            if "id" in bindings and "id =" in where_clause:
                rows = [r for r in rows if r["id"] == bindings["id"]]
            rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            cur.result = rows
            return
        if query.startswith("UPDATE inventory_items SET"):
            set_clause = query[len("UPDATE inventory_items SET ") :].split(" WHERE ")[0]
            assignments = [a.strip() for a in set_clause.split(",")]
            where_clause = query.split(" WHERE ")[1]
            where_keys = re.findall(r"(\w+)\s*=\s*%s", where_clause)
            n_where = len(where_keys)
            set_values = list(params[:-n_where]) if n_where else list(params)
            where_values = list(params[-n_where:]) if n_where else []
            where_pairs = dict(zip(where_keys, where_values))
            updates: Dict[str, Any] = {}
            for assignment, value in zip(assignments, set_values):
                col = assignment.split("=")[0].strip()
                updates[col] = value
            target_ids = []
            for item_id, row in self.inventory.items():
                if where_pairs.get("id") and row["id"] != where_pairs["id"]:
                    continue
                if where_pairs.get("owner_id") and row["owner_id"] != where_pairs["owner_id"]:
                    continue
                if "archived_at IS NULL" in where_clause and row.get("archived_at") is not None:
                    continue
                target_ids.append(item_id)
            for item_id in target_ids:
                self.inventory[item_id].update(updates)
            cur.rowcount = len(target_ids)
            return
        if query.startswith("DELETE FROM"):
            cur.rowcount = 0
            return
        # Sessions (auth)
        if query.startswith("SELECT id, user_id, token, email, name, created_at FROM sessions"):
            token = params[0]
            row = self.sessions.get(token)
            cur.result = [row] if row else []
            return
        cur.result = []
        cur.rowcount = 0


@pytest.fixture
def fake_store(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(server, "db_conn", lambda: FakeConn(store))
    return store


@pytest.fixture
def authed_client(fake_store):
    token = "test-token"
    user_id = "user-1"
    fake_store.sessions[token] = {
        "id": "sess-1",
        "user_id": user_id,
        "token": token,
        "email": "test@example.com",
        "name": "Tester",
        "created_at": datetime.now(timezone.utc),
    }
    client = TestClient(server.app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client, user_id, fake_store


# ─── Required-field fast-add ─────────────────────────────────────────────────


def test_fast_add_only_name_and_location(authed_client):
    client, _user_id, store = authed_client
    resp = client.post("/api/inventory", json={"name": "Oats", "location": "pantry"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Oats"
    assert body["location"] == "pantry"
    assert body["quantity"] is None
    assert body["unit"] is None
    assert body["normalized_name"] == "oats"
    assert body["is_low_stock"] is False
    assert body["is_expiring_soon"] is False
    stored = next(iter(store.inventory.values()))
    assert stored["normalized_name"] == "oats"


def test_add_item_with_all_optional_fields(authed_client):
    client, *_ = authed_client
    payload = {
        "name": "Greek Yogurt",
        "location": "fridge",
        "quantity": 1,
        "unit": "tub",
        "category": "dairy",
        "expiry_date": (date.today() + timedelta(days=3)).isoformat(),
        "low_stock_threshold": 2,
        "notes": "16oz",
    }
    resp = client.post("/api/inventory", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["category"] == "dairy"
    assert body["notes"] == "16oz"
    assert body["is_low_stock"] is True
    assert body["is_expiring_soon"] is True


def test_fast_add_requires_name(authed_client):
    client, *_ = authed_client
    resp = client.post("/api/inventory", json={"name": "   ", "location": "pantry"})
    assert resp.status_code == 400


def test_fast_add_updates_last_inventory_location(authed_client):
    client, user_id, store = authed_client
    client.post("/api/inventory", json={"name": "Frozen Peas", "location": "freezer"})
    assert store.households[user_id]["last_inventory_location"] == "freezer"


def test_single_add_returns_409_for_active_duplicate(authed_client):
    client, *_ = authed_client
    first = client.post("/api/inventory", json={"name": "Oats", "location": "pantry"}).json()
    resp = client.post("/api/inventory", json={"name": "  oats ", "location": "pantry"})
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"] == "Duplicate inventory item"
    assert body["error_code"] == "INVENTORY_DUPLICATE"
    assert body["duplicate"]["existing_item_id"] == first["id"]
    assert body["duplicate"]["normalized_name"] == "oats"
    assert body["duplicate"]["location"] == "pantry"


def test_single_add_allows_same_normalized_name_in_different_location(authed_client):
    client, *_ = authed_client
    assert client.post("/api/inventory", json={"name": "Oats", "location": "pantry"}).status_code == 200
    assert client.post("/api/inventory", json={"name": "oats", "location": "fridge"}).status_code == 200


def test_single_add_allows_duplicate_name_for_different_owner(fake_store):
    token_a, token_b = "token-a", "token-b"
    fake_store.sessions[token_a] = {
        "id": "sess-a", "user_id": "user-a", "token": token_a, "email": "a@example.com", "name": "A",
        "created_at": datetime.now(timezone.utc),
    }
    fake_store.sessions[token_b] = {
        "id": "sess-b", "user_id": "user-b", "token": token_b, "email": "b@example.com", "name": "B",
        "created_at": datetime.now(timezone.utc),
    }
    client_a = TestClient(server.app)
    client_b = TestClient(server.app)
    client_a.headers.update({"Authorization": f"Bearer {token_a}"})
    client_b.headers.update({"Authorization": f"Bearer {token_b}"})
    assert client_a.post("/api/inventory", json={"name": "Oats", "location": "pantry"}).status_code == 200
    assert client_b.post("/api/inventory", json={"name": "Oats", "location": "pantry"}).status_code == 200


def test_single_add_allows_recreate_when_matching_item_archived(authed_client):
    client, *_ = authed_client
    created = client.post("/api/inventory", json={"name": "Oats", "location": "pantry"}).json()
    assert client.post(f"/api/inventory/{created['id']}/archive").status_code == 200
    resp = client.post("/api/inventory", json={"name": "Oats", "location": "pantry"})
    assert resp.status_code == 200


# ─── Listing, filtering, search ──────────────────────────────────────────────


def _seed_items(client):
    today = date.today()
    items = [
        {"name": "Rice", "location": "pantry", "quantity": 1, "low_stock_threshold": 2},
        {"name": "Black Beans", "location": "pantry", "quantity": 5, "low_stock_threshold": 2},
        {
            "name": "Cheddar Cheese",
            "location": "fridge",
            "expiry_date": (today + timedelta(days=2)).isoformat(),
        },
        {"name": "Ground Beef", "location": "freezer"},
    ]
    return [client.post("/api/inventory", json=item).json() for item in items]


def test_active_inventory_grouped_by_location(authed_client):
    client, *_ = authed_client
    _seed_items(client)
    resp = client.get("/api/inventory?location=pantry")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert {row["name"] for row in rows} == {"Rice", "Black Beans"}


def test_search_uses_normalized_name(authed_client):
    client, *_ = authed_client
    _seed_items(client)
    resp = client.get("/api/inventory?search=cheese")
    assert resp.status_code == 200
    rows = resp.json()
    assert any(row["name"] == "Cheddar Cheese" for row in rows)


def test_low_stock_filter_excludes_full_items(authed_client):
    client, *_ = authed_client
    _seed_items(client)
    resp = client.get("/api/inventory?low_stock=true")
    rows = resp.json()
    assert [row["name"] for row in rows] == ["Rice"]


def test_expiring_soon_filter(authed_client):
    client, *_ = authed_client
    _seed_items(client)
    resp = client.get("/api/inventory?expiring_soon=true")
    rows = resp.json()
    assert [row["name"] for row in rows] == ["Cheddar Cheese"]


def test_archived_items_hidden_by_default(authed_client):
    client, *_ = authed_client
    items = _seed_items(client)
    target = items[0]["id"]
    client.delete(f"/api/inventory/{target}")
    resp = client.get("/api/inventory")
    names = [row["name"] for row in resp.json()]
    assert "Rice" not in names


def test_archive_endpoint_sets_archived_at(authed_client):
    client, _user_id, store = authed_client
    item = client.post("/api/inventory", json={"name": "Bread", "location": "pantry"}).json()
    resp = client.post(f"/api/inventory/{item['id']}/archive")
    assert resp.status_code == 200, resp.text
    assert resp.json()["archived_at"] is not None
    assert store.inventory[item["id"]]["archived_at"] is not None


# ─── Editing ────────────────────────────────────────────────────────────────


def test_editing_name_updates_normalized_name(authed_client):
    client, _user_id, store = authed_client
    item = client.post("/api/inventory", json={"name": "Oats", "location": "pantry"}).json()
    resp = client.put(f"/api/inventory/{item['id']}", json={"name": "Steel-Cut Oats"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["normalized_name"] == "steel cut oats"
    assert store.inventory[item["id"]]["normalized_name"] == "steel cut oats"


def test_editing_optional_fields(authed_client):
    client, *_ = authed_client
    item = client.post("/api/inventory", json={"name": "Apples", "location": "fridge"}).json()
    resp = client.put(
        f"/api/inventory/{item['id']}",
        json={"quantity": 3, "low_stock_threshold": 5, "notes": "Honeycrisp"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["quantity"] == 3
    assert body["notes"] == "Honeycrisp"
    assert body["is_low_stock"] is True


def test_editing_requires_at_least_one_field(authed_client):
    client, *_ = authed_client
    item = client.post("/api/inventory", json={"name": "Apples", "location": "fridge"}).json()
    resp = client.put(f"/api/inventory/{item['id']}", json={})
    assert resp.status_code == 400


# ─── Dashboard surfaces low-stock and expiring-soon ─────────────────────────


def test_dashboard_returns_counts_and_items(authed_client):
    client, *_ = authed_client
    _seed_items(client)
    resp = client.get("/api/inventory/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["expiring_soon_days"] == server.DEFAULT_EXPIRING_SOON_DAYS
    assert body["low_stock_count"] == 1
    assert body["expiring_soon_count"] == 1
    assert [row["name"] for row in body["low_stock"]] == ["Rice"]
    assert [row["name"] for row in body["expiring_soon"]] == ["Cheddar Cheese"]
    assert body["active_total"] == 4


def test_dashboard_omits_archived(authed_client):
    client, *_ = authed_client
    items = _seed_items(client)
    rice_id = next(item["id"] for item in items if item["name"] == "Rice")
    client.delete(f"/api/inventory/{rice_id}")
    body = client.get("/api/inventory/dashboard").json()
    assert body["low_stock_count"] == 0
    assert body["active_total"] == 3


def test_batch_creation_skips_blank_names_and_assigns_normalized_names(authed_client):
    client, _user_id, store = authed_client
    resp = client.post(
        "/api/inventory/batch",
        json=[
            {"name": "Olive Oil", "location": "pantry"},
            {"name": "   ", "location": "pantry"},
            {"name": "  Frozen Berries  ", "location": "freezer"},
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    rows = body["created"]
    assert [row["name"] for row in rows] == ["Olive Oil", "Frozen Berries"]
    assert body["skipped"] == [{"index": 1, "reason": "blank_name"}]
    assert body["conflicts"] == []
    assert body["summary"] == {"created_count": 2, "conflict_count": 0, "skipped_count": 1}
    assert all(row["normalized_name"] for row in rows)
    assert store.households[_user_id]["last_inventory_location"] == "freezer"


def test_batch_reports_db_and_intra_request_duplicates_deterministically(authed_client):
    client, *_ = authed_client
    existing = client.post("/api/inventory", json={"name": "Oats", "location": "pantry"}).json()
    resp = client.post(
        "/api/inventory/batch",
        json=[
            {"name": "Rice", "location": "pantry"},
            {"name": "Oats", "location": "pantry"},
            {"name": " rice ", "location": "pantry"},
            {"name": "  ", "location": "fridge"},
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [item["name"] for item in body["created"]] == ["Rice"]
    assert body["conflicts"] == [
        {
            "index": 1,
            "name": "Oats",
            "location": "pantry",
            "normalized_name": "oats",
            "existing_item_id": existing["id"],
            "error_code": "INVENTORY_DUPLICATE",
        },
        {
            "index": 2,
            "name": "rice",
            "location": "pantry",
            "normalized_name": "rice",
            "existing_item_id": body["created"][0]["id"],
            "error_code": "INVENTORY_DUPLICATE",
        },
    ]
    assert body["skipped"] == [{"index": 3, "reason": "blank_name"}]
    assert body["summary"] == {"created_count": 1, "conflict_count": 2, "skipped_count": 1}
