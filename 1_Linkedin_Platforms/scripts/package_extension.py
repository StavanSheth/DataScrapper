"""
Packages the DataScrapper Chrome Extension into a distributable .zip archive.
Generates:
1. apps/extension/dist/datascrapper-extension-v3.0.0.zip
2. apps/web/static/downloads/datascrapper-extension.zip (accessible via web dashboard)
"""
import os
import sys
import zipfile

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
EXT_DIR = os.path.join(BASE_DIR, "apps/extension")
DIST_DIR = os.path.join(EXT_DIR, "dist")
STATIC_DOWNLOADS_DIR = os.path.join(BASE_DIR, "apps/web/static/downloads")

os.makedirs(DIST_DIR, exist_ok=True)
os.makedirs(STATIC_DOWNLOADS_DIR, exist_ok=True)

zip_filename = "datascrapper-extension-v3.0.0.zip"
dist_zip_path = os.path.join(DIST_DIR, zip_filename)
static_zip_path = os.path.join(STATIC_DOWNLOADS_DIR, "datascrapper-extension.zip")

# Files and folders to include
INCLUDE_FILES = [
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
]

INCLUDE_DIRS = [
    "icons"
]

def create_zip(target_path):
    with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add root files
        for fname in INCLUDE_FILES:
            fpath = os.path.join(EXT_DIR, fname)
            if os.path.exists(fpath):
                zf.write(fpath, arcname=fname)
            else:
                print(f"Warning: {fname} not found in {EXT_DIR}")

        # Add icons folder
        for dname in INCLUDE_DIRS:
            dpath = os.path.join(EXT_DIR, dname)
            if os.path.exists(dpath):
                for root, _, files in os.walk(dpath):
                    for file in files:
                        full_p = os.path.join(root, file)
                        rel_p = os.path.relpath(full_p, EXT_DIR)
                        zf.write(full_p, arcname=rel_p)

create_zip(dist_zip_path)
create_zip(static_zip_path)

print(f"✅ Extension successfully packaged and exported to:")
print(f"   1. {dist_zip_path} ({os.path.getsize(dist_zip_path):,} bytes)")
print(f"   2. {static_zip_path} ({os.path.getsize(static_zip_path):,} bytes)")
