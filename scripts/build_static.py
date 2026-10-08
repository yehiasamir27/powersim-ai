"""
Assemble the static demo bundle in ``public/`` for zero-backend hosting (Vercel).

The app's pages reference assets by absolute path (``/static/assets/...``) so that
one set of HTML files works both under FastAPI and on a static host. This script
mirrors that layout:

    static/index.html      -> public/index.html      (served at /)
    static/dashboard.html  -> public/dashboard.html  (served at /dashboard)
    static/pitch.html      -> public/pitch.html      (served at /pitch)
    static/assets/*        -> public/static/assets/* (absolute paths resolve)

With ``cleanUrls`` enabled in vercel.json, ``dashboard.html`` is served at
``/dashboard`` automatically, so no rewrites are needed.

The full Python/FastAPI/Docker stack remains the production deployment; this
bundle is only the public demo, which runs the simulation client-side.

Usage:  python scripts/build_static.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PUBLIC = ROOT / "public"

PAGES = ("index.html", "dashboard.html", "pitch.html")
#: Stock media that must never ship (see .gitignore).
EXCLUDE_PREFIXES = ("shutterstock_",)


def build() -> int:
    if not STATIC.is_dir():
        print(f"error: {STATIC} not found", file=sys.stderr)
        return 1

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    (PUBLIC / "static" / "assets").mkdir(parents=True, exist_ok=True)

    copied = 0
    for page in PAGES:
        src = STATIC / page
        if not src.exists():
            print(f"error: missing page {src}", file=sys.stderr)
            return 1
        shutil.copy2(src, PUBLIC / page)
        copied += 1

    for asset in sorted((STATIC / "assets").iterdir()):
        if not asset.is_file() or asset.name.startswith(EXCLUDE_PREFIXES):
            continue
        shutil.copy2(asset, PUBLIC / "static" / "assets" / asset.name)
        copied += 1

    print(f"built {PUBLIC.relative_to(ROOT)}/ with {copied} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
