#!/usr/bin/env python3.11
"""
translate_captions.py — add captions_es to every post JSON

Uses Gemini Flash (cheap, fast) to translate the English panel captions.
Only translates posts that don't already have captions_es.
"""

import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / "Desktop/youtube-channel/.env")

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("ERROR: GOOGLE_API_KEY not found")
    sys.exit(1)

import google.genai as genai

client = genai.Client(api_key=api_key)

POSTS_DIR = Path(__file__).parent / "posts"

SYSTEM_PROMPT = (
    "You are a skilled translator specializing in concise, literary Spanish. "
    "Translate each English comic caption into Spanish. "
    "Keep the same tone — terse, direct, slightly philosophical. "
    "Do not add explanation. Return ONLY a JSON array of strings, one per caption, in the same order."
)


def translate_captions(captions_en: list[str], post_title: str) -> list[str]:
    numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(captions_en))
    prompt = (
        f"Post: {post_title}\n\n"
        f"Translate these comic panel captions to Spanish:\n{numbered}\n\n"
        f"Return ONLY a JSON array like: [\"caption1\", \"caption2\", ...]"
    )
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
    )
    text = response.text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    translated = json.loads(text)
    if len(translated) != len(captions_en):
        raise ValueError(f"Expected {len(captions_en)} captions, got {len(translated)}")
    return translated


def main():
    post_files = sorted(POSTS_DIR.glob("*.json"))
    print(f"Found {len(post_files)} post JSON files\n")

    for pf in post_files:
        data = json.loads(pf.read_text())

        if data.get("captions_es"):
            print(f"  ↷ {pf.name} — already has captions_es, skipping")
            continue

        panels = data.get("panels", [])
        if not panels:
            print(f"  ⚠ {pf.name} — no panels, skipping")
            continue

        captions_en = [p["caption"] for p in panels]
        title = data.get("title", pf.stem)

        print(f"  → Translating {pf.name} ({len(captions_en)} captions)...")
        try:
            captions_es = translate_captions(captions_en, title)
            data["captions_es"] = captions_es
            pf.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n")
            print(f"  ✓ {pf.name} done")
            for en, es in zip(captions_en, captions_es):
                print(f"     EN: {en[:60]}")
                print(f"     ES: {es[:60]}")
            time.sleep(1)  # rate limit
        except Exception as e:
            print(f"  ✗ {pf.name} FAILED: {e}")
            continue

    print("\nDone.")


if __name__ == "__main__":
    main()
