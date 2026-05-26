# Testing Guide

## Backend unit tests

```bash
pytest -q
```

Notes:
- Some tests require environment variables (for example `DATABASE_URL`).

## API smoke testing

The repository includes integration-style tests under `backend/tests/`. If you run them against a deployed backend, ensure:
- `EXPO_PUBLIC_BACKEND_URL` is set to the backend base URL
- you have a valid user session token for protected endpoints

## Family Cart OS v1 release-gate tests

The QA suite that gates v1 releases lives in `tests/`. These tests do not need
a running backend and can run from a clean checkout:

```bash
DATABASE_URL='postgresql://user:pass@localhost:5432/testdb' \
  python3 -m pytest \
    tests/test_release_guardrails.py \
    tests/test_normalized_name.py \
    tests/test_ai_response_validation.py \
    tests/test_shopping_list_dedupe.py \
    tests/test_shopping_mode_behaviour.py \
    tests/test_household_setup.py \
    tests/test_v1_qa_integration.py \
    -q
```

Also run the automated guardrail script:

```bash
python3 scripts/check_release_guardrails.py
```

Both must exit `0` for v1 release sign-off. See `docs/qa/README.md` for the
release-gate workflow.

## Lint / formatting

Backend tooling is listed in `backend/requirements.txt` (Black, isort, flake8, mypy). Configure your editor to use these tools if you are contributing.
