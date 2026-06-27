import os
import json
import time
import argparse
import httpx
from typing import List, Dict, Any

def load_dataset(filepath: str) -> List[Dict[str, Any]]:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def run_evaluation(url: str, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
    client = httpx.Client(timeout=10.0)

    total_cases = len(dataset)
    skipped_correct = 0
    not_skipped_correct = 0
    total_skips_expected = 0
    total_skips_actual = 0

    precisions = []
    recalls = []
    f1_scores = []
    latencies = []

    results = []

    for case in dataset:
        action = case["action"]
        action_type = case.get("action_type", "unknown")
        file_path = case.get("file_path", "")
        language = case.get("language", "")
        expected_titles = case.get("expected_experience_titles", [])
        expected_skip = case.get("expected_skip", False)

        payload = {
            "action": action,
            "action_type": action_type,
            "file_path": file_path,
            "language": language
        }

        if expected_skip:
            total_skips_expected += 1

        start_time = time.perf_counter()
        try:
            response = client.post(f"{url}/api/intercept", json=payload)
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            if response.status_code != 200:
                results.append({
                    "case": case,
                    "status": "error",
                    "error": f"HTTP status {response.status_code}",
                    "latency_ms": latency_ms
                })
                continue

            data = response.json()
            actual_skip = data.get("skipped", False)
            suggestions = data.get("suggestions", [])
            actual_latency = data.get("latency_ms", latency_ms)
            latencies.append(actual_latency)

            if actual_skip:
                total_skips_actual += 1

            # Skip evaluation
            skip_match = (actual_skip == expected_skip)
            if skip_match:
                if expected_skip:
                    skipped_correct += 1
                else:
                    not_skipped_correct += 1

            # Suggestion evaluation
            if not expected_skip:
                returned_titles = [s.get("title", "") for s in suggestions]

                tp = len([t for t in returned_titles if t in expected_titles])
                fp = len([t for t in returned_titles if t not in expected_titles])
                fn = len([t for t in expected_titles if t not in returned_titles])

                precision = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if len(expected_titles) == 0 else 0.0)
                recall = tp / (tp + fn) if (tp + fn) > 0 else (1.0 if len(expected_titles) == 0 else 0.0)
                f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else (1.0 if (precision == 1.0 and recall == 1.0) else 0.0)

                precisions.append(precision)
                recalls.append(recall)
                f1_scores.append(f1)
            else:
                precision, recall, f1 = 1.0, 1.0, 1.0

            results.append({
                "case": case,
                "status": "success",
                "actual_skip": actual_skip,
                "actual_titles": [s.get("title", "") for s in suggestions],
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "latency_ms": actual_latency
            })

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            results.append({
                "case": case,
                "status": "error",
                "error": str(e),
                "latency_ms": latency_ms
            })

    client.close()

    skip_accuracy = (skipped_correct + not_skipped_correct) / total_cases if total_cases > 0 else 0.0
    avg_precision = sum(precisions) / len(precisions) if precisions else 0.0
    avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
    avg_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0.0

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    max_latency = max(latencies) if latencies else 0.0
    min_latency = min(latencies) if latencies else 0.0

    return {
        "total_cases": total_cases,
        "skip_accuracy": skip_accuracy,
        "avg_precision": avg_precision,
        "avg_recall": avg_recall,
        "avg_f1": avg_f1,
        "avg_latency_ms": avg_latency,
        "max_latency_ms": max_latency,
        "min_latency_ms": min_latency,
        "results": results
    }

def generate_markdown_report(report_data: Dict[str, Any], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Loomind Experience Engine - Evaluation Harness Report\n\n")
        f.write(f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## Aggregate Metrics\n\n")
        f.write("| Metric | Value |\n")
        f.write("|--------|-------|\n")
        f.write(f"| Total Test Cases | {report_data['total_cases']} |\n")
        f.write(f"| Skip Accuracy | {report_data['skip_accuracy'] * 100:.1f}% |\n")
        f.write(f"| Average Precision | {report_data['avg_precision'] * 100:.1f}% |\n")
        f.write(f"| Average Recall | {report_data['avg_recall'] * 100:.1f}% |\n")
        f.write(f"| Average F1-Score | {report_data['avg_f1'] * 100:.1f}% |\n")
        f.write(f"| Avg Latency | {report_data['avg_latency_ms']:.2f} ms |\n")
        f.write(f"| Min Latency | {report_data['min_latency_ms']:.2f} ms |\n")
        f.write(f"| Max Latency | {report_data['max_latency_ms']:.2f} ms |\n\n")

        f.write("## Test Cases Detailed Results\n\n")
        f.write("| Action | Type | Expected Skip | Actual Skip | Precision | Recall | F1 | Latency | Status |\n")
        f.write("|--------|------|---------------|-------------|-----------|--------|----|---------|--------|\n")

        for r in report_data["results"]:
            case = r["case"]
            status = r["status"]

            action = case["action"]
            action_type = case.get("action_type", "unknown")
            expected_skip = "Yes" if case.get("expected_skip", False) else "No"

            if status == "success":
                actual_skip = "Yes" if r["actual_skip"] else "No"
                precision = f"{r['precision'] * 100:.0f}%"
                recall = f"{r['recall'] * 100:.0f}%"
                f1 = f"{r['f1'] * 100:.0f}%"
                latency = f"{r['latency_ms']:.1f} ms"
                line = f"| {action} | {action_type} | {expected_skip} | {actual_skip} | {precision} | {recall} | {f1} | {latency} | [SUCCESS] |\n"
            else:
                error = r.get("error", "Unknown error")
                line = f"| {action} | {action_type} | {expected_skip} | - | - | - | - | {r['latency_ms']:.1f} ms | [FAILED: {error}] |\n"
            f.write(line)

def main() -> None:
    parser = argparse.ArgumentParser(description="Loomind Experience Engine Evaluation Harness")
    parser.add_argument("--url", default="http://127.0.0.1:8082", help="URL of the running Experience Engine")
    parser.add_argument("--dataset", help="Path to evaluation dataset JSON")
    parser.add_argument("--output", help="Path to write the markdown report")

    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))

    dataset_path = args.dataset or os.path.join(script_dir, "data", "eval_dataset.json")
    output_path = args.output or os.path.join(script_dir, "..", "..", "..", "..", "docs", "eval-report.md")
    output_path = os.path.abspath(output_path)

    if not os.path.exists(dataset_path):
        print(f"Error: Dataset not found at {dataset_path}")
        return

    print(f"Loading evaluation dataset: {dataset_path}")
    dataset = load_dataset(dataset_path)

    print(f"Connecting to engine at: {args.url}")
    try:
        report_data = run_evaluation(args.url, dataset)
    except Exception as e:
        print(f"Fatal Error running evaluation: {e}")
        print("Please ensure the engine is running or specify the correct --url.")
        return

    print(f"Generating report: {output_path}")
    generate_markdown_report(report_data, output_path)

    print("Evaluation Complete!")
    print(f"  Total test cases: {report_data['total_cases']}")
    print(f"  Skip accuracy:    {report_data['skip_accuracy'] * 100:.1f}%")
    print(f"  Average F1-score: {report_data['avg_f1'] * 100:.1f}%")
    print(f"  Average latency:  {report_data['avg_latency_ms']:.1f} ms")

if __name__ == "__main__":
    main()
