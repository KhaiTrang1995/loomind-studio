---
name: run-tests
description: Run the Loomind test suite. Use when verifying code changes or diagnosing test failures.
---

Run the test suite for Loomind Studio.

## Python engine tests (primary)
```bash
cd core/loomind-engine
python -m pytest tests/ -v --cov=src
```

## TypeScript build verification
```bash
npx turbo build
```

## By specific test file
```bash
cd core/loomind-engine
python -m pytest tests/test_<name>.py -v
```

## After running
1. Report: total passed, failed, errors
2. For each failure: test name, error message, likely root cause
3. If all pass, confirm with the count
4. For TypeScript: confirm all 5 packages built successfully
