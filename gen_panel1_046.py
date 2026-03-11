#!/usr/bin/env python3
"""
3-step panel generation for post 046, panel 1 (dry run).

Step 1: Generate base panel WITH empty caption box baked into the art
Step 2: Feed base back as reference → Gemini fills in EN text
Step 3: Feed base back as reference → Gemini fills in ES text
"""
import io, os, sys, base64, subprocess
from pathlib import Path

# Gemini setup (same as build.py)
import google.genai as genai
from google.genai import types

r = subprocess.run(["mc", "vault", "export", "gemini-api-key"], capture_output=True, text=True)
api_key = r.stdout.strip() or os.getenv("GOOGLE_API_KEY", "")
if not api_key:
    print("No Gemini API key"); sys.exit(1)
client = genai.Client(api_key=api_key)

OUT_DIR = Path("docs/thoughts/046/the-unseen")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Character ref
REF_PATH = Path("character-reference/amelia-neutral.jpg")
ref_bytes = REF_PATH.read_bytes()
ref_part = types.Part.from_bytes(data=ref_bytes, mime_type="image/jpeg")

def text_part(t):
    return types.Part.from_text(text=t)

def img_part(raw):
    return types.Part.from_bytes(data=raw, mime_type="image/png")

# --------------------------------------------------------------------------
# Captions (for sizing the box — ES is longer)
# --------------------------------------------------------------------------
CAPTION_EN = "Am's journal, March 4. Twenty-seven posts in the archive. No panels. The key expired and the work piled up invisible."
CAPTION_ES = "Diario de Am, 4 de marzo. Veintisiete publicaciones en el archivo. Sin paneles. La clave expiró y el trabajo se acumuló invisible."

# --------------------------------------------------------------------------
# STEP 1: Generate base panel with empty caption box
# --------------------------------------------------------------------------
STEP1_PROMPT = f"""Generate a single wide-format comic panel (landscape, roughly 1550x860 pixels).

CHARACTER (must appear):
The character is female, late 20s, sharp elegant features, strong cheekbones, short dark bob, olive-tan skin, black crew-neck t-shirt. Her eyes glow ELECTRIC TEAL (#00E5FF) — this is always visible, distinctive, unmistakable. This exact character must appear in this panel.

SCENE:
Watchmen-style high contrast noir comic art, Dave Gibbons aesthetic. Stark geometric composition. Limited palette: near-black, deep amber, and electric blue.

Opening establishing shot — wide cinematic frame. The character sits at a terminal in a dark room, body positioned in the RIGHT HALF of the frame. He faces slightly left, leaning into the keyboard. The amber glow of the monitor illuminates his face and hands. On the screen: rows of filenames with dates, a file listing — some rows missing data in one column. The posture of someone cataloguing invisible work. Behind him: dark geometric shapes suggesting server racks or shelving, receding into shadow. A single overhead practical light casts a hard cone of amber onto the desk surface.

The LEFT side of the frame has breathing room — dark wall, shadow, negative space. This is where the caption will go.

EMPTY CAPTION BOX (critical — draw this as part of the art):
In the TOP-LEFT corner of the panel, draw a solid rectangular caption box. It floats about 20 pixels from the top edge and 20 pixels from the left edge. The box is approximately 480 pixels wide and 130 pixels tall (sized to hold 3 lines of small comic caption text — roughly 130 characters).

The box has:
- Solid near-black fill (#04081A) — fully opaque, not transparent
- A thin 2-pixel electric teal (#00E5FF) border on all four sides
- A 6-pixel solid electric teal (#00E5FF) accent stripe running vertically along the LEFT inner edge of the box
- The interior is EMPTY — absolutely NO text inside. Just the dark fill, the teal border, and the teal left accent stripe.

The box should look like a professional comic caption box waiting for lettering — clean, geometric, part of the panel composition.

STYLE:
Watchmen / Dave Gibbons noir aesthetic. High contrast. Heavy shadow. Stark geometric gutters. Limited palette (black + deep amber + electric blue). Bold black ink outlines. Dense cross-hatching in shadows. Electric teal only on eyes and the caption box accent.

No photorealism. No watermarks. No text anywhere in the image. No speech bubbles. No panel borders around the outer edge.

IMPORTANT: Today's date is March 10, 2026. Any dates shown in the art must be consistent with early March 2026."""

print("=" * 60)
print("STEP 1: Generating base panel with empty caption box...")
print("=" * 60)

config1 = types.GenerateContentConfig(seed=42012)  # rorschach seed
resp1 = client.models.generate_content(
    model="gemini-3-pro-image-preview",
    contents=[ref_part, text_part(STEP1_PROMPT)],
    config=config1,
)

base_path = OUT_DIR / "panel1-base-with-box.png"
base_bytes = None
for part in resp1.candidates[0].content.parts:
    if hasattr(part, 'inline_data') and part.inline_data:
        raw = part.inline_data.data
        if isinstance(raw, str):
            raw = base64.b64decode(raw)
        base_bytes = raw
        with open(base_path, "wb") as f:
            f.write(raw)
        print(f"  ✓ Base panel saved → {base_path}")
        break

if not base_bytes:
    print("  [!] No image in response for step 1")
    # Print text parts for debugging
    for part in resp1.candidates[0].content.parts:
        if hasattr(part, 'text') and part.text:
            print(f"  Text: {part.text[:500]}")
    sys.exit(1)

base_part = img_part(base_bytes)

# --------------------------------------------------------------------------
# STEP 2: Fill in EN caption text
# --------------------------------------------------------------------------
STEP2_PROMPT = f"""This is a comic panel with an empty caption box in the top-left corner. The box has a near-black fill, teal border, and teal left accent stripe.

Fill in the caption box with the following English text, using bold condensed white lettering:

"{CAPTION_EN.upper()}"

LETTERING RULES:
- Font: bold condensed sans-serif (like Impact or League Gothic), ALL CAPS
- Color: pure white (#FFFFFF)
- Text sits inside the box, to the right of the teal accent stripe
- Generous padding from all box edges (at least 10px)
- Text wraps naturally across 2-3 lines to fill the box width
- Text must be fully legible and crisp
- DO NOT change ANY of the panel artwork outside the caption box
- DO NOT change the box itself — keep its fill, border, and accent exactly as they are
- ONLY add white text inside the existing box"""

print("\n" + "=" * 60)
print("STEP 2: Adding EN caption text...")
print("=" * 60)

config2 = types.GenerateContentConfig(seed=42012)
resp2 = client.models.generate_content(
    model="gemini-3-pro-image-preview",
    contents=[base_part, text_part(STEP2_PROMPT)],
    config=config2,
)

en_path = OUT_DIR / "test-panel1-captioned.png"
for part in resp2.candidates[0].content.parts:
    if hasattr(part, 'inline_data') and part.inline_data:
        raw = part.inline_data.data
        if isinstance(raw, str):
            raw = base64.b64decode(raw)
        with open(en_path, "wb") as f:
            f.write(raw)
        print(f"  ✓ EN captioned panel saved → {en_path}")
        break
else:
    print("  [!] No image in response for step 2")
    for part in resp2.candidates[0].content.parts:
        if hasattr(part, 'text') and part.text:
            print(f"  Text: {part.text[:500]}")

# --------------------------------------------------------------------------
# STEP 3: Fill in ES caption text (from same base)
# --------------------------------------------------------------------------
STEP3_PROMPT = f"""This is a comic panel with an empty caption box in the top-left corner. The box has a near-black fill, teal border, and teal left accent stripe.

Fill in the caption box with the following Spanish text, using bold condensed white lettering:

"{CAPTION_ES.upper()}"

LETTERING RULES:
- Font: bold condensed sans-serif (like Impact or League Gothic), ALL CAPS
- Color: pure white (#FFFFFF)
- Text sits inside the box, to the right of the teal accent stripe
- Generous padding from all box edges (at least 10px)
- Text wraps naturally across 2-3 lines to fill the box width
- Text must be fully legible and crisp
- DO NOT change ANY of the panel artwork outside the caption box
- DO NOT change the box itself — keep its fill, border, and accent exactly as they are
- ONLY add white text inside the existing box"""

print("\n" + "=" * 60)
print("STEP 3: Adding ES caption text...")
print("=" * 60)

config3 = types.GenerateContentConfig(seed=42012)
resp3 = client.models.generate_content(
    model="gemini-3-pro-image-preview",
    contents=[base_part, text_part(STEP3_PROMPT)],
    config=config3,
)

es_path = OUT_DIR / "test-panel1-captioned-es.png"
for part in resp3.candidates[0].content.parts:
    if hasattr(part, 'inline_data') and part.inline_data:
        raw = part.inline_data.data
        if isinstance(raw, str):
            raw = base64.b64decode(raw)
        with open(es_path, "wb") as f:
            f.write(raw)
        print(f"  ✓ ES captioned panel saved → {es_path}")
        break
else:
    print("  [!] No image in response for step 3")
    for part in resp3.candidates[0].content.parts:
        if hasattr(part, 'text') and part.text:
            print(f"  Text: {part.text[:500]}")

print("\n" + "=" * 60)
print("DONE. Check:")
print(f"  Base:  http://localhost:4201/thoughts/046/the-unseen/panel1-base-with-box.png")
print(f"  EN:    http://localhost:4201/thoughts/046/the-unseen/test-panel1-captioned.png")
print(f"  ES:    http://localhost:4201/thoughts/046/the-unseen/test-panel1-captioned-es.png")
print("=" * 60)
