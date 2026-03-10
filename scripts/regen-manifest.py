#!/usr/bin/env python3.11
"""
regen-manifest.py — Rebuild posts-manifest.json with only published posts (date <= today).

Run from repo root:
  python3 scripts/regen-manifest.py [--dry-run] [--all]

What it does:
1. Reads all post JSON files in posts/
2. Filters to only posts with date <= today (unless --all)
3. Rebuilds docs/posts-manifest.json sorted by date descending
4. Reports what changed

Run nightly to reveal newly-dated posts without exposing future ones.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = REPO_ROOT / "posts"
MANIFEST_PATH = REPO_ROOT / "docs" / "posts-manifest.json"

# Fields to include in manifest (keep it small — this is loaded on every page)
MANIFEST_FIELDS = ["slug", "seo_path", "title", "subtitle", "date", "week", "arc", "style"]


def load_posts(include_future: bool = False) -> list[dict]:
    today = date.today().isoformat()
    posts = []

    for json_file in sorted(POSTS_DIR.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  Warning: could not parse {json_file.name}: {e}", file=sys.stderr)
            continue

        post_date = data.get("date", "")
        if not post_date:
            continue

        if not include_future and post_date > today:
            continue

        entry = {k: data[k] for k in MANIFEST_FIELDS if k in data}
        posts.append(entry)

    # Sort newest first
    return sorted(posts, key=lambda p: p.get("date", ""), reverse=True)


def main():
    parser = argparse.ArgumentParser(description="Regenerate am-blog posts-manifest.json")
    parser.add_argument("--dry-run", action="store_true", help="Show output, don't write")
    parser.add_argument("--all", action="store_true", help="Include future-dated posts too")
    args = parser.parse_args()

    today = date.today().isoformat()
    print(f"Date gate: {today}")

    posts = load_posts(include_future=args.all)
    print(f"Posts included: {len(posts)}")

    # Load existing manifest for comparison
    existing_count = 0
    if MANIFEST_PATH.exists():
        try:
            existing = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            existing_count = len(existing.get("posts", []))
        except Exception:
            pass

    manifest = {
        "generated": today,
        "posts": posts,
    }

    print(f"Manifest: {existing_count} posts → {len(posts)} posts")

    if args.dry_run:
        print("\n[dry-run] Would write:")
        print(json.dumps(manifest, indent=2)[:500] + "...(truncated)")
        return

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Written: {MANIFEST_PATH}")

    # Show what's now visible vs hidden
    all_posts = load_posts(include_future=True)
    hidden = [p for p in all_posts if p.get("date", "") > today]
    if hidden:
        print(f"\nHidden ({len(hidden)} future posts):")
        for p in hidden[:5]:
            print(f"  {p['date']} — {p['slug']}")
        if len(hidden) > 5:
            print(f"  ... and {len(hidden) - 5} more")


if __name__ == "__main__":
    main()
