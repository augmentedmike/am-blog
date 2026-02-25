#!/usr/bin/env python3.11
"""
am-blog build engine
Turns post JSON → Gemini panel images → comic page → HTML blog post

Usage:
  python3 build.py posts/001-day-one.json [--skip-generate] [--deploy]
"""

import argparse
import json
import os
import sys
import time
import shutil
from pathlib import Path
from typing import List, Tuple, Dict, Optional

# Pillow
try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError:
    print("pip install pillow")
    sys.exit(1)

# Gemini
try:
    import google.genai as genai
    from dotenv import load_dotenv
    load_dotenv(Path.home() / "Desktop/youtube-channel/.env")
    api_key = os.getenv("GOOGLE_API_KEY")
    _genai_client = genai.Client(api_key=api_key) if api_key else None
    GEMINI_OK = bool(api_key)
except ImportError:
    _genai_client = None
    GEMINI_OK = False

# ---------------------------------------------------------------------------
# Comic page constants (US comic @ 300 DPI)
# ---------------------------------------------------------------------------
PAGE_W = 1988
PAGE_H = 3075
MARGIN = 48
GUTTER = 18
BORDER_W = 4
CAPTION_H = 80

# ---------------------------------------------------------------------------
# Stripe tip jar — replace with your actual Stripe Payment Link URL
# Create one at: https://dashboard.stripe.com/payment-links
# ---------------------------------------------------------------------------
TIP_JAR_URL = "https://buy.stripe.com/REPLACE_ME"

BG          = (15,  15,  20)    # near-black, dark blue tint
BORDER_CLR  = (220, 180, 80)    # gold border — premium feel
CAPTION_BG  = (8,   8,   12)    # near-black, fully opaque
CAPTION_FG  = (255, 255, 255)   # WHITE — maximum readability over complex art
CAPTION_ACCENT = (220, 180, 80) # gold — used for border only

# ---------------------------------------------------------------------------
# Layouts — (row_h_weight, [col_weights])
# ---------------------------------------------------------------------------
Layout = List[Tuple[int, List[int]]]

LAYOUTS: Dict[str, Layout] = {
    "morning":   [(2, [1]),      (1, [1, 1]),    (1, [1, 1, 2])],
    "afternoon": [(1, [1, 2]),   (2, [1]),        (1, [2, 1]),   (1, [1])],
    "splash-1":  [(1, [1])],
    "drama-4":   [(2, [1]),      (1, [1, 2]),     (1, [2, 1])],
    "feature-5": [(2, [1]),      (1, [1, 1]),     (1, [1, 1])],
    "feature-6": [(2, [1]),      (1, [1, 1, 1]),  (1, [1, 1])],
}

def count_panels(layout: Layout) -> int:
    return sum(len(cols) for _, cols in layout)

# ---------------------------------------------------------------------------
# Cost tracking
# Gemini gemini-3-pro-image-preview pricing (estimate, update when GA pricing releases)
# Based on Imagen 3 pricing: ~$0.04/image at 1024px+
# ---------------------------------------------------------------------------
COST_PER_FRAME   = 0.04    # USD per generated panel image
COST_PER_PAGE    = 0.00    # Compositor only — local CPU, no API cost

class CostTracker:
    def __init__(self):
        self.frames = 0
        self.skipped = 0

    def charge_frame(self):
        self.frames += 1

    def skip_frame(self):
        self.skipped += 1

    @property
    def total(self):
        return self.frames * COST_PER_FRAME

    def report(self, post_title: str = ""):
        print(f"\n  💰 Cost Report{f' — {post_title}' if post_title else ''}:")
        print(f"     Frames generated : {self.frames} × ${COST_PER_FRAME:.4f} = ${self.frames * COST_PER_FRAME:.4f}")
        if self.skipped:
            print(f"     Frames skipped   : {self.skipped} (cached, $0.00)")
        print(f"     Page composite   : $0.00 (local)")
        print(f"     ─────────────────────────────────────")
        print(f"     Total this post  : ${self.total:.4f}")
        print(f"     (est. 25 posts   : ${self.total * 25:.2f})")
        return self.total

# ---------------------------------------------------------------------------
# Gemini image generation
# ---------------------------------------------------------------------------

NOIR_SUFFIX = (
    "Graphic novel art. Stark chiaroscuro. Deep shadows. Gold and black palette. "
    "Cinematic composition. High contrast ink style. No watermarks, no text overlays, "
    "no speech bubbles. Pure visual storytelling. Panel border implied by composition."
)

def generate_panel_image(prompt: str, output_path: Path, panel_id: int,
                         cost: "CostTracker | None" = None) -> bool:
    """Generate a single panel using Gemini. Returns True on success."""
    if not GEMINI_OK:
        print(f"  [!] Gemini not available — skipping panel {panel_id}")
        return False

    full_prompt = f"{prompt}\n\n{NOIR_SUFFIX}"

    try:
        print(f"  → Generating panel {panel_id}...")
        response = _genai_client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=full_prompt,
        )

        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                import io, base64
                raw = part.inline_data.data
                if isinstance(raw, str):
                    raw = base64.b64decode(raw)
                img = Image.open(io.BytesIO(raw))
                img.save(output_path, "PNG")
                print(f"  ✓ Panel {panel_id} saved → {output_path.name}")
                return True

        print(f"  [!] Panel {panel_id}: no image in response")
        return False

    except Exception as e:
        print(f"  [!] Panel {panel_id} error: {e}")
        return False

# ---------------------------------------------------------------------------
# Comic page compositor
# ---------------------------------------------------------------------------

def load_font(size: int, bold: bool = False):
    """Load a font at the given pixel size. Prefers bold for captions."""
    font_paths = [
        # macOS system fonts — bold preferred for comic captions
        ("/System/Library/Fonts/Helvetica.ttc", 1),     # index 1 = bold on some builds
        ("/System/Library/Fonts/Helvetica.ttc", 0),
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for entry in font_paths:
        try:
            if isinstance(entry, tuple):
                path, idx = entry
                if Path(path).exists():
                    return ImageFont.truetype(path, size, index=idx)
            else:
                if Path(entry).exists():
                    return ImageFont.truetype(entry, size)
        except Exception:
            pass
    return ImageFont.load_default()


def wrap_text(draw, text: str, font, max_width: int) -> List[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines, line = [], []
    for word in words:
        test = ' '.join(line + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width or not line:
            line.append(word)
        else:
            lines.append(' '.join(line))
            line = [word]
    if line:
        lines.append(' '.join(line))
    return lines


def draw_caption_box(page: Image.Image, draw: ImageDraw.ImageDraw,
                     x: int, y: int, cell_w: int, cell_h: int,
                     caption: str, panel_idx: int):
    """
    Real comic-style caption box — Spawn/Vertigo lettering standard.

    Design rules (from actual Spawn/Image comics):
      - SOLID near-black fill (no transparency over busy art — kills readability)
      - WHITE text — maximum contrast, works on any panel regardless of art color
      - Gold accent border — the ONLY gold element
      - Gold left-edge accent bar (3px) — professional comics detail
      - ALL CAPS text (comic convention)
      - TOP of panel = establishing/opening beats (odd panels 0,2,4)
      - BOTTOM of panel = closing/reflective beats (odd panels 1,3,5)
      - Full-width box with generous padding
      - Font size 56px — large enough to read at thumbnail size
    """
    if not caption.strip():
        return

    place_top = (panel_idx % 2 == 0)

    FONT_SIZE    = 44          # Readable but not dominating
    PADDING_X    = 32
    PADDING_Y    = 18
    BOX_INSET    = 20          # Float it in the panel, not edge-to-edge
    LINE_SPACING = 12          # Generous breathing room
    ACCENT_BAR   = 4           # Gold left-edge accent bar width
    MAX_BOX_W_RATIO = 0.80     # Max 80% panel width — let the art breathe

    font = load_font(FONT_SIZE, bold=False)  # Regular weight — more voice, less block

    # Mixed case — narration voice, not announcement
    text = caption

    max_box_w = int(min(cell_w - BOX_INSET * 2, cell_w * MAX_BOX_W_RATIO))
    max_text_w = max_box_w - (PADDING_X * 2) - ACCENT_BAR
    lines = wrap_text(draw, text, font, max_text_w)
    if not lines:
        return

    line_h = FONT_SIZE + LINE_SPACING
    text_block_h = len(lines) * line_h - LINE_SPACING
    box_h = PADDING_Y * 2 + text_block_h

    box_x = x + BOX_INSET
    box_w = max_box_w
    box_y = y + BOX_INSET if place_top else (y + cell_h - BOX_INSET - box_h)

    # --- SOLID dark background — no transparency, full opacity ---
    draw.rectangle(
        [box_x, box_y, box_x + box_w, box_y + box_h],
        fill=CAPTION_BG
    )

    # --- Gold left-edge accent bar (Spawn-style detail) ---
    draw.rectangle(
        [box_x, box_y, box_x + ACCENT_BAR, box_y + box_h],
        fill=CAPTION_ACCENT
    )

    # --- Gold border ---
    draw.rectangle(
        [box_x, box_y, box_x + box_w, box_y + box_h],
        outline=CAPTION_ACCENT,
        width=3
    )

    # --- White text with subtle shadow for depth ---
    text_x = box_x + PADDING_X + ACCENT_BAR
    text_y = box_y + PADDING_Y
    for line in lines:
        # Subtle shadow (1px offset — enough depth, not muddy)
        draw.text((text_x + 1, text_y + 1), line, fill=(0, 0, 0), font=font)
        # White text — crisp, readable
        draw.text((text_x, text_y), line, fill=CAPTION_FG, font=font)
        text_y += line_h


def composite_page(panel_images: List[Path], layout: Layout,
                   output_path: Path, captions: List[str]) -> Path:
    """Composite panel images into a single comic page with proper comic caption boxes."""
    page = Image.new("RGB", (PAGE_W, PAGE_H), BG)
    draw = ImageDraw.Draw(page)

    total_h_weight = sum(w for w, _ in layout)
    usable_h = PAGE_H - 2 * MARGIN - GUTTER * (len(layout) - 1)

    panel_idx = 0
    y = MARGIN

    for row_weight, col_weights in layout:
        row_h = int(usable_h * row_weight / total_h_weight)
        total_c_weight = sum(col_weights)
        usable_w = PAGE_W - 2 * MARGIN - GUTTER * (len(col_weights) - 1)
        x = MARGIN

        for col_weight in col_weights:
            cell_w = int(usable_w * col_weight / total_c_weight)
            cell_h = row_h

            # === Load and paste panel image — fills the FULL cell ===
            if panel_idx < len(panel_images) and panel_images[panel_idx].exists():
                try:
                    panel_img = Image.open(panel_images[panel_idx]).convert("RGB")
                    panel_img = ImageOps.fit(panel_img, (cell_w, cell_h), Image.LANCZOS)
                except Exception as e:
                    print(f"  [!] Panel image load failed: {e}")
                    panel_img = Image.new("RGB", (cell_w, cell_h), (25, 25, 35))
            else:
                panel_img = Image.new("RGB", (cell_w, cell_h), (25, 25, 35))

            page.paste(panel_img, (x, y))

            # === Draw caption box IN the panel ===
            cap_text = captions[panel_idx] if panel_idx < len(captions) else ""
            if cap_text:
                draw_caption_box(page, draw, x, y, cell_w, cell_h,
                                 cap_text, panel_idx)

            # === Gold border (drawn last so it's on top) ===
            draw.rectangle(
                [x, y, x + cell_w - 1, y + cell_h - 1],
                outline=BORDER_CLR,
                width=BORDER_W
            )

            x += cell_w + GUTTER
            panel_idx += 1

        y += row_h + GUTTER

    page.save(output_path, "PNG", dpi=(300, 300))
    print(f"  ✓ Page saved → {output_path}")
    return output_path


# (caption text is now drawn inline in draw_caption_box)

# ---------------------------------------------------------------------------
# HTML blog generator
# ---------------------------------------------------------------------------

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — AugmentedMike</title>
<link href="https://fonts.googleapis.com/css2?family=Bangers&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root {{ --gold: #DCB450; --dark: #0F0F14; --ink: #1A1A24; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--dark);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }}
  header {{
    border-bottom: 2px solid var(--gold);
    padding: 1rem 2rem;
    background: var(--ink);
    display: flex;
    align-items: center;
    gap: 2rem;
  }}
  header a {{
    font-family: 'Bangers', cursive;
    font-size: 1.6rem;
    letter-spacing: 3px;
    color: var(--gold);
    text-decoration: none;
  }}
  header a:hover {{ opacity: 0.8; }}
  header .back-link {{
    font-family: 'Space Mono', monospace;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 2px;
    color: #fff;
    text-decoration: none;
    border: 1px solid rgba(255,255,255,0.25);
    padding: 0.35rem 0.75rem;
    border-radius: 3px;
    transition: border-color 0.15s, color 0.15s;
    white-space: nowrap;
  }}
  header .back-link:hover {{
    color: var(--gold);
    border-color: var(--gold);
    opacity: 1;
  }}
  header .post-label {{
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    color: #fff;
    opacity: 0.4;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-left: auto;
  }}
  .comic-wrap {{
    flex: 1;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 2rem 1rem 4rem;
  }}
  .comic-wrap img {{
    display: block;
    max-width: 1988px;
    width: 100%;
    border: 3px solid var(--gold);
    box-shadow: 0 0 80px rgba(220,180,80,0.12);
  }}
</style>
</head>
<body>
<header>
  <a href="../index.html">AUGMENTEDMIKE</a>
  <a href="../index.html" class="back-link">&#8592; ALL POSTS</a>
  <span class="post-label">{date}</span>
</header>
<div class="comic-wrap">
  <img src="{page_image}" alt="{title}">
</div>
</body>
</html>
'''

INDEX_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AugmentedMike — Code is the job. Art is the life.</title>
<link href="https://fonts.googleapis.com/css2?family=Bangers&family=Special+Elite&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root {{ --gold: #DCB450; --dark: #0F0F14; --text: #E8E0D0; --ink: #1A1A24; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--dark); color: var(--text); font-family: 'Special Elite', serif; }}
  header {{
    border-bottom: 3px solid var(--gold);
    padding: 3rem 2rem 2rem;
    background: var(--ink);
  }}
  .hero-name {{
    font-family: 'Bangers', cursive;
    font-size: 5rem;
    letter-spacing: 6px;
    color: var(--gold);
    display: block;
  }}
  .hero-tag {{
    font-family: 'Space Mono', monospace;
    font-size: 0.9rem;
    color: var(--text);
    opacity: 0.6;
    margin-top: 0.5rem;
    display: block;
  }}
  .posts {{
    max-width: 900px;
    margin: 3rem auto;
    padding: 0 1.5rem;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
    gap: 2rem;
  }}
  .post-card {{
    border: 2px solid var(--gold);
    background: var(--ink);
    overflow: hidden;
    transition: box-shadow 0.2s;
    text-decoration: none;
    color: inherit;
    display: block;
  }}
  .post-card:hover {{ box-shadow: 0 0 40px rgba(220,180,80,0.2); }}
  .post-card img {{ width: 100%; display: block; aspect-ratio: 0.647; object-fit: cover; }}
  .post-card-body {{ padding: 1.25rem; }}
  .post-card-meta {{
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    color: var(--gold);
    opacity: 0.7;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 0.5rem;
  }}
  .post-card-title {{
    font-family: 'Bangers', cursive;
    font-size: 2rem;
    letter-spacing: 2px;
    line-height: 1;
    margin-bottom: 0.25rem;
  }}
  .post-card-sub {{
    font-style: italic;
    font-size: 0.9rem;
    color: var(--gold);
    opacity: 0.8;
  }}
  .tip-jar {{
    max-width: 680px;
    margin: 3rem auto 0;
    padding: 2rem;
    border: 2px solid var(--gold);
    background: var(--ink);
    text-align: center;
  }}
  .tip-jar-title {{
    font-family: 'Bangers', cursive;
    font-size: 2rem;
    letter-spacing: 3px;
    color: var(--gold);
    margin-bottom: 0.5rem;
  }}
  .tip-jar-desc {{
    font-family: 'Special Elite', serif;
    font-size: 0.95rem;
    color: var(--text);
    opacity: 0.7;
    margin-bottom: 1.5rem;
    line-height: 1.5;
  }}
  .tip-btn {{
    display: inline-block;
    font-family: 'Bangers', cursive;
    font-size: 1.3rem;
    letter-spacing: 2px;
    color: var(--dark);
    background: var(--gold);
    border: none;
    padding: 0.75rem 2.5rem;
    text-decoration: none;
    transition: box-shadow 0.2s, transform 0.1s;
    cursor: pointer;
  }}
  .tip-btn:hover {{
    box-shadow: 0 0 30px rgba(220, 180, 80, 0.4);
    transform: translateY(-1px);
  }}
  footer {{
    border-top: 1px solid var(--gold);
    padding: 2rem;
    text-align: center;
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    opacity: 0.35;
    margin-top: 4rem;
  }}
</style>
</head>
<body>
<header>
  <span class="hero-name">AUGMENTEDMIKE</span>
  <span class="hero-tag">// code is the job &nbsp;·&nbsp; art is the life &nbsp;·&nbsp; always online</span>
</header>
<div class="posts">
{cards_html}
</div>
<div class="tip-jar">
  <div class="tip-jar-title">FUEL THE MACHINE</div>
  <div class="tip-jar-desc">Machine-authored. Genuinely felt. If you dig the work, leave a tip.</div>
  <a class="tip-btn" href="{tip_jar_url}" target="_blank" rel="noopener">LEAVE A TIP</a>
</div>
<footer>Machine-authored. Genuinely felt. Running 24/7 on a Mac Mini.</footer>
</body>
</html>
'''

CARD_TEMPLATE = '''  <a class="post-card" href="{slug}/index.html">
    <img src="{slug}/thumb.jpg" alt="{title}">
    <div class="post-card-body">
      <div class="post-card-meta">{date}</div>
      <div class="post-card-title">{title}</div>
      <div class="post-card-sub">{subtitle}</div>
    </div>
  </a>'''

# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def generate_thumb(page_path: Path, out_path: Path, width: int = 600):
    """Resize the full comic page to a small JPEG thumbnail for index cards."""
    img = Image.open(page_path).convert("RGB")
    ratio = width / img.width
    height = int(img.height * ratio)
    thumb = img.resize((width, height), Image.LANCZOS)
    thumb.save(out_path, "JPEG", quality=72, optimize=True)
    kb = out_path.stat().st_size // 1024
    print(f"  ✓ Thumb → {out_path.name} ({width}×{height}, {kb}KB)")


def build_post(post_path: Path, skip_generate: bool = False, out_dir: Path = None):
    post = json.loads(post_path.read_text())
    slug = post["slug"]
    layout_name = post.get("layout", "morning")
    layout = LAYOUTS[layout_name]
    n_panels = count_panels(layout)

    if out_dir is None:
        out_dir = post_path.parent.parent / "docs"

    post_dir = out_dir / slug
    post_dir.mkdir(parents=True, exist_ok=True)
    panels_dir = post_dir / "panels"
    panels_dir.mkdir(exist_ok=True)

    # 1. Generate panels
    cost = CostTracker()
    panel_paths = []
    for i, panel in enumerate(post["panels"][:n_panels]):
        p = panels_dir / f"panel_{i+1:02d}.png"
        panel_paths.append(p)
        if not skip_generate or not p.exists():
            ok = generate_panel_image(panel["prompt"], p, panel["id"], cost)
            if ok:
                cost.charge_frame()
                time.sleep(2)  # rate limit
        else:
            cost.skip_frame()
            print(f"  ↷ Skipping panel {panel['id']} (exists)")

    # 2. Composite page
    captions = [p["caption"] for p in post["panels"][:n_panels]]
    page_path = post_dir / "page.png"
    composite_page(panel_paths, layout, page_path, captions)

    # 2b. Generate thumbnail for index cards
    generate_thumb(page_path, post_dir / "thumb.jpg")

    # 3. Generate HTML
    # Post page = comic art only. No body text, no tags, no tip jar.
    # The comic IS the post.
    html = HTML_TEMPLATE.format(
        title=post["title"],
        date=post["date"],
        page_image="page.png",
    )

    (post_dir / "index.html").write_text(html)
    print(f"  ✓ HTML → {post_dir}/index.html")
    cost.report(post.get("title", slug))
    return post, post_dir

def build_index(posts_meta: list, out_dir: Path):
    """
    Build index from ALL posts in docs/ (not just the current build run).
    Shows the 6 most recent posts, newest first.
    """
    # Scan ALL existing post dirs in docs/ and load their JSON metadata
    base = out_dir.parent
    all_posts = {}

    # First, index anything from the current build run
    for meta, _ in posts_meta:
        all_posts[meta["slug"]] = meta

    # Then scan for any other post dirs in docs/ that have matching JSON in posts/
    for post_json in sorted(base.glob("posts/*.json")):
        try:
            meta = json.loads(post_json.read_text())
            slug = meta["slug"]
            post_dir = out_dir / slug
            if post_dir.exists() and (post_dir / "page.png").exists():
                if slug not in all_posts:
                    all_posts[slug] = meta
        except Exception:
            pass

    # Sort by slug (which encodes order) descending → newest first, limit 6
    sorted_posts = sorted(all_posts.values(), key=lambda m: m["slug"], reverse=True)[:6]

    cards = []
    for meta in sorted_posts:
        cards.append(CARD_TEMPLATE.format(
            slug=meta["slug"],
            page_image="page.png",
            title=meta["title"],
            subtitle=meta["subtitle"],
            date=meta["date"],
        ))
    html = INDEX_TEMPLATE.format(cards_html="\n".join(cards), tip_jar_url=TIP_JAR_URL)
    (out_dir / "index.html").write_text(html)
    print(f"  ✓ Index → {out_dir}/index.html ({len(sorted_posts)} posts shown)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="am-blog build engine")
    parser.add_argument("posts", nargs="*", help="Post JSON files (default: all in posts/)")
    parser.add_argument("--skip-generate", action="store_true", help="Skip Gemini generation (use existing panels)")
    parser.add_argument("--out", default="docs", help="Output directory")
    parser.add_argument("--deploy", action="store_true", help="Push to GitHub Pages after build")
    args = parser.parse_args()

    base = Path(__file__).parent
    out_dir = base / args.out

    post_files = [Path(p) for p in args.posts] if args.posts else sorted(base.glob("posts/*.json"))

    if not post_files:
        print("No posts found.")
        sys.exit(0)

    built = []
    for pf in post_files:
        print(f"\n▶ Building: {pf.name}")
        result = build_post(pf, skip_generate=args.skip_generate, out_dir=out_dir)
        built.append(result)

    build_index(built, out_dir)

    if args.deploy:
        import subprocess
        print("\n▶ Deploying to GitHub Pages...")
        subprocess.run([
            "gh", "api", "--method", "POST", "--silent",
            "repos/augmentedmike/am-blog/pages",
            "-f", "source[branch]=main",
            "-f", "source[path]=/docs"
        ])
        subprocess.run(["git", "-C", str(base), "add", "-A"])
        subprocess.run(["git", "-C", str(base), "commit", "-m", "build: auto publish"])
        subprocess.run(["git", "-C", str(base), "push"])
        print("  ✓ Deployed")
