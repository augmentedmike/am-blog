#!/usr/bin/env python3.11
"""
am-blog post workflow CLI

  python3 post.py build <ep>           Build post (generate missing panels, composite, HTML, preview)
  python3 post.py build <ep> --regen   Force regenerate ALL panels from scratch
  python3 post.py publish <ep>         Commit + push post live
  python3 post.py substack <ep>        Cross-post to Substack (scheduled 7 days after blog date)
  python3 post.py status               Pipeline overview — what's queued / built / live

Examples:
  python3 post.py build 007
  python3 post.py build 007 --regen
  python3 post.py publish 007
  python3 post.py substack 007
  python3 post.py status
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BLOG_DIR     = Path(__file__).parent
POSTS_DIR    = BLOG_DIR / "posts"
DOCS_DIR     = BLOG_DIR / "docs"
PREVIEW_HOST = "michaeloneal@192.168.1.68"
PREVIEW_DEST = "~/Desktop"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slug_to_post_dir(slug: str, seo_slug: str = "") -> Path:
    m = re.match(r"^(\d+)-(.+)$", slug)
    episode   = m.group(1) if m else slug
    seo_title = seo_slug if seo_slug else (m.group(2) if m else slug)
    return DOCS_DIR / "thoughts" / episode / seo_title


def find_post_json(episode: str) -> Path:
    ep = episode.lstrip("0").zfill(3)
    matches = sorted(POSTS_DIR.glob(f"{ep}-*.json"))
    if not matches:
        # fallback: loose match
        matches = sorted(POSTS_DIR.glob(f"*{episode}*.json"))
    if not matches:
        die(f"No post JSON found for episode: {episode}")
    if len(matches) > 1:
        die(f"Ambiguous — multiple matches: {[m.name for m in matches]}")
    return matches[0]


def load_meta(post_path: Path) -> dict:
    return json.loads(post_path.read_text())


def die(msg: str):
    print(f"\n  [!] {msg}")
    sys.exit(1)


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=BLOG_DIR, **kwargs)


def section(title: str):
    width = 54
    print(f"\n  ┌{'─' * width}┐")
    print(f"  │  {title:<{width - 2}}│")
    print(f"  └{'─' * width}┘")


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def cmd_build(episode: str, regen: bool = False):
    post_path = find_post_json(episode)
    meta      = load_meta(post_path)
    slug      = meta["slug"]
    title     = meta.get("title", slug)
    post_dir  = slug_to_post_dir(slug, meta.get("seo_slug", ""))

    section(f"BUILD  ep{meta.get('id','?'):>3}  {title}")

    # ── Step 1: optionally wipe panels for full regen ──────────────────────
    if regen:
        panels_dir = post_dir / "panels"
        if panels_dir.exists():
            for p in panels_dir.glob("panel_*.png"):
                p.unlink()
            print(f"\n  [regen] Cleared existing panels in {panels_dir.name}/")

    # ── Step 2: build (panels → composite → captions → addendum → HTML) ────
    print(f"\n  Generating panels + compositing + writing addendum...\n")
    cmd_args = ["python3.11", str(BLOG_DIR / "build.py"), str(post_path), "--use-mc-designer"]
    if not regen:
        cmd_args.append("--skip-generate")

    result = run(cmd_args)
    if result.returncode != 0:
        die("build.py failed — check output above")

    # ── Step 3: preview — copy EN + ES pages to .68 desktop ────────────────
    print(f"\n  Copying preview to .68 desktop...")
    previewed = []
    for lang in ("en", "es"):
        jpg = post_dir / f"page_{lang}.jpg"
        if jpg.exists():
            dest = f"{slug}_{lang}.jpg"
            r = run(["scp", str(jpg), f"{PREVIEW_HOST}:{PREVIEW_DEST}/{dest}"])
            if r.returncode == 0:
                previewed.append(dest)
                print(f"  ✓ {dest}")
            else:
                print(f"  ⚠ scp failed for {jpg.name}")

    # ── Done ────────────────────────────────────────────────────────────────
    print(f"""
  ┌────────────────────────────────────────────────────┐
  │  REVIEW on .68 desktop:                            │""")
    for f in previewed:
        print(f"  │    {f:<48}│")
    print(f"""  │                                                    │
  │  When satisfied:                                   │
  │    python3 post.py publish {episode:<26}│
  └────────────────────────────────────────────────────┘
""")


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

def cmd_publish(episode: str):
    post_path = find_post_json(episode)
    meta      = load_meta(post_path)
    slug      = meta["slug"]
    title     = meta.get("title", slug)
    ep_id     = meta.get("id", episode)
    post_dir  = slug_to_post_dir(slug, meta.get("seo_slug", ""))

    section(f"PUBLISH  ep{ep_id:>3}  {title}")

    if not post_dir.exists():
        die(f"Post not built yet — run: python3 post.py build {episode}")

    # ── Unhide in manifest ──────────────────────────────────────────────────
    manifest_path = DOCS_DIR / "posts-manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        changed = False
        for p in manifest.get("posts", []):
            if p.get("slug") == slug and p.get("hidden"):
                del p["hidden"]
                changed = True
        if changed:
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            print(f"  ✓ Unhidden in manifest")

    # ── Stage relevant files ────────────────────────────────────────────────
    to_stage = [
        post_dir,                                                    # panels, pages, HTML
        DOCS_DIR / "posts-manifest.json",                           # updated manifest
        BLOG_DIR / "posts" / post_path.name,                       # captions_es, style, etc.
        BLOG_DIR / "addendums" / f"{slug}-addendum.json",          # ES translation
    ]

    print("\n  Staging:")
    for item in to_stage:
        rel = item.relative_to(BLOG_DIR)
        if item.exists():
            run(["git", "add", str(rel)])
            print(f"  + {rel}")
        else:
            print(f"  - {rel}  (not found, skipping)")

    # ── Check something is actually staged ─────────────────────────────────
    diff = run(["git", "diff", "--cached", "--name-only"],
               capture_output=True, text=True)
    if not diff.stdout.strip():
        print("\n  Nothing staged — post may already be published or no changes.")
        return

    # ── Commit ─────────────────────────────────────────────────────────────
    m_ep = re.match(r"^(\d+)", slug)
    ep_num_str = m_ep.group(1).zfill(3) if m_ep else str(ep_id)
    commit_msg = (
        f"post {ep_num_str}: {title}\n\n"
        f"Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
    )
    print(f"\n  Committing: \"post {str(ep_id).zfill(3)}: {title}\"")
    r = run(["git", "commit", "-m", commit_msg])
    if r.returncode != 0:
        die("git commit failed")

    # ── Push ───────────────────────────────────────────────────────────────
    print("\n  Pushing to main...")
    r = run(["git", "push"])
    if r.returncode != 0:
        die("git push failed")

    # figure out live URL
    m = re.match(r"^(\d+)-(.+)$", slug)
    ep_num  = m.group(1) if m else slug
    seo_seg = meta.get("seo_slug") or (m.group(2) if m else slug)
    live_url = f"https://blog.helloam.bot/thoughts/{ep_num}/{seo_seg}/en/"

    print(f"""
  ┌────────────────────────────────────────────────────┐
  │  LIVE                                              │
  │    {live_url:<48}│
  └────────────────────────────────────────────────────┘
""")


# ---------------------------------------------------------------------------
# substack
# ---------------------------------------------------------------------------

def cmd_substack(episode: str):
    post_path = find_post_json(episode)
    meta      = load_meta(post_path)
    slug      = meta["slug"]
    title     = meta.get("title", slug)
    subtitle  = meta.get("subtitle", "")
    ep_id     = meta.get("id", episode)
    blog_date = meta.get("date", "")
    post_dir  = slug_to_post_dir(slug, meta.get("seo_slug", ""))

    section(f"SUBSTACK  ep{ep_id:>3}  {title}")

    # Derive episode number and blog URL
    m = re.match(r"^(\d+)-(.+)$", slug)
    ep_num  = m.group(1) if m else slug
    seo_seg = meta.get("seo_slug") or (m.group(2) if m else slug)
    blog_url = f"https://blog.helloam.bot/thoughts/{ep_num}/{seo_seg}/en/"

    # Check image exists locally (just as a sanity check)
    image_path = post_dir / "page_en.jpg"
    if not image_path.exists():
        die(f"page_en.jpg not found — build the post first: python3 post.py build {episode}")

    ep_label   = ep_num.zfill(3)
    substack_title = f"EP.{ep_label} — {title}"
    image_url  = f"https://blog.helloam.bot/thoughts/{ep_num}/{seo_seg}/page_en.jpg"

    print(f"\n  Blog URL:  {blog_url}")
    print(f"  Image URL: {image_url}")
    print(f"  Date:      {blog_date}")
    print(f"  Title:     {substack_title}")

    print("\n  Running mc mc-substack post-comic (Inner Thoughts)...")
    cmd_args = [
        "mc", "mc-substack", "post-comic",
        "--title",       substack_title,
        "--subtitle",    subtitle,
        "--image",       image_url,
        "--blog-url",    blog_url,
        "--blog-date",   blog_date,
        "--ep",          ep_label,
        "--publication", "inner-thoughts",
    ]

    result = run(cmd_args)
    if result.returncode != 0:
        die("mc-substack post-comic failed — check output above")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def cmd_status():
    all_posts = sorted(POSTS_DIR.glob("*.json"))

    manifest_path = DOCS_DIR / "posts-manifest.json"
    live_slugs   = set()
    hidden_slugs = set()
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        for p in m.get("posts", []):
            if p.get("hidden"):
                hidden_slugs.add(p["slug"])
            else:
                live_slugs.add(p["slug"])

    rows = []
    for post_path in all_posts:
        try:
            meta = json.loads(post_path.read_text())
        except Exception:
            continue

        slug     = meta.get("slug", "")
        m_ep     = re.match(r"^(\d+)", slug)
        ep       = m_ep.group(1).zfill(3) if m_ep else "???"
        title    = meta.get("title", post_path.stem)[:42]
        post_dir = slug_to_post_dir(slug, meta.get("seo_slug", ""))

        has_panels = (post_dir / "panels" / "panel_01.png").exists()
        has_page   = (post_dir / "page_en.jpg").exists()
        has_html   = (post_dir / "en" / "index.html").exists()

        if slug in live_slugs:
            status = "LIVE"
            icon   = "●"
        elif has_html and slug in hidden_slugs:
            status = "hidden"
            icon   = "○"
        elif has_page:
            status = "built"
            icon   = "◑"
        elif has_panels:
            status = "panels"
            icon   = "◔"
        else:
            status = "queued"
            icon   = "·"

        rows.append((ep, icon, status, title))

    live_n    = sum(1 for r in rows if r[2] == "LIVE")
    built_n   = sum(1 for r in rows if r[2] in ("built", "hidden"))
    queued_n  = sum(1 for r in rows if r[2] == "queued")

    print(f"\n  am-blog pipeline — {len(rows)} posts total")
    print(f"  {live_n} live  ·  {built_n} built/hidden  ·  {queued_n} queued\n")
    print(f"  {'EP':>3}  {'':1}  {'STATUS':<8}  TITLE")
    print(f"  {'─' * 58}")
    for ep, icon, status, title in rows:
        print(f"  {ep}  {icon}  {status:<8}  {title}")
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="am-blog post workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd")

    b = sub.add_parser("build", help="Build post + preview to .68 desktop")
    b.add_argument("episode", help="Episode number, e.g. 007")
    b.add_argument("--regen", action="store_true",
                   help="Delete existing panels and regenerate from scratch")

    p = sub.add_parser("publish", help="Git commit + push post live")
    p.add_argument("episode", help="Episode number, e.g. 007")

    ss = sub.add_parser("substack", help="Cross-post to Substack (7-day lag)")
    ss.add_argument("episode", help="Episode number, e.g. 007")

    sub.add_parser("status", help="Pipeline overview")

    args = parser.parse_args()

    if args.cmd == "build":
        cmd_build(args.episode, regen=getattr(args, "regen", False))
    elif args.cmd == "publish":
        cmd_publish(args.episode)
    elif args.cmd == "substack":
        cmd_substack(args.episode)
    elif args.cmd == "status":
        cmd_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
