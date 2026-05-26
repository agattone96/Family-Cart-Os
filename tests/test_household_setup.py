"""Household setup + isolation contract (Ticket 7).

The v1 brief requires:

* First-login household creation with the creating user as ``Owner``.
* All v1 entities are household-scoped via ``household_id``.
* Cross-household reads / writes are rejected.
* Role enforcement lives in a shared access-control layer.

Production wiring is tracked by ``RB-002`` in
``docs/qa/release-blockers.md``. Until that lands, the tests in this file
exercise a small reference policy module that documents the contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Reference model
# ---------------------------------------------------------------------------


@dataclass
class Membership:
    user_id: str
    household_id: str
    role: str  # "owner" or "member"


@dataclass
class HouseholdEntity:
    id: str
    household_id: str
    name: str
    archived_at: Optional[str] = None


@dataclass
class HouseholdWorld:
    """Tiny world model used to pin the v1 household-scoping rules."""

    memberships: List[Membership] = field(default_factory=list)
    entities: Dict[str, HouseholdEntity] = field(default_factory=dict)

    def create_household_for_user(self, user_id: str) -> str:
        household_id = f"hh-{user_id}"
        self.memberships.append(
            Membership(user_id=user_id, household_id=household_id, role="owner")
        )
        return household_id

    def add_member(self, household_id: str, user_id: str, *, role: str = "member") -> None:
        if role not in ("owner", "member"):
            raise ValueError(f"unsupported role: {role}")
        self.memberships.append(
            Membership(user_id=user_id, household_id=household_id, role=role)
        )

    def _user_households(self, user_id: str) -> List[str]:
        return [m.household_id for m in self.memberships if m.user_id == user_id]

    def can_access(self, user_id: str, household_id: str) -> bool:
        return household_id in self._user_households(user_id)

    def create_entity(self, user_id: str, household_id: str, name: str) -> HouseholdEntity:
        if not self.can_access(user_id, household_id):
            raise PermissionError("user not a member of target household")
        entity = HouseholdEntity(
            id=f"e-{len(self.entities) + 1}", household_id=household_id, name=name
        )
        self.entities[entity.id] = entity
        return entity

    def read_entity(self, user_id: str, entity_id: str) -> HouseholdEntity:
        entity = self.entities.get(entity_id)
        if entity is None:
            raise LookupError("entity not found")
        if not self.can_access(user_id, entity.household_id):
            raise PermissionError("entity not in user's household")
        return entity

    def archive_entity(self, user_id: str, entity_id: str, now: str) -> HouseholdEntity:
        entity = self.entities.get(entity_id)
        if entity is None:
            raise LookupError("entity not found")
        if not self.can_access(user_id, entity.household_id):
            raise PermissionError("entity not in user's household")
        entity.archived_at = now
        return entity


@pytest.fixture
def world():
    return HouseholdWorld()


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def test_first_household_setup_assigns_owner(world):
    hh = world.create_household_for_user("u-1")
    assert hh == "hh-u-1"
    membership = world.memberships[0]
    assert membership.role == "owner"
    assert membership.user_id == "u-1"


def test_member_role_can_be_added_without_owner_promotion(world):
    hh = world.create_household_for_user("u-1")
    world.add_member(hh, "u-2")
    by_user = {m.user_id: m.role for m in world.memberships}
    assert by_user == {"u-1": "owner", "u-2": "member"}


def test_only_owner_and_member_roles_supported(world):
    hh = world.create_household_for_user("u-1")
    with pytest.raises(ValueError):
        world.add_member(hh, "u-3", role="co-admin")
    with pytest.raises(ValueError):
        world.add_member(hh, "u-4", role="teen")


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


def test_user_can_read_entities_in_their_household(world):
    hh = world.create_household_for_user("u-1")
    entity = world.create_entity("u-1", hh, "Tomato")
    assert world.read_entity("u-1", entity.id).name == "Tomato"


def test_user_cannot_read_entities_in_another_household(world):
    hh_a = world.create_household_for_user("u-1")
    hh_b = world.create_household_for_user("u-2")
    entity_b = world.create_entity("u-2", hh_b, "Olive Oil")
    with pytest.raises(PermissionError):
        world.read_entity("u-1", entity_b.id)
    # And vice versa
    entity_a = world.create_entity("u-1", hh_a, "Pasta")
    with pytest.raises(PermissionError):
        world.read_entity("u-2", entity_a.id)


def test_user_cannot_create_entities_in_another_household(world):
    world.create_household_for_user("u-1")
    hh_b = world.create_household_for_user("u-2")
    with pytest.raises(PermissionError):
        world.create_entity("u-1", hh_b, "Sneaky")


def test_user_cannot_archive_entities_in_another_household(world):
    hh_b = world.create_household_for_user("u-2")
    entity = world.create_entity("u-2", hh_b, "Salt")
    with pytest.raises(PermissionError):
        world.archive_entity("u-1", entity.id, "2026-05-26T00:00:00Z")


def test_member_of_target_household_can_access_entities(world):
    hh = world.create_household_for_user("u-1")
    world.add_member(hh, "u-2")
    entity = world.create_entity("u-1", hh, "Bread")
    assert world.read_entity("u-2", entity.id).name == "Bread"


# ---------------------------------------------------------------------------
# Production-state guards
# ---------------------------------------------------------------------------


def test_production_household_scoping_blocker_documented():
    """Until ``household_id`` is on the production schema, RB-002 must capture it."""
    server_text = (REPO_ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    blockers = (REPO_ROOT / "docs" / "qa" / "release-blockers.md").read_text(encoding="utf-8")
    if "household_id" not in server_text:
        assert "RB-002" in blockers


def test_owner_role_enforcement_layer_documented():
    """Role checks must live in a shared layer; the QA artifact must say so."""
    text = (REPO_ROOT / "docs" / "qa" / "mvp-release-checklist.md").read_text(encoding="utf-8").lower()
    assert "role enforcement" in text
    assert "shared access-control" in text
