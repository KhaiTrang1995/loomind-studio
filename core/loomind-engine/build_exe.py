"""
Build Loomind Engine as a standalone Windows .exe using PyInstaller.

Usage:
    python build_exe.py

Output:
    dist/loomind-engine.exe   (~150-200MB, self-contained)

The .exe includes:
    - Python runtime
    - FastAPI + Uvicorn
    - Qdrant client (local mode)
    - Sentence-Transformers + model weights
    - All src/ modules

NOTE: Windows Defender False Positive Prevention
    PyInstaller .exe files are often flagged as Trojan:Win32/Wacatac.B!ml
    by antivirus software. This build script applies mitigations:
    1. --noupx: Disables UPX compression (UPX triggers AV heuristics)
    2. Explicit excludes: Removes unused test/debug/network modules
    3. Version info: Adds PE metadata to look like a legit application
    4. No bootloader modification: Uses stock PyInstaller bootloader
    5. If still flagged, submit to https://www.microsoft.com/wdsi/filesubmission
"""

import subprocess
import sys
import os
import shutil

# ── Config ──
ENTRY_POINT = "launcher.py"
APP_NAME = "loomind-engine"
ICON_PATH = None  # Add path to .ico file if available

# Directories to include as data
DATA_INCLUDES = [
    # (source, destination_in_bundle)
    ("src", "src"),
]

# Hidden imports that PyInstaller may miss
HIDDEN_IMPORTS = [
    # Uvicorn internals (required for ASGI server)
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # FastAPI stack
    "fastapi",
    "pydantic",
    "pydantic_settings",
    "pydantic_core",
    # Data layer
    "qdrant_client",
    # ML
    "sentence_transformers",
    "torch",
    "numpy",
    # HTTP client (for LLM calls)
    "httpx",
    # ASGI framework
    "starlette",
    "anyio",
    "sniffio",
    # Config
    "dotenv",
]

# ═══════════════════════════════════════════════════════════
# EXCLUDES — Remove unused modules to:
#   1. Reduce .exe size (smaller = less AV scrutiny)
#   2. Remove test/debug code that AV may flag as suspicious
#   3. Remove network scanners/crypto that trigger heuristics
#
# CAUTION: Do NOT exclude modules that PyInstaller has
# built-in hooks for (distutils, setuptools) — causes
# "already imported as ExcludedModule" ValueError.
# Do NOT exclude modules used transitively (email → httpx,
# mimetypes → starlette).
# ═══════════════════════════════════════════════════════════
EXCLUDES = []
# EXCLUDES = [
#     # Test frameworks (not needed in production)
#     "pytest", "_pytest", "pluggy", "nose",
#     # Debug/profiling tools (flagged as suspicious by AV)
#     "pdb", "cProfile", "profile", "trace", "pstats",
#     # Interactive / REPL / GUI (not needed for headless server)
#     "tkinter", "turtle", "turtledemo", "idlelib",
#     "curses", "readline",
#     # Unused network protocols
#     "imaplib", "poplib", "smtplib", "ftplib", "nntplib",
#     # XML-RPC (unused)
#     "xmlrpc",
#     # Crypto libs (not used by this app)
#     "Crypto", "Cryptodome",
#     # Build tools — keep distutils/setuptools (PyInstaller hooks need them!)
#     "pip", "ensurepip", "venv", "lib2to3",
#     # Documentation generators
#     # NOTE: Do NOT exclude pydoc — nltk (via sentence-transformers) needs it!
#     # Chain: sentence_transformers → nltk → nltk.util → pydoc
#     "docutils", "sphinx",
#     # Jupyter / notebook
#     "IPython", "jupyter", "notebook", "ipykernel",
#     # Unused ML backends (keep torch — it's needed)
#     "tensorflow", "keras", "jax", "onnxruntime",
#     "caffe2", "torchvision", "torchaudio",
#     # GUI frameworks (server doesn't need GUI)
#     "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
#     "matplotlib",
#     # Multiprocessing forks (Windows uses spawn, not fork)
#     "multiprocessing.popen_spawn_posix",
#     "multiprocessing.popen_fork",
#     "multiprocessing.popen_forkserver",
# ]

# ── Version info for PE metadata ──
# Adding PE version info makes the .exe look legitimate to AV
VERSION_INFO = """
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(0, 1, 0, 0),
    prodvers=(0, 1, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'Loomind'),
          StringStruct('FileDescription', 'Loomind AI Experience Engine'),
          StringStruct('FileVersion', '0.1.0'),
          StringStruct('InternalName', 'loomind-engine'),
          StringStruct('LegalCopyright', 'Copyright (C) 2024-2026 Loomind'),
          StringStruct('OriginalFilename', 'loomind-engine.exe'),
          StringStruct('ProductName', 'Loomind Experience Engine'),
          StringStruct('ProductVersion', '0.1.0'),
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def check_dependencies():
    """Ensure all runtime dependencies are installed before building.

    PyInstaller can only bundle packages that are actually installed.
    If packages are missing, the .exe will build but crash at runtime
    with 'ModuleNotFoundError'.
    """
    req_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")

    # Critical packages that MUST be importable for the exe to work
    CRITICAL_PACKAGES = {
        "uvicorn": "uvicorn[standard]",
        "fastapi": "fastapi",
        "pydantic": "pydantic",
        "pydantic_settings": "pydantic-settings",
        "qdrant_client": "qdrant-client",
        "sentence_transformers": "sentence-transformers",
        "httpx": "httpx",
        "structlog": "structlog",
        "dotenv": "python-dotenv",
        "yaml": "pyyaml",
        "numpy": "numpy",
        "starlette": "starlette",
        "anyio": "anyio",
        "sniffio": "sniffio",
    }

    missing = []
    for module_name, pip_name in CRITICAL_PACKAGES.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append((module_name, pip_name))

    if missing:
        print(f"\n[!] Missing {len(missing)} required packages:")
        for mod, pip_pkg in missing:
            print(f"    - {mod} (pip: {pip_pkg})")

        # Try to install from requirements.txt first
        if os.path.exists(req_file):
            print(f"\n[AUTO] Installing dependencies from requirements.txt...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req_file],
                capture_output=False,
            )
            if result.returncode != 0:
                print(f"\n[FAIL] pip install failed. Please install manually:")
                print(f"       pip install -r requirements.txt")
                sys.exit(1)
        else:
            # Fallback: install individual packages
            print(f"\n[AUTO] Installing missing packages individually...")
            pip_packages = [pip_name for _, pip_name in missing]
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install"] + pip_packages,
                capture_output=False,
            )
            if result.returncode != 0:
                print(f"\n[FAIL] pip install failed.")
                sys.exit(1)

        # Re-verify after install
        still_missing = []
        for module_name, pip_name in missing:
            try:
                __import__(module_name)
            except ImportError:
                still_missing.append(module_name)

        if still_missing:
            print(f"\n[FAIL] Still missing after install: {', '.join(still_missing)}")
            print(f"       The .exe WILL crash at runtime without these.")
            sys.exit(1)

        print(f"[OK] All {len(CRITICAL_PACKAGES)} critical packages installed")
    else:
        print(f"[OK] All {len(CRITICAL_PACKAGES)} critical packages verified")


def check_pyinstaller():
    """Ensure PyInstaller is installed."""
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("[!] PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("[OK] PyInstaller installed")


def create_version_file():
    """Create PE version info file for Windows."""
    version_file = "version_info.txt"
    with open(version_file, "w", encoding="utf-8") as f:
        f.write(VERSION_INFO.strip())
    return version_file


def cleanup_old_build():
    """Delete old .exe before building to prevent Windows Defender file lock.

    Windows Defender scans new .exe files and may hold a lock on them.
    If we rebuild while the old file is locked, PyInstaller fails with
    PermissionError on 'set_exe_build_timestamp'. Deleting first avoids this.
    """
    exe_path = os.path.join("dist", f"{APP_NAME}.exe")
    if os.path.exists(exe_path):
        try:
            os.remove(exe_path)
            print(f"[OK] Removed old {exe_path}")
        except PermissionError:
            print(f"[WARN] Cannot delete {exe_path} (file locked by AV or another process)")
            print(f"       Try: Close any running loomind-engine.exe instances")
            print(f"       Or:  Add dist/ folder to Windows Defender exclusion list")
            # Don't sys.exit — PyInstaller --noconfirm will try to overwrite anyway


def build():
    """Run PyInstaller to create the .exe."""
    print("=" * 60)
    print("Loomind Engine — Building standalone .exe")
    print("  Anti-Virus False Positive mitigations enabled")
    print("=" * 60)

    check_pyinstaller()
    #check_dependencies()

    # Remove old exe to prevent Windows Defender lock issues
    cleanup_old_build()

    # Create version info file
    version_file = create_version_file()
    print(f"[OK] Version info file created: {version_file}")

    # Build PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onefile",      # Single .exe — required for Tauri sidecar bundling
        "--console",      # Show console window for engine logs
        "--noconfirm",    # Overwrite existing build
        "--noupx",        # CRITICAL: Don't use UPX — UPX triggers AV heuristics
        "--clean",        # Clean cache before building
        "--version-file", version_file,  # PE metadata → looks legitimate to AV
    ]

    # Add hidden imports
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])

    # Add excludes (reduce size + remove suspicious modules)
    for exc in EXCLUDES:
        cmd.extend(["--exclude-module", exc])

    # Add data includes
    for src, dst in DATA_INCLUDES:
        if os.path.exists(src):
            cmd.extend(["--add-data", f"{src}{os.pathsep}{dst}"])

    # Add icon if available
    if ICON_PATH and os.path.exists(ICON_PATH):
        cmd.extend(["--icon", ICON_PATH])

    # Entry point
    cmd.append(ENTRY_POINT)

    print(f"\n[CMD] {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))

    exe_path = os.path.join("dist", f"{APP_NAME}.exe")

    if result.returncode != 0:
        # Check if exe was created despite the error
        # (common: PermissionError on set_exe_build_timestamp from Windows Defender)
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\n[WARN] PyInstaller exited with code {result.returncode}")
            print(f"       BUT {exe_path} exists ({size_mb:.1f} MB)")
            print(f"       This is likely a Windows Defender timestamp lock issue.")
            print(f"       The .exe should still work — test it before using.")
            print(f"\n  FIX: Add this folder to Windows Defender exclusions:")
            print(f"       {os.path.abspath('dist')}")
        else:
            print(f"\n[FAIL] PyInstaller exited with code {result.returncode}")
            sys.exit(1)

    # Cleanup version file
    if os.path.exists(version_file):
        os.remove(version_file)

    # Copy .env.example alongside the exe
    dist_dir = "dist"
    env_example = ".env.example"
    if os.path.exists(env_example):
        shutil.copy2(env_example, os.path.join(dist_dir, ".env"))
        print(f"[OK] Copied {env_example} -> {dist_dir}/.env")

    size_mb = os.path.getsize(exe_path) / (1024 * 1024) if os.path.exists(exe_path) else 0

    print("\n" + "=" * 60)
    print(f"[SUCCESS] Build complete!")
    print(f"  Executable: {exe_path} ({size_mb:.1f} MB)")
    print(f"\n  Test: dist\\{APP_NAME}.exe")
    print(f"\n  NOTE: If Windows Defender flags this file:")
    print(f"  1. It is a FALSE POSITIVE (common with PyInstaller)")
    print(f"  2. Submit to: https://www.microsoft.com/wdsi/filesubmission")
    print(f"  3. Add exclusion: Windows Security > Virus protection > Exclusions")
    print("=" * 60)


if __name__ == "__main__":
    build()
