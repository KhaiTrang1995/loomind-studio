"""
Save PyInstaller + Tauri Sidecar build experiences to the engine.
Run this when the engine is online:
    python save_build_experiences.py
"""
import requests
import sys

BASE = "http://localhost:8082"

EXPERIENCES = [
    {
        "title": "PyInstaller --onefile is required for Tauri sidecar",
        "description": (
            "Tauri externalBin only bundles a single executable file. "
            "PyInstaller --onedir creates a folder with DLLs that Tauri cannot bundle → app crashes on launch. "
            "ALWAYS use --onefile for Tauri sidecar binaries. Trade-off: first launch is slower (20-60s) "
            "because --onefile extracts all dependencies to %%TEMP%%/_MEIxxxx on each run."
        ),
        "category": "gotcha",
        "severity": "critical",
        "tags": ["pyinstaller", "tauri", "sidecar", "onefile", "windows"],
    },
    {
        "title": "PyInstaller frozen mode: use sys._MEIPASS for sys.path",
        "description": (
            "When running as PyInstaller --onefile .exe, Python files are extracted to sys._MEIPASS "
            "(a temp directory like %%TEMP%%/_MEI12345). You MUST add sys._MEIPASS to sys.path[0] "
            "before any project imports, otherwise 'import src.xxx' will fail with ModuleNotFoundError. "
            "Also os.chdir(sys._MEIPASS) so relative paths work."
        ),
        "category": "gotcha",
        "severity": "critical",
        "tags": ["pyinstaller", "sys-path", "meipass", "frozen", "import"],
    },
    {
        "title": "uvicorn.run() must use app object not string in frozen mode",
        "description": (
            "uvicorn.run('src.main:app') uses string import which fails in PyInstaller frozen mode "
            "because the module discovery doesn't work with extracted temp directories. "
            "ALWAYS use uvicorn.run(app) with the direct app object reference when building "
            "standalone .exe with PyInstaller. String import only works in development mode."
        ),
        "category": "gotcha",
        "severity": "critical",
        "tags": ["uvicorn", "pyinstaller", "frozen", "fastapi", "import"],
    },
    {
        "title": "Tauri sidecar: never use .expect() for spawn - use match",
        "description": (
            "Tauri sidecar binary may not exist (dev mode, missing build step, wrong platform). "
            "Using .expect() on sidecar spawn will panic and crash the entire app with a flash. "
            "ALWAYS use match/if-let to handle spawn failure gracefully — show the dashboard "
            "in 'manual engine' mode so user can connect to an external engine."
        ),
        "category": "gotcha",
        "severity": "critical",
        "tags": ["tauri", "rust", "sidecar", "panic", "graceful-degradation"],
    },
    {
        "title": "Tauri 2.10+ requires 'use tauri::Emitter' for .emit()",
        "description": (
            "In Tauri 2.10+, the emit() method was moved to a separate Emitter trait. "
            "You must add 'use tauri::Emitter;' at the top of your Rust file, "
            "otherwise you get: 'no method named emit found for struct AppHandle'. "
            "This is a breaking change from Tauri 2.0-2.9."
        ),
        "category": "gotcha",
        "severity": "warning",
        "tags": ["tauri", "rust", "emit", "breaking-change", "trait"],
    },
    {
        "title": "PyInstaller build checklist for ML apps",
        "description": (
            "ML apps (PyTorch, sentence-transformers) with PyInstaller: "
            "1) Test launcher.py standalone first, "
            "2) Build .exe and test it standalone before integrating with Tauri, "
            "3) Always add --hidden-import for torch, numpy, uvicorn.*, starlette, anyio, "
            "4) Use --console (not --windowed) so you can see error messages, "
            "5) First launch of --onefile takes 20-60s (extraction), subsequent 5-15s, "
            "6) sys.stdout.flush() after every print — sidecar pipe may buffer output. "
            "See docs/build-checklist.md for the full checklist."
        ),
        "category": "pattern",
        "severity": "info",
        "tags": ["pyinstaller", "ml", "checklist", "torch", "build"],
    },
    {
        "title": "NEVER use Tauri sidecar() API with large PyInstaller binaries",
        "description": (
            "Tauri's shell.sidecar() API fails with 'os error 3' (path not found) "
            "even when the binary file exists. This happens with large PyInstaller .exe files (200MB+). "
            "The sidecar path resolution has issues in both dev and production modes. "
            "SOLUTION: Use std::process::Command directly instead of ShellExt::sidecar(). "
            "Implement a find_engine_binary() function that searches multiple locations: "
            "1) Next to the Tauri .exe (production), 2) Resource dir, 3) src-tauri/binaries/ (dev), "
            "4) Working directory. This approach is more reliable and debuggable."
        ),
        "category": "gotcha",
        "severity": "critical",
        "tags": ["tauri", "sidecar", "pyinstaller", "os-error-3", "std-process"],
    },
    {
        "title": "Use 127.0.0.1 not localhost in Tauri WebView fetch calls",
        "description": (
            "In Tauri production WebView, 'localhost' may not resolve correctly. "
            "All fetch() calls to the engine API must use 'http://127.0.0.1:8082' instead of "
            "'http://localhost:8082'. Also update CSP in tauri.conf.json to allow both: "
            "connect-src 'self' http://localhost:8082 http://127.0.0.1:8082"
        ),
        "category": "gotcha",
        "severity": "critical",
        "tags": ["tauri", "webview", "localhost", "csp", "fetch"],
    },
    {
        "title": "Use AbortController instead of AbortSignal.timeout() in Tauri WebView",
        "description": (
            "AbortSignal.timeout() may not be supported in Tauri's WebView engine. "
            "Always use the manual AbortController pattern for fetch timeouts: "
            "const controller = new AbortController(); "
            "const timeout = setTimeout(() => controller.abort(), 2000); "
            "fetch(url, { signal: controller.signal }).finally(() => clearTimeout(timeout));"
        ),
        "category": "gotcha",
        "severity": "warning",
        "tags": ["tauri", "webview", "fetch", "abort", "timeout"],
    },
    {
        "title": "Rust MutexGuard borrow checker: always separate into let binding",
        "description": (
            "Chaining .lock().unwrap().take() in a single expression causes Rust borrow checker "
            "lifetime errors because the MutexGuard temporary doesn't live long enough. "
            "ALWAYS separate: let mut guard = state.0.lock().unwrap(); "
            "if let Some(child) = guard.take() { ... } drop(guard);"
        ),
        "category": "gotcha",
        "severity": "warning",
        "tags": ["rust", "mutex", "borrow-checker", "lifetime", "guard"],
    },
    {
        "title": "Tauri + PyInstaller build: ALWAYS verify step by step, never skip",
        "description": (
            "Build order must be verified sequentially — STOP if any step fails: "
            "1) Test launcher.py standalone, 2) Build .exe and test standalone, "
            "3) Copy .exe to binaries/, 4) Run npx tauri dev — check Rust logs, "
            "5) Only then npx tauri build. Skipping verification leads to silent failures "
            "that are extremely hard to debug in the final installer."
        ),
        "category": "pattern",
        "severity": "critical",
        "tags": ["build", "checklist", "verification", "deployment", "sequential"],
    },
]


def main():
    # Check engine is online
    try:
        r = requests.get(f"{BASE}/health", timeout=3)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Engine offline: {e}")
        print("Start the engine first, then re-run this script.")
        sys.exit(1)

    print(f"[OK] Engine online\n")

    saved = 0
    for exp in EXPERIENCES:
        try:
            r = requests.post(f"{BASE}/api/experiences", json=exp, timeout=10)
            r.raise_for_status()
            data = r.json()
            print(f"  [OK] {data['id'][:8]}... | {exp['title']}")
            saved += 1
        except Exception as e:
            print(f"  [FAIL] {exp['title']}: {e}")

    print(f"\n[DONE] Saved {saved}/{len(EXPERIENCES)} experiences")


if __name__ == "__main__":
    main()
