#!/usr/bin/env python3
import os
import sys
from urllib.parse import urlparse
from urllib.request import urlopen

DB_SCHEMES = {"postgres", "postgresql", "mysql", "mongodb", "mongodb+srv"}


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def main() -> int:
    base_url = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("BACKEND_URL") or "").strip()
    if not base_url:
        return fail("Set EXPO_PUBLIC_BACKEND_URL or BACKEND_URL.")

    parsed = urlparse(base_url)
    if parsed.scheme.lower() in DB_SCHEMES:
        return fail("Backend URL is a database URL. Use an HTTP(S) API base URL instead.")
    if parsed.scheme.lower() not in {"http", "https"}:
        return fail("Backend URL must start with http:// or https://.")

    base_url = base_url.rstrip("/")
    target = f"{base_url}/health"

    try:
        with urlopen(target, timeout=10) as response:
            status_code = response.status
            body = response.read().decode("utf-8")
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        return fail(f"Could not reach {target}: {exc}")

    if status_code != 200:
        return fail(f"{target} returned status {status_code}")

    try:
        payload = __import__("json").loads(body)
    except ValueError:
        return fail(f"{target} did not return JSON")

    if payload.get("ok") is True:
        print(f"PASS: {target} returned ok=true")
        return 0
    return fail(f"{target} JSON did not include ok=true")


if __name__ == "__main__":
    sys.exit(main())
