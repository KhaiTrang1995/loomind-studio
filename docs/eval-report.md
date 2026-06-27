# Evaluation Report

Generated on: 2026-06-06 19:45:00

## Summary Metrics

| Metric | Value |
|--------|-------|
| Total Test Cases | 10 |
| Skip Status Accuracy | 100.00% |
| Suggestions Precision | 100.00% |
| Suggestions Recall | 100.00% |
| Suggestions F1 Score | 100.00% |
| Average Latency | 417.05 ms |

## Detailed Results

| Action | Expected Skip | Actual Skip | Expected Suggestions | Actual Suggestions | Latency (ms) | Pass |
|--------|---------------|-------------|----------------------|--------------------|--------------|------|
| `create database connection pool` | False | False | Use Connection Pooling | Use Connection Pooling | 1031.7 | Pass |
| `cat requirements.txt` | True | True | None | None | 1.9 | Pass |
| `ls core/` | True | True | None | None | 1.5 | Pass |
| `git status` | True | True | None | None | 1.1 | Pass |
| `store plain password in config file` | False | False | Do Not Store Plaintext Passwords | Do Not Store Plaintext Passwords | 1039.1 | Pass |
| `run pytest tests/` | False | False | None | None | 14.0 | Pass |
| `optimize SQL query in loop` | False | False | Avoid SQL Queries inside Loops | Avoid SQL Queries inside Loops | 1027.3 | Pass |
| `write JWT authentication helper` | False | False | Use Bcrypt for Password Hashing, Set Short JWT Expiration | Use Bcrypt for Password Hashing, Set Short JWT Expiration | 1036.0 | Pass |
| `git log --oneline` | True | True | None | None | 1.3 | Pass |
| `create new database migration file` | False | False | None | None | 16.5 | Pass |
