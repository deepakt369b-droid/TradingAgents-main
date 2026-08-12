"""Build script for TradingAgents Desktop.

Usage:
    python scripts/build.py          # Build the .exe
    python scripts/build.py --clean  # Clean first, then build
    python scripts/build.py --zip    # Build and create .zip distribution

Prerequisites:
    pip install ".[desktop,build]"
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT / "tradingagents.spec"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
ICON_SRC = ROOT / "assets" / "TauricResearch.png"
ICON_DST = ROOT / "assets" / "app_icon.ico"


def generate_icon():
    """Convert TauricResearch.png to a multi-resolution .ico file."""
    if ICON_DST.exists():
        print(f"  Icon already exists: {ICON_DST}")
        return True

    if not ICON_SRC.exists():
        print(f"  Warning: Source image not found: {ICON_SRC}")
        print("  Building without custom icon.")
        return False

    try:
        from PIL import Image

        img = Image.open(ICON_SRC)
        # Convert to RGBA if needed
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        # Generate multi-resolution icon
        sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
        icon_images = []
        for size in sizes:
            resized = img.resize(size, Image.Resampling.LANCZOS)
            icon_images.append(resized)

        # Save as ICO
        icon_images[0].save(
            str(ICON_DST),
            format="ICO",
            sizes=[(s[0], s[1]) for s in sizes],
            append_images=icon_images[1:],
        )
        print(f"  [OK] Icon generated: {ICON_DST}")
        return True

    except ImportError:
        print("  Warning: Pillow not installed. Building without custom icon.")
        return False
    except Exception as exc:
        print(f"  Warning: Icon generation failed: {exc}")
        return False


def clean():
    """Remove build artifacts."""
    for d in [BUILD_DIR, DIST_DIR]:
        if d.exists():
            shutil.rmtree(d)
            print(f"  Cleaned: {d}")


def build():
    """Run PyInstaller with the spec file."""
    if not SPEC_FILE.exists():
        print(f"  Error: Spec file not found: {SPEC_FILE}")
        sys.exit(1)

    print(f"  Building with spec: {SPEC_FILE}")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC_FILE), "--noconfirm"],
        cwd=str(ROOT),
    )

    if result.returncode != 0:
        print("\n  [FAIL] Build failed!")
        sys.exit(1)

    # Report output
    exe_path = DIST_DIR / "TradingAgents.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n  [OK] Build successful!")
        print(f"    Executable: {exe_path}")
        print(f"    Size: {size_mb:.1f} MB")
        return exe_path
    else:
        print("\n  [FAIL] Executable not found after build!")
        sys.exit(1)


def create_zip(exe_path: Path):
    """Create a .zip distribution."""
    zip_name = f"TradingAgents-Desktop-{sys.platform}"
    zip_path = DIST_DIR / zip_name
    shutil.make_archive(str(zip_path), "zip", str(DIST_DIR), exe_path.name)
    final = zip_path.with_suffix(".zip")
    size_mb = final.stat().st_size / (1024 * 1024)
    print(f"    Distribution: {final} ({size_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Build TradingAgents Desktop .exe")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts first")
    parser.add_argument("--zip", action="store_true", help="Create .zip distribution")
    args = parser.parse_args()

    print("\n****************************************")
    print("*  TradingAgents Desktop - Build       *")
    print("****************************************\n")

    if args.clean:
        print("[1/4] Cleaning...")
        clean()
    else:
        print("[1/4] Skipping clean (use --clean to force)")

    print("[2/4] Generating icon...")
    generate_icon()

    print("[3/4] Building executable...")
    exe_path = build()

    if args.zip:
        print("[4/4] Creating distribution...")
        create_zip(exe_path)
    else:
        print("[4/4] Skipping zip (use --zip to create)")

    print("\n  Done! 🎉\n")


if __name__ == "__main__":
    main()
