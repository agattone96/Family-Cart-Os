#!/usr/bin/env python3
"""Family Cart OS v1 — automated release-guardrail checks.

This script enforces the scope rules described in
``docs/qa/scope-guardrail-signoff.md`` and the navigation / dashboard rules from
the v1 product brief. It is intentionally dependency-free so it can run in CI
and on a release manager's laptop without `pip install`.

Exit codes
----------
* ``0`` — all guardrails pass.
* ``1`` — at least one guardrail failed. Details are printed to stderr.

The script is also importable from tests (see
``tests/test_release_guardrails.py``); ``run_checks()`` returns a structured
result rather than calling ``sys.exit``.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Sections required by the Family Cart OS v1 app shell (Ticket 7).
REQUIRED_V1_SECTIONS: Sequence[str] = (
    "Dashboard",
    "Inventory",
    "AI Meal Ideas",
    "Weekly Meal Planner",
    "Shopping List",
)

# Maximum number of primary dashboard cards allowed in v1 (Ticket 6).
DASHBOARD_CARD_LIMIT = 5

# Phrases that, if surfaced in product UI strings, would imply an
# out-of-scope v1 feature. Each entry is the explicit user-facing phrase plus
# the deferred feature it maps to. Keep these tight enough not to false-positive
# on legitimate planner/inventory copy.
OUT_OF_SCOPE_UI_TERMS: Sequence[tuple[str, str]] = (
    ("scan receipt", "Receipt scanning"),
    ("receipt scan", "Receipt scanning"),
    ("scan barcode", "Barcode scanning"),
    ("barcode scan", "Barcode scanning"),
    ("live price", "Live grocery pricing"),
    ("live pricing", "Live grocery pricing"),
    ("apply coupon", "Coupons"),
    ("clip coupon", "Coupons"),
    ("grocery delivery", "Grocery delivery"),
    ("instacart", "Grocery delivery"),
    ("doordash", "Grocery delivery"),
    ("calorie", "Nutrition tracking"),
    ("nutrition tracking", "Nutrition tracking"),
    ("macro tracking", "Nutrition tracking"),
    ("budget tracking", "Budget tracking"),
    ("monthly budget", "Budget tracking"),
    ("switch household", "Multi-household switching UI"),
    ("switch to household", "Multi-household switching UI"),
    ("household switcher", "Multi-household switching UI"),
    ("co-admin", "Five-role permission system"),
    ("teen role", "Five-role permission system"),
    ("child role", "Five-role permission system"),
    ("activity history", "Activity history"),
    ("audit log", "Activity history"),
    ("approval flow", "Request approval flow"),
    ("household inbox", "Household inbox"),
    ("list template", "Templates"),
    ("save as template", "Templates"),
)

# Empty-state copy in these files must not promise out-of-scope features.
EMPTY_STATE_SOURCE_GLOBS: Sequence[str] = (
    "frontend/app/**/*.tsx",
    "frontend/app/**/*.ts",
    "frontend/src/**/*.tsx",
)

# Where Family Cart OS app shell navigation lives (or should live).
APP_SHELL_CANDIDATES: Sequence[str] = (
    "frontend/app/(tabs)/_layout.tsx",
    "frontend/app/_layout.tsx",
    "apps/diana-web/src/App.tsx",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class GuardrailReport:
    results: List[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.passed for r in self.results)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    def failures(self) -> List[CheckResult]:
        return [r for r in self.results if not r.passed]


def _iter_files(globs: Iterable[str], repo_root: Path) -> List[Path]:
    files: List[Path] = []
    for pattern in globs:
        # Path.glob does not support ``**`` recursively unless we split on it.
        if "**" in pattern:
            base, _, rest = pattern.partition("**/")
            base_dir = repo_root / base
            if not base_dir.exists():
                continue
            files.extend(p for p in base_dir.rglob(rest) if p.is_file())
        else:
            candidate = repo_root / pattern
            if candidate.is_file():
                files.append(candidate)
    return files


def _strip_metro_cache(paths: Iterable[Path]) -> List[Path]:
    """Skip the Metro bundler cache — vendor code, not authored product UI."""
    return [p for p in paths if ".metro-cache" not in p.parts]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_navigation_sections(repo_root: Path) -> CheckResult:
    """At least one app shell file must declare all five v1 sections.

    The check intentionally accepts any one of the candidate shell files,
    because the v1 product can ship either through the Expo app or the
    diana-web app (or both).
    """
    findings: List[str] = []
    matched_any = False
    for candidate in APP_SHELL_CANDIDATES:
        path = repo_root / candidate
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        missing = [s for s in REQUIRED_V1_SECTIONS if s.lower() not in text]
        if not missing:
            matched_any = True
            break
        findings.append(f"{candidate}: missing {missing}")

    if matched_any:
        return CheckResult(
            name="navigation-five-sections",
            passed=True,
            detail="All five v1 sections found in an app shell file.",
        )
    detail = (
        "No app shell file declares all five v1 navigation sections "
        f"({list(REQUIRED_V1_SECTIONS)}). Findings: "
        + "; ".join(findings) if findings else
        "No candidate app shell file was found."
    )
    return CheckResult(name="navigation-five-sections", passed=False, detail=detail)


def check_dashboard_card_limit(repo_root: Path) -> CheckResult:
    """Dashboard renders no more than ``DASHBOARD_CARD_LIMIT`` primary cards.

    Heuristic: if a dashboard source file exists, count distinct lines that
    look like a `testID="dashboard-card-..."` or `data-card` declaration. If
    no dashboard file exists yet, the check is **not** treated as a failure —
    that gap is owned by RB-008 in ``release-blockers.md``.
    """
    candidates = (
        repo_root / "frontend/app/(tabs)/dashboard.tsx",
        repo_root / "frontend/app/(tabs)/index.tsx",  # in case shell is renamed
        repo_root / "apps/diana-web/src/pages/dashboard.tsx",
    )
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        # only count files that explicitly self-identify as the dashboard
        if "dashboard-card" not in text.lower():
            continue
        card_lines = re.findall(r"testID=[\"'`]dashboard-card[-_]\w+", text, flags=re.I)
        unique_cards = sorted(set(card_lines))
        if len(unique_cards) > DASHBOARD_CARD_LIMIT:
            return CheckResult(
                name="dashboard-card-limit",
                passed=False,
                detail=(
                    f"Dashboard file {path.relative_to(repo_root)} exposes "
                    f"{len(unique_cards)} primary cards (limit is "
                    f"{DASHBOARD_CARD_LIMIT}). Cards: {unique_cards}."
                ),
            )
        return CheckResult(
            name="dashboard-card-limit",
            passed=True,
            detail=(
                f"Dashboard file {path.relative_to(repo_root)} declares "
                f"{len(unique_cards)} primary cards (≤ {DASHBOARD_CARD_LIMIT})."
            ),
        )

    return CheckResult(
        name="dashboard-card-limit",
        passed=True,
        detail=(
            "No dashboard source file found — gap is tracked as RB-008 in "
            "docs/qa/release-blockers.md, not a guardrail failure."
        ),
    )


def check_no_out_of_scope_ui_strings(repo_root: Path) -> CheckResult:
    """Scan product source files for in-product UI strings that map to out-of-scope features."""
    paths = _strip_metro_cache(_iter_files(EMPTY_STATE_SOURCE_GLOBS, repo_root))
    offenders: List[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lower = text.lower()
        for phrase, feature in OUT_OF_SCOPE_UI_TERMS:
            if phrase in lower:
                offenders.append(
                    f"{path.relative_to(repo_root)}: '{phrase}' implies '{feature}'"
                )
    if offenders:
        return CheckResult(
            name="no-out-of-scope-ui-strings",
            passed=False,
            detail=(
                "Out-of-scope feature references detected in product UI source. "
                "Remove or move them behind a v2 feature flag. Offenders:\n  - "
                + "\n  - ".join(offenders)
            ),
        )
    return CheckResult(
        name="no-out-of-scope-ui-strings",
        passed=True,
        detail=f"Scanned {len(paths)} files; no out-of-scope UI phrases found.",
    )


def check_qa_artifacts_present(repo_root: Path) -> CheckResult:
    """Required QA artifacts must exist."""
    required = [
        "docs/qa/mvp-release-checklist.md",
        "docs/qa/scope-guardrail-signoff.md",
        "docs/qa/known-issues.md",
        "docs/qa/release-blockers.md",
    ]
    missing = [name for name in required if not (repo_root / name).is_file()]
    if missing:
        return CheckResult(
            name="qa-artifacts-present",
            passed=False,
            detail=f"Missing QA artifacts: {missing}",
        )
    return CheckResult(name="qa-artifacts-present", passed=True, detail="All four QA artifacts present.")


def check_shopping_mode_offline_decision(repo_root: Path) -> CheckResult:
    """Offline strategy must be documented before shopping mode implementation."""
    path = repo_root / "docs/qa/release-blockers.md"
    if not path.is_file():
        return CheckResult(
            name="shopping-mode-offline-decision",
            passed=False,
            detail="docs/qa/release-blockers.md missing — cannot verify offline strategy.",
        )
    text = path.read_text(encoding="utf-8")
    needles = (
        "optimistic update",
        "local queue",
        "sync on reconnect",
        "no-loss guarantee",
    )
    missing = [n for n in needles if n.lower() not in text.lower()]
    if missing:
        return CheckResult(
            name="shopping-mode-offline-decision",
            passed=False,
            detail=(
                "Shopping-mode offline strategy section is incomplete in "
                f"docs/qa/release-blockers.md. Missing concepts: {missing}."
            ),
        )
    return CheckResult(
        name="shopping-mode-offline-decision",
        passed=True,
        detail="Offline strategy documented in docs/qa/release-blockers.md.",
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_checks(repo_root: Path | None = None) -> GuardrailReport:
    repo_root = repo_root or REPO_ROOT
    report = GuardrailReport()
    report.add(check_qa_artifacts_present(repo_root))
    report.add(check_navigation_sections(repo_root))
    report.add(check_dashboard_card_limit(repo_root))
    report.add(check_no_out_of_scope_ui_strings(repo_root))
    report.add(check_shopping_mode_offline_decision(repo_root))
    return report


def _format(report: GuardrailReport) -> str:
    lines = []
    for result in report.results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"[{status}] {result.name}")
        if result.detail:
            for piece in result.detail.splitlines():
                lines.append(f"    {piece}")
    if report.ok:
        lines.append("")
        lines.append("All release guardrails passed.")
    else:
        lines.append("")
        lines.append(f"{len(report.failures())} guardrail check(s) failed.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root to scan (default: this repo).",
    )
    args = parser.parse_args(argv)
    report = run_checks(args.repo_root)
    print(_format(report))
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover - entrypoint
    sys.exit(main())
