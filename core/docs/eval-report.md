# Loomind Experience Engine - Evaluation Harness Report

Generated at: 2026-06-06 11:32:02

## Aggregate Metrics

| Metric | Value |
|--------|-------|
| Total Test Cases | 10 |
| Skip Accuracy | 100.0% |
| Average Precision | 33.3% |
| Average Recall | 33.3% |
| Average F1-Score | 33.3% |
| Avg Latency | 704.70 ms |
| Min Latency | 0.00 ms |
| Max Latency | 2351.77 ms |

## Test Cases Detailed Results

| Action | Type | Expected Skip | Actual Skip | Precision | Recall | F1 | Latency | Status |
|--------|------|---------------|-------------|-----------|--------|----|---------|--------|
| create database connection pool | write | No | No | 0% | 0% | 0% | 2351.8 ms | [SUCCESS] |
| cat requirements.txt | read | Yes | Yes | 100% | 100% | 100% | 0.0 ms | [SUCCESS] |
| ls core/ | unknown | Yes | Yes | 100% | 100% | 100% | 0.0 ms | [SUCCESS] |
| git status | unknown | Yes | Yes | 100% | 100% | 100% | 0.0 ms | [SUCCESS] |
| store plain password in config file | write | No | No | 0% | 0% | 0% | 2331.2 ms | [SUCCESS] |
| run pytest tests/ | execute | No | No | 100% | 100% | 100% | 14.1 ms | [SUCCESS] |
| optimize SQL query in loop | write | No | No | 0% | 0% | 0% | 2317.2 ms | [SUCCESS] |
| write JWT authentication helper | write | No | No | 0% | 0% | 0% | 16.0 ms | [SUCCESS] |
| git log --oneline | read | Yes | Yes | 100% | 100% | 100% | 0.0 ms | [SUCCESS] |
| create new database migration file | write | No | No | 100% | 100% | 100% | 16.7 ms | [SUCCESS] |
