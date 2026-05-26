# QA & Release Gate

Family Cart OS v1 release gate. Everything in this folder is treated as
authoritative for release sign-off. Update these files alongside any change
that affects scope, navigation, or release readiness.

| File | Purpose |
|---|---|
| `mvp-release-checklist.md` | Row-by-row reusable QA checklist for the v1 pantry → shopping loop. |
| `scope-guardrail-signoff.md` | Formal confirmation that out-of-scope v1 features are absent. |
| `known-issues.md` | Defects QA has accepted and intentionally shipped around. |
| `release-blockers.md` | Issues that block v1 from shipping. Cleared, signed, or formally excepted. |

## Tooling

Run the automated guardrail script before sign-off:

```bash
python3 scripts/check_release_guardrails.py
```

Run the v1 release guardrail tests:

```bash
DATABASE_URL='postgresql://user:pass@localhost:5432/testdb' \
  python3 -m pytest tests/test_release_guardrails.py tests/test_normalized_name.py tests/test_ai_response_validation.py -q
```

Both must exit `0` for sign-off.
