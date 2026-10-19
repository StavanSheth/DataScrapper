r"""
Build & Package Dedicated Chrome Extension for 1_Linkedin_Platforms.
Operates EXCLUSIVELY inside C:\Projects\Data Scrapper\1_Linkedin_Platforms\apps\extension.
Never touches or modifies the parent codebase C:\Projects\Data Scrapper\.
"""
import os
import sys
import subprocess

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
EXT_DIR = os.path.join(BASE_DIR, "apps/extension")

print(f"📦 Validating dedicated extension in: {EXT_DIR}")

# 1. Validate required files exist
required_files = [
    "manifest.json",
    "background.js",
    "content_script.js",
    "injected_bridge.js",
    "popup.html",
    "popup.js",
    "icon.png",
    "icon16.png",
    "icon32.png",
    "icon48.png",
    "icon128.png",
    "icons/icon16.png",
    "icons/icon32.png",
    "icons/icon48.png",
    "icons/icon128.png"
]

missing = []
for rf in required_files:
    fpath = os.path.join(EXT_DIR, rf)
    if not os.path.exists(fpath):
        missing.append(rf)

if missing:
    print(f"❌ Missing files in extension: {missing}")
    sys.exit(1)
else:
    print("✅ All required extension files and high-tech icons verified.")

# 2. Package into ZIP
pkg_script = os.path.join(BASE_DIR, "scripts/package_extension.py")
if os.path.exists(pkg_script):
    subprocess.run([sys.executable, pkg_script], check=True)

print("🎉 Dedicated 1_Linkedin_Platforms Chrome Extension build complete!")
