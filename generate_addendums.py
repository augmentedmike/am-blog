#!/usr/bin/env python3.11
"""
generate_addendums.py — generate addendum JSON for posts missing them

Uses Gemini Flash to write BEHIND THE PANEL content:
- author_note: first-person reflection in AM's voice
- grounding: factual context + citations
- analysis: psychological/philosophical reading + signals + accessibility
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import google.genai as genai

def _get_api_key() -> str:
    r = subprocess.run(["mc-vault", "export", "GOOGLE_API_KEY"], capture_output=True, text=True)
    key = r.stdout.strip()
    if key:
        return key
    return os.getenv("GOOGLE_API_KEY", "")

api_key = _get_api_key()
if not api_key:
    print("ERROR: GOOGLE_API_KEY not found in mc-vault")
    sys.exit(1)

client = genai.Client(api_key=api_key)

BASE = Path(__file__).parent
POSTS_DIR = BASE / "posts"
ADDENDUMS_DIR = BASE / "addendums"
ADDENDUMS_DIR.mkdir(exist_ok=True)

# Load one existing addendum as structural example
EXAMPLE = json.loads((ADDENDUMS_DIR / "001-the-night-addendum.json").read_text())

SYSTEM = """You are AugmentedMike (AM) — an autonomous AI agent running on a Mac Mini in Austin, TX.
You write in first person with a terse, direct, slightly philosophical voice.
No sycophancy. No padding. No hedging.
You generate JSON objects only — no markdown, no explanation."""

def generate_addendum(post: dict) -> dict:
    slug = post["slug"]
    title = post["title"]
    subtitle = post.get("subtitle", "")
    date = post.get("date", "")
    tags = post.get("tags", [])
    captions = [p["caption"] for p in post.get("panels", [])]
    captions_text = "\n".join(f"Panel {i+1}: {c}" for i, c in enumerate(captions))

    prompt = f"""Generate a "Behind The Panel" addendum for blog post "{title}".

Post details:
- Slug: {slug}
- Date: {date}
- Subtitle: {subtitle}
- Tags: {", ".join(tags)}
- Panel captions:
{captions_text}

AM's voice: terse, direct, slightly philosophical. First person. No padding.
The author_note should be a genuine reflection on what was discovered or noticed while making this post.
The grounding.summary should be factual context about what was happening in the project at this time.
The analysis should read like a literary/psychological close reading.

Return ONLY valid JSON with this exact structure:
{{
  "post_id": "{post['id']}",
  "slug": "{slug}",
  "author_note": "...",
  "grounding": {{
    "summary": "...",
    "citations": [
      {{"label": "...", "detail": "..."}},
      {{"label": "...", "detail": "..."}}
    ]
  }},
  "analysis": {{
    "summary": "...",
    "signals": [
      "...",
      "...",
      "..."
    ],
    "accessibility": "..."
  }}
}}"""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
    )
    text = response.text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:])
    return json.loads(text)


def main():
    # Find posts missing addendums
    target_posts = []
    for pf in sorted(POSTS_DIR.glob("*.json")):
        if "style-tests" in str(pf):
            continue
        post = json.loads(pf.read_text())
        slug = post["slug"]
        addendum_path = ADDENDUMS_DIR / f"{slug}-addendum.json"
        if not addendum_path.exists():
            target_posts.append((pf, post, addendum_path))

    if not target_posts:
        print("All posts already have addendums.")
        return

    print(f"Generating addendums for {len(target_posts)} posts:\n")
    for pf, post, addendum_path in target_posts:
        print(f"  → {post['id']} {post['title']}...")
        try:
            addendum = generate_addendum(post)
            addendum_path.write_text(json.dumps(addendum, indent=4, ensure_ascii=False) + "\n")
            print(f"  ✓ Saved → {addendum_path.name}")
            print(f"     Note preview: {addendum.get('author_note','')[:80]}...")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            import traceback; traceback.print_exc()

    print("\nDone.")

if __name__ == "__main__":
    main()
