"""Shopping mode behaviour contract (Ticket 5).

These tests describe the v1 shopping-mode behaviour without requiring the
production UI to exist yet. They exercise a small reference state machine
that documents the expected interaction model:

* Single-tap check / uncheck toggles ``is_checked`` and updates UI state
  optimistically.
* Local changes survive a sync failure.
* Finishing a session archives only checked items and stamps
  ``finished_at`` on the list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Reference state machine
# ---------------------------------------------------------------------------


@dataclass
class ShoppingItem:
    id: str
    name: str
    is_checked: bool = False
    checked_at: Optional[str] = None
    archived_at: Optional[str] = None
    removed_at: Optional[str] = None


@dataclass
class ShoppingSession:
    """Documents the v1 shopping mode behaviour as a tiny in-memory model."""

    items: List[ShoppingItem]
    status: str = "active"
    started_at: str = "2026-05-26T00:00:00Z"
    finished_at: Optional[str] = None
    pending_queue: List[Dict] = field(default_factory=list)
    network_connected: bool = True
    sync_status: str = "synced"  # one of synced | pending | sync_failed

    def toggle(self, item_id: str, *, now: str = "2026-05-26T00:00:01Z") -> ShoppingItem:
        """Optimistically toggle is_checked and queue a sync."""
        target = next(i for i in self.items if i.id == item_id)
        target.is_checked = not target.is_checked
        target.checked_at = now if target.is_checked else None
        self.pending_queue.append(
            {"item_id": item_id, "is_checked": target.is_checked, "at": now}
        )
        self._attempt_sync()
        return target

    def go_offline(self) -> None:
        self.network_connected = False
        if self.pending_queue:
            self.sync_status = "pending"

    def go_online(self, *, sync_succeeds: bool = True) -> None:
        self.network_connected = True
        self._attempt_sync(sync_succeeds=sync_succeeds)

    def _attempt_sync(self, *, sync_succeeds: bool = True) -> None:
        if not self.pending_queue:
            self.sync_status = "synced"
            return
        if not self.network_connected:
            self.sync_status = "pending"
            return
        if sync_succeeds:
            self.pending_queue.clear()
            self.sync_status = "synced"
        else:
            self.sync_status = "sync_failed"

    def finish(self, *, now: str = "2026-05-26T01:00:00Z") -> None:
        if self.status == "finished":
            return
        for item in self.items:
            if item.is_checked and not item.archived_at:
                item.archived_at = now
        self.finished_at = now
        self.status = "finished"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _session() -> ShoppingSession:
    return ShoppingSession(
        items=[
            ShoppingItem(id="1", name="Tomato"),
            ShoppingItem(id="2", name="Pasta"),
            ShoppingItem(id="3", name="Olive Oil"),
        ]
    )


def test_single_tap_checks_item_and_updates_state():
    session = _session()
    item = session.toggle("1")
    assert item.is_checked is True
    assert item.checked_at is not None


def test_single_tap_toggle_uncheck():
    session = _session()
    session.toggle("1")
    again = session.toggle("1")
    assert again.is_checked is False
    assert again.checked_at is None


def test_unchecked_items_come_first_in_active_list_after_checkoff():
    session = _session()
    session.toggle("2")  # Pasta is now checked
    unchecked_first = sorted(session.items, key=lambda i: i.is_checked)
    assert [i.id for i in unchecked_first][:2] == ["1", "3"]


def test_optimistic_updates_when_offline():
    session = _session()
    session.go_offline()
    session.toggle("1")
    # UI must reflect the change immediately.
    assert session.items[0].is_checked is True
    # Pending queue captures the unsent change.
    assert len(session.pending_queue) == 1
    assert session.sync_status == "pending"


def test_pending_changes_sync_on_reconnect():
    session = _session()
    session.go_offline()
    session.toggle("1")
    session.toggle("2")
    assert len(session.pending_queue) == 2
    session.go_online(sync_succeeds=True)
    assert session.pending_queue == []
    assert session.sync_status == "synced"


def test_failed_sync_does_not_erase_local_progress():
    session = _session()
    session.toggle("1")
    session.toggle("2")
    # Simulate a network blip during sync.
    session.go_offline()
    session.toggle("3")
    session.go_online(sync_succeeds=False)
    # Items still reflect local progress.
    assert session.items[0].is_checked is True
    assert session.items[1].is_checked is True
    assert session.items[2].is_checked is True
    # And the queue is not cleared — retries will continue.
    assert len(session.pending_queue) >= 1
    assert session.sync_status == "sync_failed"


def test_finish_session_archives_checked_items_only():
    session = _session()
    session.toggle("1")
    session.toggle("2")
    session.finish()
    by_id = {i.id: i for i in session.items}
    assert by_id["1"].archived_at is not None
    assert by_id["2"].archived_at is not None
    assert by_id["3"].archived_at is None, "unchecked items must remain active"


def test_finish_session_stamps_finished_at_and_sets_status():
    session = _session()
    session.toggle("1")
    session.finish()
    assert session.status == "finished"
    assert session.finished_at is not None


def test_finish_is_idempotent():
    session = _session()
    session.toggle("1")
    session.finish()
    first_finished_at = session.finished_at
    session.finish()  # No-op on a finished list.
    assert session.finished_at == first_finished_at
    assert session.status == "finished"


def test_unchecked_items_are_preserved_after_finish():
    session = _session()
    session.toggle("1")
    session.finish()
    remaining = [i for i in session.items if not i.archived_at]
    assert {i.id for i in remaining} == {"2", "3"}
