"""Tests for ``scripts/test-db-connection.py``.

The script's filename contains a hyphen, so it cannot be imported with the
normal ``import`` machinery. We load it via ``importlib.util`` and exercise
the validation / redaction helpers directly.

These tests intentionally do not require a live PostgreSQL connection — the
network-using path (``run_diagnostics``) is covered by mocking ``psycopg``.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "test-db-connection.py"


def _load_script_module() -> types.ModuleType:
    """Import ``scripts/test-db-connection.py`` under a stable module name."""
    spec = importlib.util.spec_from_file_location(
        "test_db_connection_script_module", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script_module() -> types.ModuleType:
    return _load_script_module()


# ---------------------------------------------------------------------------
# validate_database_url
# ---------------------------------------------------------------------------


def test_validate_rejects_missing(script_module):
    with pytest.raises(ValueError, match="DATABASE_URL is not set"):
        script_module.validate_database_url(None)


def test_validate_rejects_blank(script_module):
    with pytest.raises(ValueError, match="DATABASE_URL is not set"):
        script_module.validate_database_url("   ")


def test_validate_rejects_http(script_module):
    with pytest.raises(ValueError, match="not an http"):
        script_module.validate_database_url("http://example.com")


def test_validate_rejects_https(script_module):
    with pytest.raises(ValueError, match="not an http"):
        script_module.validate_database_url("https://example.com")


def test_validate_rejects_expo_public_value(script_module):
    with pytest.raises(ValueError, match="EXPO_PUBLIC"):
        script_module.validate_database_url(
            "EXPO_PUBLIC_BACKEND_URL=https://api.example.com"
        )


def test_validate_rejects_unknown_scheme(script_module):
    with pytest.raises(ValueError, match="postgresql"):
        script_module.validate_database_url("mysql://user:pw@host/db")


def test_validate_accepts_postgres_scheme(script_module):
    url = "postgres://user:pw@host:5432/db"
    assert script_module.validate_database_url(url) == url


def test_validate_accepts_postgresql_neon(script_module):
    url = (
        "postgresql://diana:secret@ep-xxx.us-east-2.aws.neon.tech/neondb"
        "?sslmode=require"
    )
    assert script_module.validate_database_url(url) == url


def test_validate_trims_whitespace(script_module):
    url = " postgresql://u:p@h/db "
    assert script_module.validate_database_url(url) == url.strip()


# ---------------------------------------------------------------------------
# safe_hostname
# ---------------------------------------------------------------------------


def test_safe_hostname_extracts_only_host(script_module):
    url = (
        "postgresql://diana:supersecret@ep-xxx.us-east-2.aws.neon.tech/"
        "neondb?sslmode=require"
    )
    assert script_module.safe_hostname(url) == "ep-xxx.us-east-2.aws.neon.tech"


def test_safe_hostname_never_exposes_password(script_module):
    url = "postgresql://diana:supersecret@host.example.com/db"
    host = script_module.safe_hostname(url)
    assert "supersecret" not in host
    assert "diana" not in host


def test_safe_hostname_falls_back_on_unparseable(script_module):
    # urlparse is very permissive; pass something with no host component.
    assert script_module.safe_hostname("not a url") == "<unknown host>"


# ---------------------------------------------------------------------------
# run_diagnostics — connection path mocked
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, results):
        self._results = list(results)
        self._last = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query):
        self._last = query

    def fetchone(self):
        return (self._results.pop(0),)


class _FakeConnection:
    def __init__(self, results):
        self._results = results

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _FakeCursor(self._results)


def test_run_diagnostics_success(monkeypatch, script_module):
    results = ["PostgreSQL 16.1 on x86_64", "neondb", "diana"]

    def fake_connect(url):
        assert url.startswith("postgresql://")
        return _FakeConnection(results)

    monkeypatch.setattr(script_module.psycopg, "connect", fake_connect)

    out = io.StringIO()
    err = io.StringIO()
    code = script_module.run_diagnostics(
        "postgresql://diana:secret@ep-xxx.us-east-2.aws.neon.tech/neondb",
        out=out,
        err=err,
    )

    assert code == 0
    output = out.getvalue()
    assert "Connecting to host: ep-xxx.us-east-2.aws.neon.tech" in output
    assert "PostgreSQL version: PostgreSQL 16.1" in output
    assert "Database: neondb" in output
    assert "User: diana" in output
    assert "✅ Connection successful." in output
    # Never leak credentials.
    assert "secret" not in output
    assert "secret" not in err.getvalue()


def test_run_diagnostics_failure_reports_error_without_credentials(
    monkeypatch, script_module
):
    def fake_connect(url):
        raise RuntimeError("could not connect to server")

    monkeypatch.setattr(script_module.psycopg, "connect", fake_connect)

    out = io.StringIO()
    err = io.StringIO()
    code = script_module.run_diagnostics(
        "postgresql://diana:supersecret@ep-xxx.us-east-2.aws.neon.tech/neondb",
        out=out,
        err=err,
    )

    assert code == 1
    assert "❌ Connection failed: could not connect to server" in err.getvalue()
    # The full URL and the password must never appear in either stream.
    assert "supersecret" not in err.getvalue()
    assert "supersecret" not in out.getvalue()
    # The host line is still printed before the failure.
    assert "Connecting to host: ep-xxx.us-east-2.aws.neon.tech" in out.getvalue()


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def test_main_missing_database_url_exits_nonzero(monkeypatch, capsys, script_module):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Prevent .env loading from leaking values from the dev machine.
    monkeypatch.setattr(script_module, "ENV_PATH", Path("/nonexistent/.env"))
    monkeypatch.setattr(script_module, "load_dotenv", lambda *a, **kw: False)

    code = script_module.main([])
    captured = capsys.readouterr()
    assert code == 1
    assert "DATABASE_URL is not set" in captured.err


def test_main_rejects_http_database_url(monkeypatch, capsys, script_module):
    monkeypatch.setenv("DATABASE_URL", "https://api.example.com")
    monkeypatch.setattr(script_module, "ENV_PATH", Path("/nonexistent/.env"))
    monkeypatch.setattr(script_module, "load_dotenv", lambda *a, **kw: False)

    code = script_module.main([])
    captured = capsys.readouterr()
    assert code == 1
    assert "http" in captured.err.lower()


def test_main_success_path(monkeypatch, capsys, script_module):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://diana:secret@ep-xxx.us-east-2.aws.neon.tech/neondb",
    )
    monkeypatch.setattr(script_module, "ENV_PATH", Path("/nonexistent/.env"))
    monkeypatch.setattr(script_module, "load_dotenv", lambda *a, **kw: False)

    results = ["PostgreSQL 16.1", "neondb", "diana"]
    monkeypatch.setattr(
        script_module.psycopg,
        "connect",
        lambda url: _FakeConnection(results),
    )

    code = script_module.main([])
    captured = capsys.readouterr()
    assert code == 0
    assert "✅ Connection successful." in captured.out
    assert "secret" not in captured.out
    assert "secret" not in captured.err
