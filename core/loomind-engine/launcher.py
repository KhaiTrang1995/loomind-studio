"""
Loomind Experience Engine — Standalone Launcher
Entry point for PyInstaller bundle (.exe).

Handles:
- Frozen mode detection (PyInstaller --onefile)
- sys.path fix for _MEIPASS extraction directory
- Data directory setup (%APPDATA%/Loomind/)
- Direct uvicorn startup (no string import — crucial for frozen mode)
- Graceful shutdown on SIGTERM/SIGINT (from Tauri sidecar kill)
"""

from __future__ import annotations

import os
import sys
import signal
import time

# ═══════════════════════════════════════════════════════════
# STEP 1: Fix Python path BEFORE any project imports
# PyInstaller --onefile extracts to sys._MEIPASS (%TEMP%/_MEIxxxx)
# We must add it to sys.path so `import src.xxx` works
# ═══════════════════════════════════════════════════════════

IS_FROZEN = getattr(sys, "frozen", False)
STARTUP_TIME = time.time()

if IS_FROZEN:
    # _MEIPASS is where PyInstaller extracts bundled files
    MEIPASS = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    BUNDLE_DIR = os.path.dirname(sys.executable)

    # Add extraction dir to sys.path (so `from src.xxx import` works)
    if MEIPASS not in sys.path:
        sys.path.insert(0, MEIPASS)

    # Also set working directory to extraction dir
    os.chdir(MEIPASS)

    # Use %APPDATA%/Loomind for persistent data
    APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
    DATA_DIR = os.path.join(APPDATA, "Loomind")
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "data", "qdrant"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)

    # Set environment variables for the engine config
    os.environ.setdefault("QDRANT_MODE", "local")
    os.environ.setdefault("QDRANT_PATH", os.path.join(DATA_DIR, "data", "qdrant"))
    os.environ.setdefault("ENGINE_HOST", "127.0.0.1")
    os.environ.setdefault("ENGINE_PORT", "8082")
    os.environ.setdefault("ENGINE_LOG_LEVEL", "info")
    os.environ.setdefault("LOG_FILE", os.path.join(DATA_DIR, "logs", "engine.log"))

    # Load .env if exists alongside .exe (not inside bundle)
    env_file = os.path.join(BUNDLE_DIR, ".env")
    if os.path.exists(env_file):
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except ImportError:
            pass  # dotenv optional

    print(f"[Loomind] Standalone mode (PyInstaller)")
    print(f"[Loomind] Bundle: {MEIPASS}")
    print(f"[Loomind] Data:   {DATA_DIR}")
    print(f"[Loomind] sys.path[0]: {sys.path[0]}")
    sys.stdout.flush()


def main() -> None:
    """Start the Experience Engine server."""
    if "--mcp" in sys.argv:
        try:
            from src.presentation.mcp_server import mcp
            import logging
            logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
            mcp.run(transport="stdio")
            sys.exit(0)
        except Exception as e:
            import traceback
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)

    print(f"[Loomind] Importing modules...")
    sys.stdout.flush()

    try:
        import uvicorn
        print(f"[Loomind] uvicorn OK ({time.time() - STARTUP_TIME:.1f}s)")
        sys.stdout.flush()
    except Exception as e:
        print(f"[Loomind] FATAL: Cannot import uvicorn: {e}")
        sys.stdout.flush()
        input("Press Enter to exit...")
        sys.exit(1)

    try:
        from src.main import app
        print(f"[Loomind] src.main OK ({time.time() - STARTUP_TIME:.1f}s)")
        sys.stdout.flush()
    except Exception as e:
        print(f"[Loomind] FATAL: Cannot import src.main: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        input("Press Enter to exit...")
        sys.exit(1)

    try:
        from src.config import settings
    except Exception:
        # Fallback defaults if config fails
        class settings:  # type: ignore
            engine_host = "127.0.0.1"
            engine_port = 8082
            engine_log_level = "info"

    host = settings.engine_host
    port = settings.engine_port
    log_level = settings.engine_log_level

    print(f"[Loomind] Starting engine on http://{host}:{port}")
    print(f"[Loomind] Startup time: {time.time() - STARTUP_TIME:.1f}s")
    print(f"[Loomind] Press Ctrl+C to stop")
    sys.stdout.flush()

    # Graceful shutdown handler
    def handle_shutdown(signum: int, frame: object) -> None:
        print(f"\n[Loomind] Received signal {signum}, shutting down...")
        sys.stdout.flush()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    try:
        # CRITICAL: Use app object directly, NOT string "src.main:app"
        # String import doesn't work in PyInstaller frozen mode!
        uvicorn.run(
            app,  # Direct reference — works in frozen mode
            host=host,
            port=port,
            log_level=log_level,
        )
    except SystemExit:
        print("[Loomind] Engine stopped.")
    except Exception as e:
        print(f"[Loomind] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        input("Press Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    main()
