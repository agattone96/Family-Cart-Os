"""Release-guardrail tests for the Family Cart OS v1 MVP.

These tests are part of the v1 release gate and run in CI. They protect the
following invariants:

* The four QA artifacts in ``docs/qa/`` exist and contain the structured
  fields required by the QA checklist (test name, feature area, etc.).
* The release-blocker list documents the known v1 gaps.
* The scope-guardrail sign-off lists every deferred v1 feature.
* The automated guardrail script (``scripts/check_release_guardrails.py``) is
  importable and surfaces the expected checks.
* Out-of-scope feature names do not appear in product UI source files.

Where a v1 feature does not yet exist (e.g. the 5-tab app shell), the
corresponding test asserts that the gap is captured as a blocker in
``docs/qa/release-blockers.md``. This keeps the suite green while still
forcing the team to actively maintain the blocker list.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_guardrail_module():
    """Import ``scripts/check_release_guardrails.py`` without polluting sys.path."""
    spec = importlib.util.spec_from_file_location(
        "check_release_guardrails",
        REPO_ROOT / "scripts" / "check_release_guardrails.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _qa_text(filename: str) -> str:
    path = REPO_ROOT / "docs" / "qa" / filename
    assert path.is_file(), f"Missing QA artifact: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# QA artifact presence + structure
# ---------------------------------------------------------------------------


def test_required_qa_artifacts_exist():
    for filename in (
        "mvp-release-checklist.md",
        "scope-guardrail-signoff.md",
        "known-issues.md",
        "release-blockers.md",
        "README.md",
    ):
        path = REPO_ROOT / "docs" / "qa" / filename
        assert path.is_file(), f"Missing required QA artifact: {path}"


def test_checklist_contains_required_fields():
    text = _qa_text("mvp-release-checklist.md").lower()
    # The MVP checklist must expose every field the spec demands per row.
    for field in (
        "test name",
        "feature area",
        "preconditions",
        "test steps",
        "expected result",
        "actual result",
        "pass / fail",
        "notes",
        "release blocker",
    ):
        assert field in text, f"Checklist missing required field column: {field}"


def test_checklist_covers_each_core_qa_area():
    text = _qa_text("mvp-release-checklist.md").lower()
    for area in (
        "household setup",
        "household data scoping",
        "inventory",
        "ai meal",
        "weekly meal planner",
        "shopping list",
        "shopping mode",
        "dashboard",
        "scope guardrails",
    ):
        assert area in text, f"Checklist missing coverage for: {area}"


def test_checklist_documents_specific_required_tests():
    """Each named test required by the implementation brief is referenced."""
    text = _qa_text("mvp-release-checklist.md").lower()
    for required in (
        "ai-success-path",
        "ai-malformed-response",
        "ai-empty-response",
        "shop-dedupe-normalized",
        "shop-mode-checkoff",
        "shop-mode-optimistic-offline",
        "dash-card-limit",
        "dash-counts-accurate",
        "guardrail-no-out-of-scope-ui",
        "household-isolation-read",
        "household-isolation-write",
    ):
        assert required in text, f"Checklist missing required test row: {required}"


# ---------------------------------------------------------------------------
# Scope-guardrail sign-off completeness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "deferred_feature",
    [
        "Request approval flow",
        "Household inbox",
        "Five-role permission system",
        "Receipt scanning",
        "Barcode scanning",
        "Live grocery pricing",
        "Coupons",
        "Grocery delivery integrations",
        "Nutrition tracking",
        "Budget tracking",
        "Multi-household switching UI",
        "Templates",
        "Reusable list presets",
        "Activity history",
        "Complex household logistics outside the pantry-to-shopping loop",
    ],
)
def test_scope_signoff_lists_every_deferred_feature(deferred_feature):
    text = _qa_text("scope-guardrail-signoff.md")
    assert deferred_feature in text, (
        f"scope-guardrail-signoff.md must list deferred feature '{deferred_feature}'"
    )


# ---------------------------------------------------------------------------
# Release blocker invariants (one blocker per v1 ticket gap)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "blocker_id, expected_keyword",
    [
        ("RB-001", "navigation"),
        ("RB-002", "household"),
        ("RB-003", "normalized_name"),
        ("RB-004", "offline"),
        ("RB-005", "ai_generations"),
        ("RB-006", "meal_plan"),
        ("RB-007", "shopping_list"),
        ("RB-008", "dashboard"),
    ],
)
def test_release_blocker_documented(blocker_id, expected_keyword):
    text = _qa_text("release-blockers.md").lower()
    assert blocker_id.lower() in text, f"Missing blocker row {blocker_id}"
    assert expected_keyword in text, (
        f"Blocker {blocker_id} should reference '{expected_keyword}' in release-blockers.md"
    )


def test_five_v1_navigation_sections_present_or_blocker():
    """If the 5 sections aren't shipped yet, RB-001 must document the gap."""
    module = _load_guardrail_module()
    result = module.check_navigation_sections(REPO_ROOT)
    blockers = _qa_text("release-blockers.md")
    if not result.passed:
        assert "RB-001" in blockers, (
            "Navigation sections check failed but RB-001 is missing from "
            "release-blockers.md."
        )


def test_household_scoping_blocker_documented():
    """If the household_id schema isn't shipped, RB-002 captures the gap."""
    server_text = (REPO_ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    blockers = _qa_text("release-blockers.md")
    if "household_id" not in server_text:
        assert "RB-002" in blockers


def test_inventory_schema_blocker_documented():
    """If `normalized_name` / `archived_at` aren't on the schema, RB-003 captures it."""
    server_text = (REPO_ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    blockers = _qa_text("release-blockers.md")
    if "normalized_name" not in server_text or "archived_at" not in server_text:
        assert "RB-003" in blockers


def test_shopping_mode_offline_decision_documented():
    text = _qa_text("release-blockers.md").lower()
    for needle in ("optimistic update", "local queue", "sync on reconnect", "no-loss guarantee"):
        assert needle in text, (
            f"Offline strategy must include '{needle}' in docs/qa/release-blockers.md"
        )


def test_ai_generations_table_blocker_documented():
    server_text = (REPO_ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    blockers = _qa_text("release-blockers.md")
    if "ai_generations" not in server_text:
        assert "RB-005" in blockers


def test_meal_plan_blocker_documented():
    server_text = (REPO_ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    blockers = _qa_text("release-blockers.md")
    if "meal_plans" not in server_text or "meal_ingredients" not in server_text:
        assert "RB-006" in blockers


def test_shopping_list_blocker_documented():
    server_text = (REPO_ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    blockers = _qa_text("release-blockers.md")
    if "shopping_lists" not in server_text or "shopping_list_items" not in server_text:
        assert "RB-007" in blockers


def test_dashboard_blocker_documented():
    has_dashboard = (
        (REPO_ROOT / "frontend/app/(tabs)/dashboard.tsx").exists()
        or (REPO_ROOT / "apps/diana-web/src/pages/dashboard.tsx").exists()
    )
    blockers = _qa_text("release-blockers.md")
    if not has_dashboard:
        assert "RB-008" in blockers


# ---------------------------------------------------------------------------
# Guardrail script
# ---------------------------------------------------------------------------


def test_guardrail_module_importable_and_runs_checks():
    module = _load_guardrail_module()
    report = module.run_checks(REPO_ROOT)
    check_names = {r.name for r in report.results}
    for required in (
        "qa-artifacts-present",
        "navigation-five-sections",
        "dashboard-card-limit",
        "no-out-of-scope-ui-strings",
        "shopping-mode-offline-decision",
    ):
        assert required in check_names


def test_guardrail_qa_artifacts_check_passes():
    module = _load_guardrail_module()
    result = module.check_qa_artifacts_present(REPO_ROOT)
    assert result.passed, result.detail


def test_guardrail_no_out_of_scope_ui_strings_passes():
    """The product source must never expose deferred-feature copy."""
    module = _load_guardrail_module()
    result = module.check_no_out_of_scope_ui_strings(REPO_ROOT)
    assert result.passed, result.detail


def test_guardrail_offline_decision_check_passes():
    module = _load_guardrail_module()
    result = module.check_shopping_mode_offline_decision(REPO_ROOT)
    assert result.passed, result.detail


# ---------------------------------------------------------------------------
# Dashboard card limit (Ticket 6) regardless of whether the file exists yet
# ---------------------------------------------------------------------------


def test_dashboard_card_limit_constant_matches_spec():
    """Sanity check: limit constant in script matches the v1 brief (4–5)."""
    module = _load_guardrail_module()
    assert module.DASHBOARD_CARD_LIMIT == 5


def _scan_dashboard_cards(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return set(re.findall(r"testID=[\"'`]dashboard-card[-_]\w+", text, flags=re.I))


def test_dashboard_card_limit_enforced_if_dashboard_exists():
    candidates = [
        REPO_ROOT / "frontend/app/(tabs)/dashboard.tsx",
        REPO_ROOT / "apps/diana-web/src/pages/dashboard.tsx",
    ]
    existing = [p for p in candidates if p.exists()]
    if not existing:
        pytest.skip("Dashboard not implemented yet (tracked by RB-008).")
    module = _load_guardrail_module()
    result = module.check_dashboard_card_limit(REPO_ROOT)
    assert result.passed, result.detail
