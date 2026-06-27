import os
import sys

# Add core/loomind-engine to path so we can import src
script_dir = os.path.dirname(os.path.abspath(__file__))
engine_path = os.path.abspath(os.path.join(script_dir, "..", "core", "loomind-engine"))
if engine_path not in sys.path:
    sys.path.insert(0, engine_path)

from src.client import LoomindClient

def main():
    client = LoomindClient(base_url="http://127.0.0.1:8082")

    print("Checking Experience Engine health...")
    if not client.is_healthy():
        print("  [WARNING] Experience Engine is offline. Please start it using:")
        print("            python -m uvicorn src.main:app --host 127.0.0.1 --port 8082")
        print("            Running in offline client-side simulation...\n")

    # Example action to intercept
    action = "create a new database connection pool"
    print(f"Intercepting action: '{action}'")

    res = client.intercept(action=action, action_type="write", file_path="src/db.py", language="python")

    print("\nIntercept Response:")
    print(f"  Skipped:          {res.get('skipped', False)}")
    print(f"  Latency:          {res.get('latency_ms', 0.0):.1f} ms")
    print(f"  Layers Executed:  {', '.join(res.get('layers_executed', []))}")

    suggestions = res.get("suggestions", [])
    if suggestions:
        print(f"  Suggestions Found ({len(suggestions)}):")
        for s in suggestions:
            print(f"    - [{s.get('severity', 'info').upper()}] {s.get('title')}: {s.get('message')}")
    else:
        print("  No suggestions found.")

    client.close()

if __name__ == "__main__":
    main()
