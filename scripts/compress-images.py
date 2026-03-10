#!/usr/bin/env python3.11
"""
compress-images.py — Convert PNG panels to WebP and update HTML references.

Run from repo root:
  python3 scripts/compress-images.py [--dry-run] [--quality 85]

What it does:
1. Finds all docs/thoughts/*/panels/*.png
2. Converts each to .webp at the given quality (default 85, target <150KB)
3. Deletes the original .png (saves space)
4. Updates docs/thoughts/*/index.html to reference .webp instead of .png
5. Reports before/after sizes

Safe to re-run — skips already-converted panels.
"""

import argparse
import os
import re
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("pip install pillow")
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs" / "thoughts"
DEFAULT_QUALITY = 85
TARGET_KB = 150


def convert_panel(png_path: Path, quality: int, dry_run: bool) -> tuple[int, int]:
    """Convert a PNG panel to WebP. Returns (original_bytes, new_bytes)."""
    webp_path = png_path.with_suffix(".webp")
    orig_size = png_path.stat().st_size

    if webp_path.exists():
        # Already converted — skip
        return orig_size, webp_path.stat().st_size

    if dry_run:
        print(f"  [dry-run] would convert: {png_path.name}")
        return orig_size, 0

    with Image.open(png_path) as img:
        img.save(webp_path, "WEBP", quality=quality, method=6)

    new_size = webp_path.stat().st_size
    png_path.unlink()
    return orig_size, new_size


def patch_html(html_path: Path, dry_run: bool) -> int:
    """Replace .png references with .webp in an HTML file. Returns number of replacements."""
    content = html_path.read_text(encoding="utf-8")
    # Match panel_XX.png references specifically (not other PNGs like page.png, thumb.jpg)
    patched, count = re.subn(r'(panel_\d+)\.png', r'\1.webp', content)
    if count == 0:
        return 0
    if not dry_run:
        html_path.write_text(patched, encoding="utf-8")
    return count


def main():
    parser = argparse.ArgumentParser(description="Compress am-blog panel PNGs to WebP")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no changes")
    parser.add_argument("--quality", type=int, default=DEFAULT_QUALITY,
                        help=f"WebP quality (default {DEFAULT_QUALITY})")
    args = parser.parse_args()

    if not DOCS.exists():
        print(f"Error: docs/thoughts not found at {DOCS}")
        sys.exit(1)

    total_saved = 0
    total_orig = 0
    panels_converted = 0
    panels_skipped = 0

    post_dirs = sorted(DOCS.iterdir())
    for post_dir in post_dirs:
        if not post_dir.is_dir():
            continue

        # Each post_dir may have a nested slug dir (e.g., the-backup)
        # Or panels may be directly inside post_dir/panels/
        panels_candidates = list(post_dir.rglob("panels"))
        for panels_dir in panels_candidates:
            if not panels_dir.is_dir():
                continue

            pngs = sorted(panels_dir.glob("panel_*.png"))
            if not pngs:
                continue

            print(f"\n{post_dir.name}/")
            for png in pngs:
                webp = png.with_suffix(".webp")
                if webp.exists() and not png.exists():
                    # Already done
                    panels_skipped += 1
                    continue

                orig, new = convert_panel(png, args.quality, args.dry_run)
                saved = orig - new
                total_orig += orig
                total_saved += saved
                panels_converted += 1

                kb_orig = orig // 1024
                kb_new = new // 1024
                flag = " ⚠️  still large" if kb_new > TARGET_KB else ""
                print(f"  {png.name} → .webp  {kb_orig}K → {kb_new}K  (-{saved//1024}K){flag}")

        # Patch HTML files in this post dir
        for html_file in post_dir.rglob("index.html"):
            count = patch_html(html_file, args.dry_run)
            if count:
                action = "[dry-run] would patch" if args.dry_run else "patched"
                print(f"  {action} {html_file.relative_to(DOCS)}: {count} .png→.webp refs")

    print(f"\n{'='*50}")
    print(f"Panels converted : {panels_converted}")
    print(f"Panels skipped   : {panels_skipped} (already WebP)")
    print(f"Total saved      : {total_saved // (1024*1024):.1f} MB  ({total_saved // 1024} KB)")
    if args.dry_run:
        print("(dry-run — no files changed)")


if __name__ == "__main__":
    main()
