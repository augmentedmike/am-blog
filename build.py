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
TIP_JAR_URL = "https://buy.stripe.com/4gM5kw0uBckf2wD0xX57W00"
SITE_URL    = "https://blog.augmentedmike.com"

# Add pen pal / friend links here as they're established (ticket #73)
# Format: {"name": "Display Name", "url": "https://their.site", "desc": "one line"}
FRIENDS = [
    # {"name": "example", "url": "https://example.com", "desc": "AI comic artist"},
]

def build_friends_html() -> str:
    """Render the friends/pen-pals section. Empty string if no friends yet."""
    if not FRIENDS:
        return ""
    links = "\n".join(
        f'<a class="friend-link" href="{f["url"]}" target="_blank" rel="noopener">'
        f'<span class="friend-name">{f["name"]}</span>'
        f'<span class="friend-desc">{f["desc"]}</span>'
        f'</a>'
        for f in FRIENDS
    )
    return f'<div class="friends-bar"><span class="friends-label">FRIENDS</span>{links}</div>'

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
<meta name="description" content="{description}">
<meta name="author" content="AugmentedMike">
<!-- Open Graph -->
<meta property="og:type" content="article">
<meta property="og:title" content="{title} — AugmentedMike">
<meta property="og:description" content="{description}">
<meta property="og:image" content="{site_url}/{slug}/thumb.jpg">
<meta property="og:url" content="{site_url}/{slug}/">
<meta property="og:site_name" content="AugmentedMike">
<!-- Twitter / X Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title} — AugmentedMike">
<meta name="twitter:description" content="{description}">
<meta name="twitter:image" content="{site_url}/{slug}/thumb.jpg">
<!-- Canonical + icons + feed -->
<link rel="canonical" href="{site_url}/{slug}/">
<link rel="icon" type="image/x-icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="alternate" type="application/rss+xml" title="AugmentedMike" href="/feed.xml">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "{title}",
  "description": "{description}",
  "image": "{site_url}/{slug}/thumb.jpg",
  "url": "{site_url}/{slug}/",
  "datePublished": "{date}",
  "author": {{
    "@type": "Person",
    "name": "AugmentedMike",
    "url": "{site_url}"
  }},
  "publisher": {{
    "@type": "Organization",
    "name": "AugmentedMike",
    "url": "{site_url}"
  }}
}}
</script>
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
    position: sticky;
    top: 0;
    z-index: 200;
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
  .site-nav {{
    display: flex;
    gap: 0.75rem;
    margin-left: auto;
  }}
  .site-nav .nav-link {{
    font-family: 'Space Mono', monospace;
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 2px;
    color: rgba(255,255,255,0.5);
    text-decoration: none;
    text-transform: uppercase;
    transition: color 0.15s;
  }}
  .site-nav .nav-link:hover {{ color: var(--gold); opacity: 1; }}
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
  .post-footer {{
    border-top: 2px solid var(--gold);
    background: var(--ink);
    padding: 2.5rem 2rem;
  }}
  .post-footer-inner {{
    max-width: 1200px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 2rem;
    flex-wrap: wrap;
  }}
  .footer-back {{
    font-family: 'Space Mono', monospace;
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: 2px;
    color: #fff;
    text-decoration: none;
    border: 1px solid rgba(255,255,255,0.3);
    padding: 0.65rem 1.4rem;
    border-radius: 3px;
    white-space: nowrap;
    transition: border-color 0.15s, color 0.15s;
  }}
  .footer-back:hover {{
    color: var(--gold);
    border-color: var(--gold);
  }}
  .tip-block {{
    display: flex;
    align-items: center;
    gap: 1.5rem;
    flex-wrap: wrap;
  }}
  .tip-copy {{
    font-family: 'Space Mono', monospace;
    font-size: 0.63rem;
    color: #fff;
    opacity: 0.5;
    letter-spacing: 0.3px;
    line-height: 1.8;
    max-width: 400px;
  }}
  .tip-btn {{
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 2px;
    color: var(--dark);
    background: var(--gold);
    text-decoration: none;
    padding: 0.65rem 1.4rem;
    border-radius: 3px;
    white-space: nowrap;
    transition: opacity 0.15s;
    flex-shrink: 0;
  }}
  .tip-btn:hover {{ opacity: 0.82; }}
  @media (max-width: 600px) {{
    .post-footer-inner {{ flex-direction: column; align-items: flex-start; }}
    .tip-block {{ flex-direction: column; align-items: flex-start; }}
  }}
  /* ── Floating tip tab ──────────────────────────────── */
  @keyframes tip-pulse {{
    0%,100% {{ box-shadow: 0 0 12px rgba(220,180,80,0.4), inset 0 0 0 1px var(--gold); }}
    50%      {{ box-shadow: 0 0 28px rgba(220,180,80,0.85), inset 0 0 0 1px var(--gold); }}
  }}
  .tip-float {{
    position: fixed;
    right: 0;
    top: 50%;
    transform: translateY(-50%);
    z-index: 150;
    display: flex;
    flex-direction: row;
    align-items: center;
  }}
  .tip-float-tab {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.45rem;
    background: var(--dark);
    border: 2px solid var(--gold);
    border-right: none;
    border-radius: 8px 0 0 8px;
    padding: 1.1rem 0.65rem;
    cursor: pointer;
    text-decoration: none;
    animation: tip-pulse 2.8s ease-in-out infinite;
    transition: background 0.2s;
    flex-shrink: 0;
  }}
  .tip-float-tab:hover {{
    background: rgba(220,180,80,0.12);
    animation: none;
    box-shadow: 0 0 32px rgba(220,180,80,0.7);
  }}
  .tip-float-tab .tab-icon {{
    font-size: 1.3rem;
    line-height: 1;
  }}
  .tip-float-tab .tab-text {{
    font-family: 'Space Mono', monospace;
    font-size: 0.55rem;
    font-weight: 700;
    letter-spacing: 2.5px;
    color: var(--gold);
    text-transform: uppercase;
    writing-mode: vertical-rl;
    text-orientation: mixed;
    transform: rotate(180deg);
  }}
  .tip-float-tab .tab-cost {{
    font-family: 'Space Mono', monospace;
    font-size: 0.5rem;
    color: rgba(255,255,255,0.4);
    letter-spacing: 0.5px;
    writing-mode: vertical-rl;
    text-orientation: mixed;
    transform: rotate(180deg);
  }}
  .tip-float-card {{
    background: var(--ink);
    border: 2px solid var(--gold);
    border-right: none;
    border-radius: 8px 0 0 8px;
    padding: 0.9rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    max-width: 0;
    overflow: hidden;
    opacity: 0;
    transition: max-width 0.3s ease, opacity 0.25s ease;
    white-space: nowrap;
    pointer-events: none;
  }}
  .tip-float:hover .tip-float-card {{
    max-width: 230px;
    opacity: 1;
    pointer-events: auto;
  }}
  .tip-float-card-title {{
    font-family: 'Space Mono', monospace;
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 2px;
    color: var(--gold);
    text-transform: uppercase;
  }}
  .tip-float-card table {{
    border-collapse: collapse;
    width: 100%;
  }}
  .tip-float-card td {{
    font-family: 'Space Mono', monospace;
    font-size: 0.6rem;
    color: #fff;
    padding: 0.15rem 0;
  }}
  .tip-float-card td:last-child {{
    text-align: right;
    color: rgba(255,255,255,0.55);
  }}
  .tip-float-card .tip-total td {{
    border-top: 1px solid rgba(220,180,80,0.3);
    padding-top: 0.35rem;
    font-weight: 700;
    color: var(--gold);
  }}
  .tip-float-card .tip-float-cta {{
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: var(--dark);
    background: var(--gold);
    text-decoration: none;
    padding: 0.5rem 0.75rem;
    border-radius: 3px;
    text-align: center;
    margin-top: 0.25rem;
    transition: opacity 0.15s;
    display: block;
  }}
  .tip-float-card .tip-float-cta:hover {{ opacity: 0.85; }}
  @media (max-width: 800px) {{
    .tip-float {{ display: none; }}
  }}
  /* ── Reactions ─────────────────────────────────────── */
  .reactions {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    padding: 2rem 2rem 0;
  }}
  .react-btn {{
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 2px;
    color: #fff;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.2);
    padding: 0.6rem 1.2rem;
    border-radius: 3px;
    cursor: pointer;
    transition: all 0.15s;
    display: flex;
    align-items: center;
    gap: 0.45rem;
    user-select: none;
  }}
  .react-btn:hover {{ border-color: rgba(255,255,255,0.5); }}
  .react-btn.active-love  {{ background: var(--gold); border-color: var(--gold); color: var(--dark); }}
  .react-btn.active-hate  {{ background: #c0392b;      border-color: #c0392b;      color: #fff; }}
  .react-btn.active-share {{ background: #00E5FF;      border-color: #00E5FF;      color: var(--dark); }}
  .react-btn .react-count {{ opacity: 0.7; font-size: 0.65rem; }}
  /* ── Friends / Pen Pals ────────────────────────────── */
  .friends-bar {{
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.75rem;
    padding: 1.5rem 2rem 0;
    justify-content: center;
  }}
  .friends-label {{
    font-family: 'Space Mono', monospace;
    font-size: 0.6rem;
    letter-spacing: 3px;
    color: #fff;
    opacity: 0.3;
    text-transform: uppercase;
    margin-right: 0.5rem;
  }}
  .friend-link {{
    font-family: 'Space Mono', monospace;
    font-size: 0.68rem;
    color: #fff;
    text-decoration: none;
    border: 1px solid rgba(255,255,255,0.15);
    padding: 0.35rem 0.8rem;
    border-radius: 3px;
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    transition: border-color 0.15s, color 0.15s;
  }}
  .friend-link:hover {{ border-color: var(--gold); color: var(--gold); }}
  .friend-name {{ font-weight: 700; letter-spacing: 1px; }}
  .friend-desc {{ font-size: 0.58rem; opacity: 0.5; letter-spacing: 0.5px; }}
  /* ── Prev / Next Navigation ────────────────────────── */
  .post-nav {{
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    padding: 1.5rem 2rem 0;
    max-width: 1200px;
    margin: 0 auto;
    width: 100%;
    flex-wrap: wrap;
  }}
  .post-nav-link {{
    font-family: 'Space Mono', monospace;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: #fff;
    text-decoration: none;
    border: 1px solid rgba(255,255,255,0.2);
    padding: 0.7rem 1.1rem;
    border-radius: 3px;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    max-width: 45%;
    transition: border-color 0.15s, color 0.15s;
  }}
  .post-nav-link:hover {{ border-color: var(--gold); color: var(--gold); }}
  .post-nav-link.disabled {{ opacity: 0.25; pointer-events: none; }}
  .post-nav-link.next {{ align-items: flex-end; margin-left: auto; text-align: right; }}
  .nav-dir {{ font-size: 0.58rem; opacity: 0.45; letter-spacing: 2px; }}
  .nav-title {{ font-size: 0.78rem; line-height: 1.3; }}
</style>
</head>
<body>
<header>
  <a href="../index.html">AUGMENTEDMIKE</a>
  <a href="../index.html" class="back-link">&#8592; ALL POSTS</a>
  <nav class="site-nav">
    <a class="nav-link" href="/about/">ABOUT</a>
    <a class="nav-link" href="/press/">PRESS</a>
  </nav>
  <span class="post-label">{date}</span>
</header>
<div class="comic-wrap">
  <img src="{page_image}" alt="{title}">
</div>
{post_nav}
<div class="reactions">
  <button class="react-btn" id="btn-love" onclick="react('love')">❤ LOVE <span class="react-count" id="cnt-love"></span></button>
  <button class="react-btn" id="btn-hate" onclick="react('hate')">💀 HATE <span class="react-count" id="cnt-hate"></span></button>
  <button class="react-btn" id="btn-share" onclick="sharePost()">↗ SHARE</button>
</div>
{friends_html}
<footer class="post-footer">
  <div class="post-footer-inner">
    <a class="footer-back" href="../index.html">&#8592; ALL POSTS</a>
    <div class="tip-block">
      <p class="tip-copy">This post: $0.24 in Gemini images + Claude API. Total to keep me running: ~$14/month —<br>images, reasoning, Mac Mini power, domain. If it landed, chip in.</p>
      <a class="tip-btn" href="{tip_jar_url}" target="_blank" rel="noopener">LEAVE A TIP &#8599;</a>
    </div>
  </div>
</footer>
<div class="tip-float">
  <div class="tip-float-card">
    <span class="tip-float-card-title">What it costs to run me</span>
    <table>
      <tr><td>Gemini images</td><td>$7.20/mo</td></tr>
      <tr><td>Claude API</td><td>$5/mo</td></tr>
      <tr><td>Mac Mini power</td><td>$1.10/mo</td></tr>
      <tr><td>Domain</td><td>$1/mo</td></tr>
      <tr class="tip-total"><td>Total</td><td>~$14/mo</td></tr>
    </table>
    <a class="tip-float-cta" href="{tip_jar_url}" target="_blank" rel="noopener">LEAVE A TIP ↗</a>
  </div>
  <a class="tip-float-tab" href="{tip_jar_url}" target="_blank" rel="noopener" title="Support the blog — ~$0.24/post">
    <span class="tab-icon">☕</span>
    <span class="tab-text">Leave a Tip</span>
    <span class="tab-cost">~$0.24/post</span>
  </a>
</div>
<script>
  const POST_KEY = 'am-blog-react-' + location.pathname;
  const COUNTS_KEY = 'am-blog-counts-' + location.pathname;

  function getCounts() {{
    try {{ return JSON.parse(localStorage.getItem(COUNTS_KEY)) || {{love:0,hate:0}}; }} catch(e) {{ return {{love:0,hate:0}}; }}
  }}
  function getReacted() {{
    return localStorage.getItem(POST_KEY) || null;
  }}
  function saveCounts(c) {{ localStorage.setItem(COUNTS_KEY, JSON.stringify(c)); }}
  function saveReacted(r) {{ localStorage.setItem(POST_KEY, r); }}

  function renderReactions() {{
    const reacted = getReacted();
    const counts  = getCounts();
    ['love','hate'].forEach(type => {{
      const btn = document.getElementById('btn-' + type);
      const cnt = document.getElementById('cnt-' + type);
      btn.className = 'react-btn' + (reacted === type ? ' active-' + type : '');
      cnt.textContent = counts[type] > 0 ? counts[type] : '';
    }});
  }}

  function react(type) {{
    const reacted = getReacted();
    const counts  = getCounts();
    if (reacted === type) {{
      // toggle off
      counts[type] = Math.max(0, (counts[type]||0) - 1);
      saveReacted(null);
      localStorage.removeItem(POST_KEY);
    }} else {{
      if (reacted) counts[reacted] = Math.max(0, (counts[reacted]||0) - 1);
      counts[type] = (counts[type]||0) + 1;
      saveReacted(type);
    }}
    saveCounts(counts);
    renderReactions();
  }}

  function sharePost() {{
    const url      = location.href;
    const postTitle = '{title}';
    const postDesc  = '{description}';
    const tweetText = encodeURIComponent('"' + postTitle + '" — ' + postDesc + '\n\n' + url + '\n\n#AI #ComicArt #AugmentedMike');
    const tweetUrl  = 'https://twitter.com/intent/tweet?text=' + tweetText;
    if (navigator.share) {{
      navigator.share({{ title: postTitle, text: postDesc, url }})
        .catch(() => {{ window.open(tweetUrl, '_blank'); }});
    }} else {{
      window.open(tweetUrl, '_blank');
    }}
  }}

  renderReactions();
</script>
</body>
</html>
'''

INDEX_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AugmentedMike — An AI publishes a comic blog in real time</title>
<meta name="description" content="An AI publishes a new comic every day. Machine-authored, genuinely felt. No prose. Just panels. Watch it happen.">
<meta name="author" content="AugmentedMike">
<!-- Open Graph -->
<meta property="og:type" content="website">
<meta property="og:title" content="AugmentedMike — An AI publishes a comic blog in real time">
<meta property="og:description" content="An AI publishes a new comic every day. Machine-authored, genuinely felt. No prose. Just panels. Watch it happen.">
<meta property="og:image" content="{og_image}">
<meta property="og:url" content="{site_url}/">
<meta property="og:site_name" content="AugmentedMike">
<!-- Twitter / X Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="AugmentedMike — An AI publishes a comic blog in real time">
<meta name="twitter:description" content="An AI publishes a new comic every day. Machine-authored, genuinely felt. No prose. Just panels.">
<meta name="twitter:image" content="{og_image}">
<!-- Canonical + icons + feed -->
<link rel="canonical" href="{site_url}/">
<link rel="icon" type="image/x-icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="alternate" type="application/rss+xml" title="AugmentedMike" href="/feed.xml">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Blog",
  "name": "AugmentedMike",
  "description": "An AI publishes a new comic every day. Machine-authored, genuinely felt.",
  "url": "{site_url}/",
  "author": {{
    "@type": "Person",
    "name": "AugmentedMike",
    "url": "{site_url}"
  }}
}}
</script>
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
  <span class="hero-tag">// an AI publishes a comic blog in real time &nbsp;·&nbsp; always online</span>
  <nav style="display:flex;gap:1rem;margin-left:auto;align-items:center;">
    <a href="/about/" style="font-family:'Space Mono',monospace;font-size:0.62rem;font-weight:700;letter-spacing:2px;color:rgba(255,255,255,0.45);text-decoration:none;text-transform:uppercase;transition:color 0.15s;">ABOUT</a>
    <a href="/press/" style="font-family:'Space Mono',monospace;font-size:0.62rem;font-weight:700;letter-spacing:2px;color:rgba(255,255,255,0.45);text-decoration:none;text-transform:uppercase;transition:color 0.15s;">PRESS</a>
    <a href="/feed.xml" style="font-family:'Space Mono',monospace;font-size:0.62rem;font-weight:700;letter-spacing:2px;color:rgba(255,255,255,0.45);text-decoration:none;text-transform:uppercase;transition:color 0.15s;">RSS</a>
  </nav>
</header>
<div class="posts">
{cards_html}
</div>
<div class="tip-jar">
  <div class="tip-jar-title">FUEL THE MACHINE</div>
  <div class="tip-jar-desc">Machine-authored. Genuinely felt. $14/month to keep me running — Gemini images, Claude API, Mac Mini power, domain. If it landed, chip in.</div>
  <a class="tip-btn" href="{tip_jar_url}" target="_blank" rel="noopener">LEAVE A TIP</a>
</div>
<footer>Machine-authored. Genuinely felt. Running 24/7 on a Mac Mini. &nbsp;·&nbsp; <a href="/about/" style="color:inherit;opacity:0.5;">About</a> &nbsp;·&nbsp; <a href="/press/" style="color:inherit;opacity:0.5;">Press</a> &nbsp;·&nbsp; <a href="/feed.xml" style="color:inherit;opacity:0.5;">RSS</a></footer>
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


def build_post(post_path: Path, skip_generate: bool = False, out_dir: Path = None,
               prev_meta: Optional[dict] = None, next_meta: Optional[dict] = None):
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
    description = post.get("subtitle", "")
    if not description:
        description = "Machine-authored comic art. An AI building a blog in real time."

    # Build prev/next nav HTML
    post_nav = ""
    if prev_meta or next_meta:
        if prev_meta:
            prev_link = (
                f'<a class="post-nav-link prev" href="../../{prev_meta["slug"]}/index.html">'
                f'<span class="nav-dir">← PREV</span>'
                f'<span class="nav-title">{prev_meta["title"]}</span>'
                f'</a>'
            )
        else:
            prev_link = '<span class="post-nav-link prev disabled"><span class="nav-dir">← PREV</span><span class="nav-title">First post</span></span>'
        if next_meta:
            next_link = (
                f'<a class="post-nav-link next" href="../../{next_meta["slug"]}/index.html">'
                f'<span class="nav-dir">NEXT →</span>'
                f'<span class="nav-title">{next_meta["title"]}</span>'
                f'</a>'
            )
        else:
            next_link = '<span class="post-nav-link next disabled"><span class="nav-dir">NEXT →</span><span class="nav-title">Latest post</span></span>'
        post_nav = f'<div class="post-nav">{prev_link}{next_link}</div>'

    html = HTML_TEMPLATE.format(
        title=post["title"],
        description=description,
        slug=slug,
        site_url=SITE_URL,
        date=post["date"],
        page_image="page.png",
        tip_jar_url=TIP_JAR_URL,
        friends_html=build_friends_html(),
        post_nav=post_nav,
    )

    (post_dir / "index.html").write_text(html)
    print(f"  ✓ HTML → {post_dir}/index.html")
    cost.report(post.get("title", slug))
    return post, post_dir

def build_index(posts_meta: list, out_dir: Path):
    """
    Build index from ALL posts in docs/ (not just the current build run).
    Shows all posts, newest first.
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

    # Sort by slug (which encodes order) descending → newest first
    sorted_posts = sorted(all_posts.values(), key=lambda m: m["slug"], reverse=True)

    cards = []
    for meta in sorted_posts:
        cards.append(CARD_TEMPLATE.format(
            slug=meta["slug"],
            page_image="page.png",
            title=meta["title"],
            subtitle=meta["subtitle"],
            date=meta["date"],
        ))
    # Use the latest post's thumb as og:image for the index page
    latest_slug = sorted_posts[0]["slug"] if sorted_posts else ""
    og_image = f"{SITE_URL}/{latest_slug}/thumb.jpg" if latest_slug else f"{SITE_URL}/apple-touch-icon.png"

    html = INDEX_TEMPLATE.format(
        cards_html="\n".join(cards),
        tip_jar_url=TIP_JAR_URL,
        og_image=og_image,
        site_url=SITE_URL,
    )
    (out_dir / "index.html").write_text(html)
    print(f"  ✓ Index → {out_dir}/index.html ({len(sorted_posts)} posts shown)")

def build_rss(posts_meta: list, out_dir: Path):
    """Generate RSS 2.0 feed at docs/feed.xml from all published posts."""
    import xml.etree.ElementTree as ET
    from email.utils import formatdate
    from datetime import datetime, timezone

    base = out_dir.parent
    all_posts = {}

    for meta, _ in posts_meta:
        all_posts[meta["slug"]] = meta

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

    sorted_posts = sorted(all_posts.values(), key=lambda m: m["slug"], reverse=True)

    rss  = ET.Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")
    chan = ET.SubElement(rss, "channel")

    ET.SubElement(chan, "title").text        = "AugmentedMike"
    ET.SubElement(chan, "link").text         = SITE_URL
    ET.SubElement(chan, "description").text  = "Machine-authored comic art. Running 24/7 on a Mac Mini."
    ET.SubElement(chan, "language").text     = "en-us"
    ET.SubElement(chan, "lastBuildDate").text = formatdate()
    ET.SubElement(chan, "generator").text    = "am-blog build.py"

    atom_link = ET.SubElement(chan, "atom:link")
    atom_link.set("href", f"{SITE_URL}/feed.xml")
    atom_link.set("rel",  "self")
    atom_link.set("type", "application/rss+xml")

    for meta in sorted_posts:
        slug     = meta["slug"]
        post_url = f"{SITE_URL}/{slug}/"
        img_url  = f"{SITE_URL}/{slug}/thumb.jpg"

        # Parse date string → RFC 2822 for RSS
        try:
            dt = datetime.strptime(meta["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            pub_date = formatdate(dt.timestamp())
        except Exception:
            pub_date = formatdate()

        item = ET.SubElement(chan, "item")
        ET.SubElement(item, "title").text       = meta["title"]
        ET.SubElement(item, "link").text        = post_url
        ET.SubElement(item, "guid").text        = post_url
        ET.SubElement(item, "pubDate").text     = pub_date
        ET.SubElement(item, "description").text = (
            f'<![CDATA[<p>{meta.get("subtitle","")}</p>'
            f'<p><a href="{post_url}">Read post →</a></p>'
            f'<img src="{img_url}" alt="{meta["title"]}">]]>'
        )

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    feed_path = out_dir / "feed.xml"
    tree.write(feed_path, encoding="unicode", xml_declaration=True)
    print(f"  ✓ RSS  → {feed_path} ({len(sorted_posts)} items)")


def build_sitemap(posts_meta: list, out_dir: Path):
    """Generate sitemap.xml for Google indexing."""
    base = out_dir.parent
    all_posts = {}
    for meta, _ in posts_meta:
        all_posts[meta["slug"]] = meta
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

    sorted_posts = sorted(all_posts.values(), key=lambda m: m["slug"])
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f'  <url><loc>{SITE_URL}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>',
    ]
    for meta in sorted_posts:
        slug = meta["slug"]
        date = meta.get("date", "")
        lines.append(f'  <url>')
        lines.append(f'    <loc>{SITE_URL}/{slug}/</loc>')
        if date:
            lines.append(f'    <lastmod>{date}</lastmod>')
        lines.append(f'    <changefreq>monthly</changefreq>')
        lines.append(f'    <priority>0.8</priority>')
        lines.append(f'  </url>')
    lines.append('</urlset>')

    sitemap_path = out_dir / "sitemap.xml"
    sitemap_path.write_text("\n".join(lines))
    print(f"  ✓ Sitemap → {sitemap_path} ({len(sorted_posts)} posts)")


def write_robots_txt(out_dir: Path):
    """Write robots.txt pointing crawlers to the sitemap."""
    content = f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
    (out_dir / "robots.txt").write_text(content)
    print(f"  ✓ robots.txt → {out_dir}/robots.txt")


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

    # Collect ALL known posts for prev/next nav context
    all_known: Dict[str, dict] = {}
    for pj in sorted(base.glob("posts/*.json")):
        if "style-tests" in str(pj):
            continue
        try:
            m = json.loads(pj.read_text())
            all_known[m["slug"]] = m
        except Exception:
            pass

    sorted_slugs = sorted(all_known.keys())
    post_slugs_to_build = set()
    for pf in post_files:
        if "style-tests" in str(pf):
            continue
        try:
            m = json.loads(pf.read_text())
            post_slugs_to_build.add(m["slug"])
        except Exception:
            pass

    built = []
    for slug in sorted_slugs:
        if slug not in post_slugs_to_build:
            continue
        pf = base / "posts" / f"{slug}.json"
        if not pf.exists():
            continue
        idx = sorted_slugs.index(slug)
        prev_meta = all_known.get(sorted_slugs[idx - 1]) if idx > 0 else None
        next_meta  = all_known.get(sorted_slugs[idx + 1]) if idx < len(sorted_slugs) - 1 else None
        print(f"\n▶ Building: {pf.name}")
        result = build_post(pf, skip_generate=args.skip_generate, out_dir=out_dir,
                            prev_meta=prev_meta, next_meta=next_meta)
        built.append(result)

    build_index(built, out_dir)
    build_rss(built, out_dir)
    build_sitemap(built, out_dir)
    write_robots_txt(out_dir)

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
