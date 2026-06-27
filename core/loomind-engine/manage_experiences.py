"""
Loomind — Experience Export/Import CLI Tool

Usage:
    python manage_experiences.py export [filename]
    python manage_experiences.py import <filename> [--overwrite]
    python manage_experiences.py count
    python manage_experiences.py eval [--url <url>]

Examples:
    python manage_experiences.py export                          # Export to experiences_backup_YYYYMMDD.json
    python manage_experiences.py export my_backup.json           # Export to custom filename
    python manage_experiences.py import my_backup.json           # Import (skip duplicates)
    python manage_experiences.py import my_backup.json --overwrite  # Import (overwrite existing)
    python manage_experiences.py eval                            # Run evaluation harness
    python manage_experiences.py eval --url http://127.0.0.1:8082 # Run on custom url
"""

import json
import sys
import os
from datetime import datetime

try:
    import requests
except ImportError:
    # Fallback to urllib for environments without requests
    import urllib.request
    import urllib.error

    class requests:  # type: ignore
        @staticmethod
        def get(url, **kw):
            try:
                r = urllib.request.urlopen(url, timeout=kw.get("timeout", 5))
                return type("R", (), {"ok": True, "status_code": r.status, "json": lambda: json.loads(r.read()), "raise_for_status": lambda: None})()
            except Exception as e:
                raise ConnectionError(str(e))

        @staticmethod
        def post(url, json=None, **kw):
            data = json.dumps(json).encode() if json else None
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            r = urllib.request.urlopen(req, timeout=kw.get("timeout", 30))
            return type("R", (), {"ok": True, "status_code": r.status, "json": lambda: json.loads(r.read()), "raise_for_status": lambda: None})()


BASE = "http://127.0.0.1:8082"


def check_engine():
    try:
        r = requests.get(f"{BASE}/health", timeout=3)
        return r.ok
    except Exception:
        return False


def cmd_export(filename=None):
    if not filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"experiences_backup_{ts}.json"

    print(f"[*] Exporting experiences from {BASE}...")
    r = requests.get(f"{BASE}/api/experiences/backup/export", timeout=30)
    r.raise_for_status()
    data = r.json()

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    size_kb = os.path.getsize(filename) / 1024
    print(f"[OK] Exported {data['total']} experiences to {filename} ({size_kb:.1f} KB)")
    return data["total"]


def cmd_import(filename, overwrite=False):
    if not os.path.exists(filename):
        print(f"[ERROR] File not found: {filename}")
        sys.exit(1)

    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Support both ExportBundle format and plain list
    if isinstance(data, dict) and "experiences" in data:
        experiences = data["experiences"]
        print(f"[*] Loading ExportBundle: {len(experiences)} experiences")
    elif isinstance(data, list):
        experiences = data
        print(f"[*] Loading plain list: {len(experiences)} experiences")
    else:
        print("[ERROR] Invalid format. Expected ExportBundle or list of experiences.")
        sys.exit(1)

    mode = "OVERWRITE" if overwrite else "SKIP duplicates"
    print(f"[*] Importing to {BASE} (mode: {mode})...")

    r = requests.post(
        f"{BASE}/api/experiences/backup/import",
        json={"experiences": experiences, "overwrite": overwrite},
        timeout=120,
    )
    r.raise_for_status()
    result = r.json()

    print(f"\n[DONE] Import result:")
    print(f"  Imported: {result['imported']}")
    print(f"  Skipped:  {result['skipped']}")
    print(f"  Failed:   {result['failed']}")
    print(f"  Total:    {result['total_in_file']}")


def cmd_count():
    r = requests.get(f"{BASE}/api/stats", timeout=5)
    r.raise_for_status()
    data = r.json()
    print(f"Total experiences: {data.get('total_experiences', '?')}")


def cmd_eval(url=None):
    from src.harness.evaluator import load_dataset, run_evaluation, generate_markdown_report

    url = url or BASE
    script_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_path = os.path.join(script_dir, "src", "harness", "data", "eval_dataset.json")
    output_path = os.path.join(script_dir, "..", "..", "docs", "eval-report.md")
    output_path = os.path.abspath(output_path)

    if not os.path.exists(dataset_path):
        print(f"[ERROR] Dataset not found at {dataset_path}")
        return

    print(f"[*] Loading evaluation dataset: {dataset_path}")
    dataset = load_dataset(dataset_path)

    print(f"[*] Connecting to engine at: {url}")
    try:
        report_data = run_evaluation(url, dataset)
    except Exception as e:
        print(f"[ERROR] Running evaluation: {e}")
        return

    print(f"[*] Generating report: {output_path}")
    generate_markdown_report(report_data, output_path)

    print("[DONE] Evaluation complete:")
    print(f"  Total cases:    {report_data['total_cases']}")
    print(f"  Skip accuracy:  {report_data['skip_accuracy'] * 100:.1f}%")
    print(f"  Avg F1-score:   {report_data['avg_f1'] * 100:.1f}%")
    print(f"  Avg latency:    {report_data['avg_latency_ms']:.1f} ms")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()

    # The eval command can run when engine is online
    if cmd != "eval" and not check_engine():
        print(f"[ERROR] Engine offline at {BASE}")
        print("Start the engine first, then re-run this script.")
        sys.exit(1)

    if cmd == "export":
        filename = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_export(filename)
    elif cmd == "import":
        if len(sys.argv) < 3:
            print("[ERROR] Usage: python manage_experiences.py import <filename> [--overwrite]")
            sys.exit(1)
        filename = sys.argv[2]
        overwrite = "--overwrite" in sys.argv
        cmd_import(filename, overwrite)
    elif cmd == "count":
        cmd_count()
    elif cmd == "eval":
        url = None
        if "--url" in sys.argv:
            try:
                idx = sys.argv.index("--url")
                if idx + 1 < len(sys.argv):
                    url = sys.argv[idx + 1]
            except ValueError:
                pass
        cmd_eval(url)
    else:
        print(f"[ERROR] Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
