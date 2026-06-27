"""
Loomind — All-in-One Build Script
Builds engine.exe + Tauri installer in one command.

Usage:
    python build_all.py

Output:
    apps/loomind-desktop/src-tauri/target/release/bundle/nsis/Loomind_0.1.0_x64-setup.exe
"""

import os
import sys
import shutil
import subprocess
import platform


# ── Paths ──
ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.join(ROOT, "core", "loomind-engine")
DESKTOP_DIR = os.path.join(ROOT, "apps", "loomind-desktop")
TAURI_DIR = os.path.join(DESKTOP_DIR, "src-tauri")
BINARIES_DIR = os.path.join(TAURI_DIR, "binaries")


def get_target_triple() -> str:
    """Get the Rust target triple for the current platform."""
    result = subprocess.run(
        ["rustc", "-Vv"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    # Fallback
    if platform.system() == "Windows":
        return "x86_64-pc-windows-msvc"
    elif platform.system() == "Darwin":
        return "aarch64-apple-darwin" if platform.machine() == "arm64" else "x86_64-apple-darwin"
    return "x86_64-unknown-linux-gnu"


def step(num: int, title: str):
    print(f"\n{'=' * 60}")
    print(f"  Step {num}: {title}")
    print(f"{'=' * 60}\n")


def main():
    print("🚀 Loomind — All-in-One Build")
    print(f"   Platform: {platform.system()} {platform.machine()}")

    target = get_target_triple()
    print(f"   Target: {target}")

    # ── Step 1: Build Engine .exe ──
    step(1, "Building Python Engine (PyInstaller)")

    os.chdir(ENGINE_DIR)
    result = subprocess.run(
        [sys.executable, "build_exe.py"],
        cwd=ENGINE_DIR,
    )
    if result.returncode != 0:
        print("[FAIL] Engine build failed!")
        sys.exit(1)

    engine_exe = os.path.join(ENGINE_DIR, "dist", "loomind-engine.exe")
    if not os.path.exists(engine_exe):
        print(f"[FAIL] Expected {engine_exe} but not found!")
        sys.exit(1)
    size_mb = os.path.getsize(engine_exe) / (1024 * 1024)
    print(f"[OK] Engine built: {engine_exe} ({size_mb:.1f} MB)")

    # ── Step 2: Copy engine to Tauri binaries ──
    step(2, "Copying engine binary to Tauri sidecar")

    os.makedirs(BINARIES_DIR, exist_ok=True)

    # Clean old onedir artifacts if present
    old_dist = os.path.join(BINARIES_DIR, "loomind-engine-dist")
    if os.path.exists(old_dist):
        shutil.rmtree(old_dist)
        print(f"[OK] Cleaned old onedir artifacts")

    ext = ".exe" if platform.system() == "Windows" else ""
    dest = os.path.join(BINARIES_DIR, f"loomind-engine-{target}{ext}")

    # Copy single .exe with target triple naming
    shutil.copy2(engine_exe, dest)
    print(f"[OK] Copied to {dest}")

    # ── Step 3: Build frontend ──
    step(3, "Building Frontend (Vite)")

    os.chdir(ROOT)
    result = subprocess.run(["npx", "turbo", "build"], cwd=ROOT, shell=True)
    if result.returncode != 0:
        print("[FAIL] Frontend build failed!")
        sys.exit(1)
    print("[OK] Frontend built")

    # ── Step 4: Build Tauri installer ──
    step(4, "Building Tauri Installer")

    os.chdir(DESKTOP_DIR)
    result = subprocess.run(
        ["npx", "tauri", "build"],
        cwd=DESKTOP_DIR,
        shell=True,
    )
    if result.returncode != 0:
        print("[FAIL] Tauri build failed!")
        sys.exit(1)

    # Find the installer
    nsis_dir = os.path.join(TAURI_DIR, "target", "release", "bundle", "nsis")
    msi_dir = os.path.join(TAURI_DIR, "target", "release", "bundle", "msi")

    print("\n" + "=" * 60)
    print("  BUILD COMPLETE!")
    print("=" * 60)

    if os.path.exists(nsis_dir):
        for f in os.listdir(nsis_dir):
            if f.endswith(".exe"):
                print(f"  NSIS Installer: {os.path.join(nsis_dir, f)}")

    if os.path.exists(msi_dir):
        for f in os.listdir(msi_dir):
            if f.endswith(".msi"):
                print(f"  MSI Installer:  {os.path.join(msi_dir, f)}")

    print(f"\n  Share the installer with your users!")
    print("=" * 60)


if __name__ == "__main__":
    main()
