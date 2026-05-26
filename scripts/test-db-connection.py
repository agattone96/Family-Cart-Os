"""Verify the Neon PostgreSQL connection configured in the repo root ``.env``.

This is a safe, self-contained diagnostic script: it loads ``DATABASE_URL`` from
the repo root ``.env`` file, runs a small set of read-only queries, and prints
only non-sensitive metadata (the hostname extracted from the URL plus the
results of ``SELECT version();``, ``SELECT current_database();`` and
``SELECT current_user;``).

The script never prints the full ``DATABASE_URL`` or any credential — only the
hostname is shown. It exits non-zero when the URL is missing, obviously
malformed (e.g. an ``http(s)://`` URL or an ``EXPO_PUBLIC_*`` value), or when
the connection cannot be established.

Run from the repo root:

    python scripts/test-db-connection.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import IO, Optional, Sequence
from urllib.parse import urlparse

try:  # pragma: no cover - import guard, exercised manually
    from dotenv import load_dotenv
except ImportError as exc:  # pragma: no cover - import guard
    print(
        "❌ Missing dependency: python-dotenv. Install backend deps with: "
        "pip install -r backend/requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc

try:  # pragma: no cover - import guard, exercised manually
    import psycopg
except ImportError as exc:  # pragma: no cover - import guard
    print(
        "❌ Missing dependency: psycopg. Install backend deps with: "
        "pip install -r backend/requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"

DIAGNOSTIC_QUERIES: Sequence[tuple[str, str]] = (
    ("PostgreSQL version", "SELECT version();"),
    ("Database", "SELECT current_database();"),
    ("User", "SELECT current_user;"),
)


def _is_expo_public_url(value: str) -> bool:
    """Return True when ``value`` looks like a frontend/public env value."""
    stripped = value.strip()
    if not stripped:
        return False
    # Direct copy of an ``EXPO_PUBLIC_BACKEND_URL=...`` line, or the variable
    # name pasted in by mistake.
    upper = stripped.upper()
    if upper.startswith("EXPO_PUBLIC_"):
        return True
    return False


def validate_database_url(value: Optional[str]) -> str:
    """Validate ``DATABASE_URL`` before attempting to connect.

    Returns the trimmed URL when it looks acceptable. Raises ``ValueError``
    with a user-facing message otherwise. The raised message is safe to print
    — it never echoes the full URL or any credentials.
    """
    if value is None or not value.strip():
        raise ValueError(
            "DATABASE_URL is not set. Add it to the repo root .env file "
            "(see .env.example)."
        )

    trimmed = value.strip()
    lowered = trimmed.lower()

    if lowered.startswith(("http://", "https://")):
        raise ValueError(
            "DATABASE_URL must be a postgresql:// connection string, not an "
            "http(s):// URL. It looks like the frontend backend URL was "
            "pasted into DATABASE_URL by mistake."
        )

    if _is_expo_public_url(trimmed):
        raise ValueError(
            "DATABASE_URL must be a server-side postgresql:// connection "
            "string, not an EXPO_PUBLIC_* value. EXPO_PUBLIC_* variables are "
            "exposed to the client and must never hold database credentials."
        )

    if not (lowered.startswith("postgresql://") or lowered.startswith("postgres://")):
        raise ValueError(
            "DATABASE_URL must start with postgresql:// (or postgres://). "
            "See .env.example for the expected format."
        )

    return trimmed


def safe_hostname(url: str) -> str:
    """Extract only the hostname from ``url`` for display.

    Returns ``"<unknown host>"`` when the URL cannot be parsed — this is a
    diagnostic-only fallback and never includes credentials.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return "<unknown host>"
    return parsed.hostname or "<unknown host>"


def run_diagnostics(
    database_url: str,
    *,
    out: Optional[IO[str]] = None,
    err: Optional[IO[str]] = None,
) -> int:
    """Connect and run the diagnostic queries. Return a process exit code.

    ``out`` / ``err`` default to the current ``sys.stdout`` / ``sys.stderr``;
    they are looked up at call time so tests that swap the streams (e.g.
    pytest's ``capsys``) see the captured output.
    """
    out_stream: IO[str] = out if out is not None else sys.stdout
    err_stream: IO[str] = err if err is not None else sys.stderr

    host = safe_hostname(database_url)
    # Flush so the host line appears before any subsequent stderr error when
    # stdout is block-buffered (e.g. piped output).
    print(f"Connecting to host: {host}", file=out_stream, flush=True)

    try:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                for label, query in DIAGNOSTIC_QUERIES:
                    cur.execute(query)
                    row = cur.fetchone()
                    value = row[0] if row else ""
                    print(f"{label}: {value}", file=out_stream)
    except Exception as exc:  # noqa: BLE001 - we intentionally catch broadly
        # Stringify via str(exc) so we never leak repr() details that might
        # include the connection string.
        message = str(exc).strip() or exc.__class__.__name__
        print(f"❌ Connection failed: {message}", file=err_stream)
        return 1

    print("✅ Connection successful.", file=out_stream)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point. ``argv`` is accepted for testability but ignored."""
    del argv  # unused

    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    else:
        # Fall back to ambient environment so the script still works when the
        # repo .env is absent (e.g. CI) but DATABASE_URL is exported.
        load_dotenv()

    raw = os.environ.get("DATABASE_URL")
    try:
        database_url = validate_database_url(raw)
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    return run_diagnostics(database_url)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
