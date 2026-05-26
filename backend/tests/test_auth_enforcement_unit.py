import ast
import os
from pathlib import Path

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

from backend import server


PROTECTED_ENDPOINTS = [
    "get_profile",
    "update_profile",
    "reset_profile",
    "get_inventory",
    "add_inventory_item",
    "add_inventory_batch",
    "update_inventory_item",
    "archive_inventory_item",
    "delete_inventory_item",
    "get_inventory_dashboard",
    "get_required_items",
    "add_required_item",
    "update_required_item",
    "delete_required_item",
    "generate_plan",
    "get_current_plan",
    "update_current_plan",
    "remove_recipe",
    "regenerate_recipe",
    "get_history",
    "save_to_history",
    "duplicate_from_history",
]


@pytest.mark.asyncio
async def test_require_session_rejects_missing_bearer_token():
    with pytest.raises(HTTPException) as exc:
        await server.require_session(None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_require_session_rejects_invalid_bearer_token(monkeypatch):
    async def fake_get_session(_authorization):
        return None

    monkeypatch.setattr(server, "get_session", fake_get_session)

    with pytest.raises(HTTPException) as exc:
        await server.require_session("Bearer invalid")
    assert exc.value.status_code == 401


def test_public_owner_fallback_removed_from_server_source():
    source = Path(server.__file__).read_text()
    assert "PUBLIC_OWNER_ID" not in source
    assert "if session else" not in source


def _function_calls_require_session(func: ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(func):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            call = node.value
            target = call.func
            name = getattr(target, "id", None) or getattr(target, "attr", None)
            if name == "require_session":
                for arg in call.args:
                    if isinstance(arg, ast.Name) and arg.id == "authorization":
                        return True
    return False


@pytest.mark.parametrize("endpoint_name", PROTECTED_ENDPOINTS)
def test_protected_endpoints_enforce_session(endpoint_name):
    tree = ast.parse(Path(server.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == endpoint_name:
            assert _function_calls_require_session(node), (
                f"{endpoint_name} must call require_session(authorization)"
            )
            return
    pytest.fail(f"Endpoint {endpoint_name} not found in server.py")
