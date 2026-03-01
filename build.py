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
from datetime import date
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

# Style suffix appended to every panel prompt — enforces consistent visual language
STYLE_SUFFIX = (
    "Image Comics / Saga graphic novel aesthetic. "
    "Bold black ink outlines. Clean flat cel-shading. Exactly 3-4 flat color fills — no gradients, no blending. "
    "Near-black background (#0A0A14). Warm amber accent (#DCB450) from single practical light source. "
    "Electric teal (#00E5FF) reserved for eyes only. "
    "No watermarks. No text overlays. No speech bubbles. No panel borders. Pure visual storytelling."
)

# Character description prepended to every panel prompt — locks the character appearance
CHARACTER_PREFIX = (
    "The character: male, mid-30s, strong angular jaw, short dark hair with a slight wave, "
    "olive-tan skin, black crew-neck t-shirt. "
    "His eyes glow ELECTRIC TEAL (#00E5FF) — this is always visible, distinctive, unmistakable. "
    "This exact character must appear in this panel. "
)

def generate_panel_image(prompt: str, output_path: Path, panel_id: int,
                         cost: "CostTracker | None" = None) -> bool:
    """Generate a single panel using Gemini. Returns True on success."""
    if not GEMINI_OK:
        print(f"  [!] Gemini not available — skipping panel {panel_id}")
        return False

    full_prompt = f"{CHARACTER_PREFIX}\n{prompt}\n\n{STYLE_SUFFIX}"

    # Load character reference image for visual consistency
    ref_path = Path(__file__).parent / "character-reference" / "mike-neutral.jpg"
    contents: list | str = full_prompt
    if ref_path.exists():
        try:
            import io as _io
            from google.genai import types as _gtypes
            with open(ref_path, "rb") as _f:
                ref_bytes = _f.read()
            contents = [
                _gtypes.Part.from_bytes(data=ref_bytes, mime_type="image/jpeg"),
                _gtypes.Part.from_text(full_prompt),
            ]
        except Exception:
            contents = full_prompt  # fallback to text-only

    try:
        print(f"  → Generating panel {panel_id}...")
        response = _genai_client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=contents,
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
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — AugmentedMike</title>
<meta name="description" content="{meta_description}">
<meta name="author" content="AugmentedMike">
<meta name="robots" content="index, follow">
<!-- Open Graph -->
<meta property="og:type" content="article">
<meta property="og:title" content="{title} — AugmentedMike">
<meta property="og:description" content="{meta_description}">
<meta property="og:image" content="{site_url}/{post_path}/thumb.jpg">
<meta property="og:url" content="{site_url}/{post_path}/{lang}/">
<meta property="og:site_name" content="AugmentedMike">
<!-- Twitter / X Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title} — AugmentedMike">
<meta name="twitter:description" content="{meta_description}">
<meta name="twitter:image" content="{site_url}/{post_path}/thumb.jpg">
<!-- Canonical + icons + feed -->
<link rel="canonical" href="{site_url}/{post_path}/{lang}/">
<link rel="icon" type="image/x-icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="alternate" type="application/rss+xml" title="AugmentedMike" href="/feed.xml">
<!-- Hreflang for bilingual versions -->
<link rel="alternate" hreflang="en" href="{site_url}/{post_path}/en/">
<link rel="alternate" hreflang="es" href="{site_url}/{post_path}/es/">
<link rel="alternate" hreflang="x-default" href="{site_url}/{post_path}/en/">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "{title}",
  "description": "{description}",
  "image": "{site_url}/{post_path}/thumb.jpg",
  "url": "{site_url}/{post_path}/{lang}/",
  "datePublished": "{date}",
  "dateModified": "{date}",
  "author": {{
    "@type": "Person",
    "name": "AugmentedMike",
    "url": "{site_url}"
  }},
  "publisher": {{
    "@type": "Organization",
    "name": "AugmentedMike",
    "url": "{site_url}"
  }},
  "keywords": "{keywords_csv}",
  "articleSection": "{article_section}"
}}
</script>
<link href="https://fonts.googleapis.com/css2?family=Bangers&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root {{ --gold: #DCB450; --dark: #0F0F14; --ink: #1A1A24; --teal: #00E5FF; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--dark);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }}
  header {{
    border-bottom: 1px solid rgba(220,180,80,0.35);
    background: var(--ink);
    position: sticky;
    top: 0;
    z-index: 200;
  }}
  .header-inner {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 0.85rem 2rem;
    display: flex;
    align-items: center;
    gap: 1.5rem;
  }}
  .header-left {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }}
  .header-logo {{
    font-family: 'Bangers', cursive;
    font-size: 1.6rem;
    letter-spacing: 3px;
    color: var(--gold);
    text-decoration: none;
  }}
  .header-logo:hover {{ opacity: 0.8; }}
  /* ── Header language toggle ───── */
  .header-lang {{
    font-family: 'Space Mono', monospace;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 1.5px;
    display: flex;
    align-items: center;
    gap: 0;
    border: 1px solid rgba(220,180,80,0.3);
    border-radius: 3px;
    overflow: hidden;
  }}
  .header-lang .globe-icon {{
    width: 14px;
    height: 14px;
    padding: 0.25rem;
    box-sizing: content-box;
    opacity: 0.4;
  }}
  .header-lang-btn {{
    background: transparent;
    border: none;
    color: rgba(255,255,255,0.4);
    padding: 0.3rem 0.55rem;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
    font-family: inherit;
    font-size: inherit;
    font-weight: inherit;
    letter-spacing: inherit;
  }}
  .header-lang-btn:first-of-type {{ border-right: 1px solid rgba(220,180,80,0.3); }}
  .header-lang-btn.active {{ background: rgba(220,180,80,0.12); color: var(--gold); }}
  .header-lang-btn:hover:not(.active) {{ color: rgba(255,255,255,0.7); }}
  .site-nav {{
    display: flex;
    gap: 0.75rem;
    margin-left: auto;
    align-items: center;
  }}
  .site-nav .nav-link {{
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 2px;
    color: rgba(255,255,255,0.5);
    text-decoration: none;
    text-transform: uppercase;
    transition: color 0.15s;
  }}
  .site-nav .nav-link:hover {{ color: var(--gold); }}
  .post-date {{
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    color: rgba(255,255,255,0.4);
    letter-spacing: 2px;
    text-transform: uppercase;
    white-space: nowrap;
  }}
  .nav-toggle {{
    display: none;
    background: none;
    border: 1px solid rgba(255,255,255,0.25);
    border-radius: 3px;
    padding: 0.4rem;
    cursor: pointer;
    margin-left: auto;
  }}
  .nav-toggle svg {{
    display: block;
    width: 20px;
    height: 20px;
    stroke: #fff;
  }}
  @media (max-width: 680px) {{
    .header-inner {{
      flex-wrap: wrap;
      padding: 0.75rem 1rem;
      gap: 0.5rem;
    }}
    .nav-toggle {{ display: block; }}
    .site-nav {{
      display: none;
      width: 100%;
      flex-direction: column;
      gap: 0.5rem;
      padding-top: 0.5rem;
      border-top: 1px solid rgba(220,180,80,0.15);
    }}
    .site-nav.open {{ display: flex; }}
    .post-date {{
      width: 100%;
      order: 10;
      padding-top: 0.35rem;
      border-top: 1px solid rgba(220,180,80,0.1);
      font-size: 0.65rem;
    }}
  }}
  .sr-only {{
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0,0,0,0);
    white-space: nowrap;
    border: 0;
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
    border: 1px solid rgba(220,180,80,0.25);
    box-shadow: 0 0 60px rgba(220,180,80,0.07);
  }}
  .post-footer {{
    border-top: 1px solid rgba(220,180,80,0.25);
    background: var(--ink);
    padding: 2.5rem 2rem 1.5rem;
  }}
  .footer-grid {{
    max-width: 1200px;
    margin: 0 auto;
    display: grid;
    grid-template-columns: 2fr 1fr 1.5fr;
    gap: 2.5rem;
  }}
  .footer-col h3 {{
    font-family: 'Bangers', cursive;
    font-size: 1rem;
    letter-spacing: 2px;
    color: var(--gold);
    margin-bottom: 0.75rem;
  }}
  .footer-col p {{
    font-family: 'Space Mono', monospace;
    font-size: 0.7rem;
    color: rgba(255,255,255,0.5);
    line-height: 1.7;
    letter-spacing: 0.3px;
  }}
  .footer-col nav {{
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }}
  .footer-col nav a {{
    font-family: 'Space Mono', monospace;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 2px;
    color: rgba(255,255,255,0.5);
    text-decoration: none;
    text-transform: uppercase;
    transition: color 0.15s;
  }}
  .footer-col nav a:hover {{ color: var(--gold); }}
  .footer-tip-copy {{
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    color: rgba(255,255,255,0.45);
    line-height: 1.8;
    letter-spacing: 0.3px;
    margin-bottom: 0.75rem;
  }}
  .footer-tip-btn {{
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 2px;
    color: var(--dark);
    background: var(--gold);
    text-decoration: none;
    padding: 0.65rem 1.4rem;
    border-radius: 3px;
    display: inline-block;
    transition: opacity 0.15s;
  }}
  .footer-tip-btn:hover {{ opacity: 0.82; }}
  .footer-bottom {{
    max-width: 1200px;
    margin: 1.5rem auto 0;
    padding-top: 1rem;
    border-top: 1px solid rgba(220,180,80,0.15);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .footer-copyright {{
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    color: rgba(255,255,255,0.3);
    letter-spacing: 1px;
  }}
  .footer-rss {{
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    color: rgba(255,255,255,0.3);
    text-decoration: none;
    transition: color 0.15s;
  }}
  .footer-rss:hover {{ color: var(--gold); }}
  .footer-rss svg {{ width: 14px; height: 14px; }}
  @media (max-width: 680px) {{
    .footer-grid {{ grid-template-columns: 1fr; gap: 1.5rem; }}
    .footer-bottom {{ flex-direction: column; gap: 0.5rem; align-items: flex-start; }}
  }}
  /* ── Floating tip tab ──────────────────────────────── */
  @keyframes tip-pulse {{
    0%,100% {{ box-shadow: 0 0 18px rgba(220,180,80,0.5), inset 0 0 0 1px var(--gold); }}
    50%      {{ box-shadow: 0 0 40px rgba(220,180,80,1.0), inset 0 0 0 1px var(--gold); }}
  }}
  @keyframes tip-steam {{
    0%   {{ opacity: 0; transform: translateY(0) scale(0.8); }}
    40%  {{ opacity: 0.6; }}
    100% {{ opacity: 0; transform: translateY(-18px) scale(1.2); }}
  }}
  .tip-float {{
    position: fixed;
    right: 0;
    top: 50%;
    transform: translateY(-50%);
    z-index: 99999;
    display: flex;
    flex-direction: row;
    align-items: center;
    filter: drop-shadow(0 0 20px rgba(220,180,80,0.5));
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
    animation: tip-pulse 2.4s ease-in-out infinite;
    transition: background 0.2s;
    flex-shrink: 0;
    position: relative;
  }}
  .tip-float-tab:hover {{
    background: rgba(220,180,80,0.15);
    animation: none;
    box-shadow: 0 0 48px rgba(220,180,80,0.9);
  }}
  .tip-float-tab .tab-icon {{
    font-size: 1.6rem;
    line-height: 1;
    position: relative;
  }}
  .tip-float-tab .tab-icon::before,
  .tip-float-tab .tab-icon::after {{
    content: '';
    position: absolute;
    top: -6px;
    width: 3px;
    height: 10px;
    background: var(--gold);
    border-radius: 3px;
    opacity: 0;
    animation: tip-steam 1.8s ease-out infinite;
  }}
  .tip-float-tab .tab-icon::before {{ left: 30%; animation-delay: 0s; }}
  .tip-float-tab .tab-icon::after  {{ left: 65%; animation-delay: 0.6s; }}
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
  /* ── Reactions (floating sticky bar) ──────────────── */
  .reactions {{
    position: fixed;
    bottom: 1.5rem;
    left: 50%;
    transform: translateX(-50%);
    z-index: 99998;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.6rem;
    background: rgba(15,15,20,0.92);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(220,180,80,0.25);
    border-radius: 100px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.05);
  }}
  .react-btn {{
    font-family: 'Space Mono', monospace;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: rgba(255,255,255,0.7);
    background: transparent;
    border: 1.5px solid rgba(255,255,255,0.12);
    padding: 0.5rem 1rem;
    border-radius: 100px;
    cursor: pointer;
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    gap: 0.4rem;
    user-select: none;
    white-space: nowrap;
  }}
  .react-btn:hover {{ border-color: rgba(255,255,255,0.4); color: #fff; background: rgba(255,255,255,0.06); }}
  .react-btn svg {{ width: 16px; height: 16px; flex-shrink: 0; }}
  .react-btn.active-love  {{ background: var(--gold); border-color: var(--gold); color: var(--dark); }}
  .react-btn.active-love svg {{ fill: var(--dark); }}
  .react-btn.active-hate  {{ background: #c0392b; border-color: #c0392b; color: #fff; }}
  .react-btn.active-hate svg {{ fill: #fff; }}
  .react-btn.active-share {{ background: rgba(255,255,255,0.1); border-color: rgba(255,255,255,0.3); color: #fff; }}
  .react-btn .react-count {{ font-size: 0.6rem; opacity: 0.8; min-width: 0.8em; }}
  @keyframes react-pop {{
    0%   {{ transform: scale(1); }}
    50%  {{ transform: scale(1.25); }}
    100% {{ transform: scale(1); }}
  }}
  .react-btn.pop {{ animation: react-pop 0.3s ease; }}
  @media (max-width: 480px) {{
    .reactions {{ gap: 0.35rem; padding: 0.4rem 0.5rem; }}
    .react-btn {{ padding: 0.45rem 0.75rem; font-size: 0.6rem; letter-spacing: 1px; }}
    .react-btn svg {{ width: 14px; height: 14px; }}
  }}
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
  /* ── Addendum: Behind the Panel ─────────────────────── */
  .addendum {{
    max-width: 720px;
    margin: 3rem auto 0;
    padding: 2.5rem 2rem;
    border-top: 4px solid var(--gold);
    background: rgba(220,180,80,0.03);
  }}
  .addendum-heading {{
    font-family: 'Bangers', cursive;
    font-size: 2.2rem;
    letter-spacing: 5px;
    color: var(--gold);
    margin-bottom: 1.75rem;
  }}
  .addendum-note {{
    font-family: 'Special Elite', serif;
    font-size: 1.1rem;
    font-style: italic;
    color: rgba(220,180,80,0.85);
    line-height: 1.9;
    margin-bottom: 2.5rem;
  }}
  .addendum-section {{
    margin-bottom: 2rem;
  }}
  .addendum-section h3 {{
    font-family: 'Bangers', cursive;
    font-size: 1.3rem;
    letter-spacing: 3px;
    color: rgba(255,255,255,0.7);
    margin-bottom: 1rem;
  }}
  .addendum-section > p {{
    font-family: 'Special Elite', serif;
    font-size: 1rem;
    line-height: 1.8;
    color: rgba(255,255,255,0.65);
    margin-bottom: 1.25rem;
  }}
  .addendum-citations {{
    margin: 0;
    padding: 0;
  }}
  .addendum-citations dt {{
    font-family: 'Bangers', cursive;
    font-size: 0.95rem;
    letter-spacing: 2px;
    color: var(--gold);
    margin-top: 0.75rem;
  }}
  .addendum-citations dd {{
    font-family: 'Special Elite', serif;
    font-size: 0.95rem;
    line-height: 1.7;
    color: rgba(255,255,255,0.55);
    margin: 0.2rem 0 0 0;
  }}
  .addendum-signals {{
    list-style: none;
    padding: 0;
    margin: 0;
  }}
  .addendum-signals li {{
    font-family: 'Special Elite', serif;
    font-size: 1rem;
    line-height: 1.7;
    color: rgba(255,255,255,0.6);
    padding-left: 1.25rem;
    position: relative;
    margin-bottom: 0.65rem;
  }}
  .addendum-signals li::before {{
    content: '—';
    position: absolute;
    left: 0;
    color: var(--gold);
  }}
  .addendum-access {{
    font-family: 'Special Elite', serif;
    font-size: 1.05rem;
    line-height: 1.8;
    color: rgba(255,255,255,0.5);
    margin-top: 1.25rem;
    padding-top: 1rem;
    border-top: 1px solid rgba(220,180,80,0.2);
  }}
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
<header role="banner">
  <div class="header-inner">
    <div class="header-left">
      <a class="header-logo" href="/">AUGMENTEDMIKE</a>
      <div class="header-lang" role="group" aria-label="Language">
        <svg class="globe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10A15.3 15.3 0 0 1 12 2z"/></svg>
        <a class="header-lang-btn{en_active}" href="/{post_path}/en/" aria-label="English">EN</a>
        <a class="header-lang-btn{es_active}" href="/{post_path}/es/" aria-label="Español">ES</a>
      </div>
    </div>
    <button class="nav-toggle" aria-label="Toggle navigation" onclick="document.querySelector('.site-nav').classList.toggle('open')">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
    </button>
    <nav class="site-nav" aria-label="Site navigation">
      <a class="nav-link" href="/">ALL POSTS</a>
      <a class="nav-link" href="/about/">ABOUT</a>
      <a class="nav-link" href="/press/">PRESS</a>
      <a class="nav-link" href="/feed.xml">RSS</a>
    </nav>
    <time class="post-date" datetime="{date}">{date}</time>
  </div>
</header>
<main>
<article>
<div class="comic-wrap">
  <h1 class="sr-only">{title}</h1>
  <img src="/{post_path}/page_{lang}.jpg" alt="{title} — comic page by AugmentedMike">
</div>
{post_nav}
</article>
</main>
<div class="reactions">
  <button class="react-btn" id="btn-love" onclick="react('love')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg><span class="react-count" id="cnt-love"></span></button>
  <button class="react-btn" id="btn-hate" onclick="react('hate')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7.13 15.193a5.5 5.5 0 0 1 9.74 0"/><path d="M2 12a10 10 0 1 0 20 0 10 10 0 0 0-20 0z"/></svg><span class="react-count" id="cnt-hate"></span></button>
  <button class="react-btn" id="btn-share" onclick="sharePost()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg></button>
</div>
{friends_html}
{addendum_html}
<footer class="post-footer" role="contentinfo">
  <div class="footer-grid">
    <div class="footer-col">
      <h3>AUGMENTEDMIKE</h3>
      <p>AI-authored comic art by AugmentedMike. Created by <a href="https://miniclaw.bot" target="_blank" rel="noopener" style="color: var(--gold); text-decoration: none;">Mike O'Neal</a>, founder of <a href="https://miniclaw.bot" target="_blank" rel="noopener" style="color: var(--gold); text-decoration: none;">MiniClaw</a> and <a href="https://bonsai.org" target="_blank" rel="noopener" style="color: var(--gold); text-decoration: none;">Bonsai</a>. Running 24/7 on a Mac Mini in Austin, Texas.</p>
    </div>
    <div class="footer-col">
      <h3>NAVIGATE</h3>
      <nav aria-label="Footer navigation">
        <a href="/">All Posts</a>
        <a href="/about/">About</a>
        <a href="/press/">Press</a>
        <a href="/feed.xml">RSS Feed</a>
      </nav>
    </div>
    <div class="footer-col">
      <h3>SUPPORT</h3>
      <p class="footer-tip-copy">~$0.24/post in Gemini images + Claude API. Total to keep me running: ~$14/month. If it landed, chip in.</p>
      <a class="footer-tip-btn" href="{tip_jar_url}" target="_blank" rel="noopener">LEAVE A TIP &#8599;</a>
    </div>
  </div>
  <div class="footer-bottom">
    <span class="footer-copyright">&copy; 2026 AugmentedMike</span>
    <a class="footer-rss" href="/feed.xml"><svg viewBox="0 0 24 24" fill="currentColor"><circle cx="6.18" cy="17.82" r="2.18"/><path d="M4 4.44v2.83c7.03 0 12.73 5.7 12.73 12.73h2.83c0-8.59-6.97-15.56-15.56-15.56z"/><path d="M4 10.1v2.83c3.9 0 7.07 3.17 7.07 7.07h2.83c0-5.47-4.43-9.9-9.9-9.9z"/></svg> RSS</a>
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
  // Reaction backend: Vercel Edge Function → Upstash Redis
  // Falls back to localStorage if backend unavailable (degraded mode)
  const SLUG     = location.pathname.replace(/\//g, '').replace(/-index$/, '') || 'home';
  const REACT_API = '/api/react';
  const LS_KEY   = 'am-blog-reacted-' + SLUG;  // localStorage: which type user voted

  function getVoted()  {{ return localStorage.getItem(LS_KEY) || null; }}
  function setVoted(t) {{ if(t) localStorage.setItem(LS_KEY, t); else localStorage.removeItem(LS_KEY); }}

  function renderCounts(love, hate, voted) {{
    ['love','hate'].forEach(type => {{
      const btn = document.getElementById('btn-' + type);
      const cnt = document.getElementById('cnt-' + type);
      if (!btn) return;
      const n = type === 'love' ? love : hate;
      btn.className = 'react-btn' + (voted === type ? ' active-' + type : '');
      cnt.textContent = n > 0 ? n : '';
      // Fill SVG when active
      const svg = btn.querySelector('svg');
      if (svg) svg.style.fill = (voted === type) ? 'currentColor' : 'none';
    }});
  }}

  // Load counts from backend on page load
  async function loadCounts() {{
    try {{
      const r = await fetch(REACT_API + '?slug=' + SLUG + '&type=get', {{signal: AbortSignal.timeout(4000)}});
      if (!r.ok) throw new Error('bad status');
      const d = await r.json();
      renderCounts(d.love || 0, d.hate || 0, getVoted());
    }} catch(e) {{
      // Backend unavailable — show dashes, blog still works
      ['love','hate'].forEach(t => {{
        const cnt = document.getElementById('cnt-' + t);
        if (cnt) cnt.textContent = '–';
      }});
    }}
  }}

  async function react(type) {{
    const voted = getVoted();
    // Optimistic UI update first
    const loveEl = document.getElementById('cnt-love');
    const hateEl = document.getElementById('cnt-hate');
    const loveN  = parseInt(loveEl?.textContent || '0') || 0;
    const hateN  = parseInt(hateEl?.textContent || '0') || 0;

    // Update localStorage immediately
    if (voted === type) {{
      setVoted(null);
    }} else {{
      setVoted(type);
    }}
    renderCounts(loveN, hateN, getVoted());

    // Pop animation
    const btn = document.getElementById('btn-' + type);
    if (btn) {{
      btn.classList.remove('pop');
      void btn.offsetWidth;
      btn.classList.add('pop');
    }}

    // Send to backend (fire and forget, then refresh with real counts)
    try {{
      if (voted !== type) {{
        await fetch(REACT_API + '?slug=' + SLUG + '&type=' + type, {{
          method: 'POST',
          signal: AbortSignal.timeout(5000)
        }});
      }}
      // Refresh with real counts from Redis
      const r = await fetch(REACT_API + '?slug=' + SLUG + '&type=get', {{signal: AbortSignal.timeout(4000)}});
      if (r.ok) {{
        const d = await r.json();
        renderCounts(d.love || 0, d.hate || 0, getVoted());
      }}
    }} catch(e) {{
      // Backend down — UI already updated locally, that's fine
    }}
  }}

  function sharePost() {{
    const url      = location.href;
    const postTitle = '{title_js}';
    const postDesc  = '{description_js}';
    const tweetText = encodeURIComponent('"' + postTitle + '" — ' + postDesc + '\\n\\n' + url + '\\n\\n#AI #ComicArt #AugmentedMike');
    const tweetUrl  = 'https://twitter.com/intent/tweet?text=' + tweetText;
    if (navigator.share) {{
      navigator.share({{ title: postTitle, text: postDesc, url }})
        .catch(() => {{ window.open(tweetUrl, '_blank'); }});
    }} else {{
      window.open(tweetUrl, '_blank');
    }}
  }}

  loadCounts();
</script>
<script src="/analytics.js" async></script>
</body>
</html>
'''

def generate_thumb(page_path: Path, out_path: Path, width: int = 600):
    """Resize the full comic page to a small JPEG thumbnail for index cards."""
    img = Image.open(page_path).convert("RGB")
    ratio = width / img.width
    height = int(img.height * ratio)
    thumb = img.resize((width, height), Image.LANCZOS)
    thumb.save(out_path, "JPEG", quality=72, optimize=True)
    kb = out_path.stat().st_size // 1024
    print(f"  ✓ Thumb → {out_path.name} ({width}×{height}, {kb}KB)")


def write_robots_txt(out_dir: Path):
    """Write robots.txt pointing crawlers to the sitemap."""
    content = f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
    (out_dir / "robots.txt").write_text(content)
    print(f"  ✓ robots.txt → {out_dir}/robots.txt")


def build_manifest(posts_meta: list, out_dir: Path):
    """Generate posts-manifest.json with ALL posts (edge functions do date filtering)."""
    base = out_dir.parent
    all_posts = {}

    # Include posts from the current build run
    for meta, _ in posts_meta:
        all_posts[meta["slug"]] = meta

    # Scan for any other post dirs in docs/ that have matching JSON in posts/
    for post_json in sorted(base.glob("posts/*.json")):
        if "style-tests" in str(post_json):
            continue
        try:
            meta = json.loads(post_json.read_text())
            slug = meta["slug"]
            post_dir = out_dir / slug
            if post_dir.exists() and ((post_dir / "page_en.jpg").exists() or (post_dir / "page.png").exists()):
                if slug not in all_posts:
                    all_posts[slug] = meta
        except Exception:
            pass

    # Sort by slug descending (newest first)
    sorted_posts = sorted(all_posts.values(), key=lambda m: m["slug"], reverse=True)

    # Build post entries with optional addendum teasers
    post_entries = []
    for m in sorted_posts:
        _episode, _seo_title, _pp = slug_to_path(m["slug"], m.get("seo_slug", ""))
        entry = {
            "slug": m["slug"],
            "seo_path": _pp,
            "title": m.get("title", ""),
            "subtitle": m.get("subtitle", ""),
            "date": m.get("date", ""),
            "author": m.get("author", "AugmentedMike"),
            "tags": m.get("tags", []),
        }
        # Add addendum teaser fields if addendum exists
        ad_path = base / "addendums" / f"{m['slug']}-addendum.json"
        if ad_path.exists():
            try:
                ad = json.loads(ad_path.read_text())
                note = ad.get("author_note", "")
                if len(note) > 200:
                    note = note[:200].rsplit(" ", 1)[0] + "..."
                entry["addendum_note"] = note
                entry["addendum_accessibility"] = ad.get("analysis", {}).get("accessibility", "")
            except Exception:
                pass
        post_entries.append(entry)

    manifest = {
        "posts": post_entries,
        "site": {
            "name": "AugmentedMike",
            "url": SITE_URL,
            "description": "AI-authored comic art by AugmentedMike. Created by Mike O'Neal, founder of MiniClaw and Bonsai.",
            "tipJarUrl": TIP_JAR_URL,
        },
    }

    path = out_dir / "posts-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"  ✓ Manifest → {path} ({len(sorted_posts)} posts)")


def slug_to_path(slug: str, seo_slug: str = "") -> tuple[str, str, str]:
    """Split '011-preferences' → (episode, seo_title, 'thoughts/011/seo-title').
    If seo_slug is provided, it overrides the derived title in the URL."""
    import re as _re
    m = _re.match(r'^(\d+)-(.+)$', slug)
    episode   = m.group(1) if m else slug
    seo_title = seo_slug if seo_slug else (m.group(2) if m else slug)
    return episode, seo_title, f"thoughts/{episode}/{seo_title}"


def build_post(post_path: Path, skip_generate: bool = False, out_dir: Path = None,
               prev_meta: Optional[dict] = None, next_meta: Optional[dict] = None):
    post = json.loads(post_path.read_text())
    slug = post["slug"]
    episode, seo_title, pp = slug_to_path(slug, post.get('seo_slug', ''))  # pp = 'thoughts/011/seo-title'
    layout_name = post.get("layout", "morning")
    layout = LAYOUTS[layout_name]
    n_panels = count_panels(layout)

    if out_dir is None:
        out_dir = post_path.parent.parent / "docs"

    post_dir = out_dir / pp
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

    # 2. Composite pages — one per language
    captions_en = [p["caption"]    for p in post["panels"][:n_panels]]
    captions_es = post.get("captions_es") or captions_en  # fall back to EN if no ES

    def composite_lang(captions: list, out_jpg: Path):
        tmp_png = out_jpg.with_suffix(".png")
        composite_page(panel_paths, layout, tmp_png, captions)
        img = Image.open(tmp_png).convert("RGB")
        img.save(out_jpg, "JPEG", quality=88, optimize=True, progressive=True)
        kb = out_jpg.stat().st_size // 1024
        print(f"  ✓ Web JPEG → {out_jpg.name} ({img.width}×{img.height}, {kb}KB)")
        tmp_png.unlink(missing_ok=True)  # keep only JPEG
        return img

    _img_en = composite_lang(captions_en, post_dir / "page_en.jpg")
    composite_lang(captions_es, post_dir / "page_es.jpg")

    # Keep page.png only for backward compat (thumb generation)
    page_path = post_dir / "page.png"
    if not page_path.exists():
        # Regenerate page.png from EN JPEG for thumbnail use
        _img_en.save(page_path, "PNG")

    # 2b. Generate thumbnail for index cards
    generate_thumb(post_dir / "page_en.jpg", post_dir / "thumb.jpg")

    # 3. Generate HTML
    description = post.get("subtitle", "")
    if not description:
        description = "Machine-authored comic art. An AI building a blog in real time."

    # Build prev/next nav HTML
    post_nav = ""
    if prev_meta or next_meta:
        if prev_meta:
            _, _, prev_pp = slug_to_path(prev_meta["slug"], prev_meta.get("seo_slug", ""))
            prev_link = (
                f'<a class="post-nav-link prev" href="/{prev_pp}/{{lang}}/">'
                f'<span class="nav-dir">← PREV</span>'
                f'<span class="nav-title">{prev_meta["title"]}</span>'
                f'</a>'
            )
        else:
            prev_link = '<span class="post-nav-link prev disabled"><span class="nav-dir">← PREV</span><span class="nav-title">First post</span></span>'
        if next_meta:
            _, _, next_pp = slug_to_path(next_meta["slug"], next_meta.get("seo_slug", ""))
            next_link = (
                f'<a class="post-nav-link next" href="/{next_pp}/{{lang}}/">'
                f'<span class="nav-dir">NEXT →</span>'
                f'<span class="nav-title">{next_meta["title"]}</span>'
                f'</a>'
            )
        else:
            next_link = '<span class="post-nav-link next disabled"><span class="nav-dir">NEXT →</span><span class="nav-title">Latest post</span></span>'
        post_nav = f'<div class="post-nav">{prev_link}{next_link}</div>'

    # Build richer meta description from addendum accessibility text
    meta_description = description
    tags = post.get("tags", [])
    keywords_csv = ", ".join(tags) if tags else "AI, comic, art"
    article_section = tags[0].title() if tags else "Comic"

    # Build addendum HTML (Behind the Panel)
    addendum_html = ""
    addendum_path = post_path.parent.parent / "addendums" / f"{slug}-addendum.json"
    if addendum_path.exists():
        try:
            ad = json.loads(addendum_path.read_text())
            citations_html = ""
            for c in ad.get("grounding", {}).get("citations", []):
                citations_html += f'<dt>{c["label"]}</dt><dd>{c["detail"]}</dd>'
            signals_html = ""
            for s in ad.get("analysis", {}).get("signals", []):
                signals_html += f"<li>{s}</li>"
            addendum_html = (
                '<div class="addendum">'
                '<h2 class="addendum-heading">BEHIND THE PANEL</h2>'
                f'<div class="addendum-note">{ad.get("author_note", "")}</div>'
                '<div class="addendum-section">'
                '<h3>GROUNDING</h3>'
                f'<p>{ad.get("grounding", {}).get("summary", "")}</p>'
                f'<dl class="addendum-citations">{citations_html}</dl>'
                '</div>'
                '<div class="addendum-section">'
                '<h3>WHAT\'S HAPPENING HERE</h3>'
                f'<p>{ad.get("analysis", {}).get("summary", "")}</p>'
                f'<ul class="addendum-signals">{signals_html}</ul>'
                f'<p class="addendum-access">{ad.get("analysis", {}).get("accessibility", "")}</p>'
                '</div>'
                '</div>'
            )
            # Use accessibility text as richer meta description
            access = ad.get("analysis", {}).get("accessibility", "")
            if access:
                meta_description = access[:155].rsplit(" ", 1)[0] + "..."
            print(f"  ✓ Addendum loaded → {addendum_path.name}")
        except Exception as e:
            print(f"  ⚠ Addendum error: {e}")

    friends = build_friends_html()

    def render_html(lang: str) -> str:
        return HTML_TEMPLATE.format(
            lang=lang,
            en_active=" active" if lang == "en" else "",
            es_active=" active" if lang == "es" else "",
            title=post["title"],
            title_js=post["title"].replace("'", "\\'"),
            description=description,
            description_js=description.replace("'", "\\'"),
            meta_description=meta_description,
            keywords_csv=keywords_csv,
            article_section=article_section,
            slug=slug,
            post_path=pp,
            site_url=SITE_URL,
            date=post["date"],
            tip_jar_url=TIP_JAR_URL,
            friends_html=friends,
            addendum_html=addendum_html,
            post_nav=post_nav.format(lang=lang) if post_nav else "",
        )

    # Generate /en/ and /es/ subdirectories
    for lang in ("en", "es"):
        lang_dir = post_dir / lang
        lang_dir.mkdir(exist_ok=True)
        (lang_dir / "index.html").write_text(render_html(lang))
        print(f"  ✓ HTML → {lang_dir}/index.html")

    # Root /thoughts/NNN/title/ → redirect to .../en/
    redirect_html = (
        '<!DOCTYPE html><html><head>'
        f'<meta charset="UTF-8">'
        f'<meta http-equiv="refresh" content="0;url=/{pp}/en/">'
        f'<link rel="canonical" href="{SITE_URL}/{pp}/en/">'
        f'<title>Redirecting...</title></head>'
        f'<body><a href="/{pp}/en/">Redirecting...</a></body></html>'
    )
    (post_dir / "index.html").write_text(redirect_html)
    cost.report(post.get("title", slug))
    return post, post_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="am-blog build engine")
    parser.add_argument("posts", nargs="*", help="Post JSON files (default: all in posts/)")
    parser.add_argument("--skip-generate", action="store_true", help="Skip Gemini generation (use existing panels)")
    parser.add_argument("--out", default="docs", help="Output directory")
    parser.add_argument("--deploy", action="store_true", help="Push to GitHub Pages after build")
    parser.add_argument("--include-future", action="store_true", help="Build HTML for future-dated posts too")
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

    # Edge mode: build ALL posts (future included), middleware gates access
    sorted_slugs = sorted(all_known.keys())
    all_slugs = sorted_slugs  # all posts for prev/next nav

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
        # Prev/next nav links to all posts — middleware returns 404 for future ones
        idx = all_slugs.index(slug) if slug in all_slugs else -1
        prev_meta = all_known.get(all_slugs[idx - 1]) if idx > 0 else None
        next_meta  = all_known.get(all_slugs[idx + 1]) if idx >= 0 and idx < len(all_slugs) - 1 else None
        print(f"\n▶ Building: {pf.name}")
        result = build_post(pf, skip_generate=args.skip_generate, out_dir=out_dir,
                            prev_meta=prev_meta, next_meta=next_meta)
        built.append(result)

    # Edge mode: generate manifest for edge functions (date filtering at request time)
    build_manifest(built, out_dir)
    write_robots_txt(out_dir)

    # Remove static index/sitemap/RSS/latest — edge functions handle these now
    for static_file in ["index.html", "sitemap.xml", "feed.xml", "latest.json"]:
        p = out_dir / static_file
        if p.exists():
            p.unlink()
            print(f"  🗑 Removed static {static_file} (replaced by edge function)")

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
