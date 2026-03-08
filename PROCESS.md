# Blog Post Process — AugmentedMike

Every post follows this exact sequence. Do not skip steps.

## 1. Seed (T-5 days before publish date)
- File: `seeds/YYYY-MM-DD-seed.md`
- Contains: slug, title, subtitle, arc, style, full panel breakdown, emotional arc, notes
- Created by: nightly-blog-post cron or manual

## 2. Post JSON (T-5 days)
- File: `posts/NNN-slug.json`
- Fields: id, slug, seo_slug, date, title, subtitle, arc, style, layout, panels (array of 6), captions_es
- Each panel: id, caption (EN), prompt
- Style must be an arc key: `arc1`, `arc2`, `arc3`, `arc4` (see ARCS.md)
- Do NOT set `character_anchor` unless the post intentionally uses a non-default character for ALL panels

## 3. Panel Generation (EN + ES, same art)

### How it works

Base art is generated ONCE per panel using Gemini with a fixed seed per arc.
EN and ES captions are then applied separately via `mc mc-designer edit` on
the same base images. This guarantees identical art between languages.

**Never call Gemini twice for the same panel** — different calls = different art.

```
panels/         ← base art, no captions (Gemini, seeded)
panels_en/      ← base art + EN caption bar (mc-designer edit)
panels_es/      ← base art + ES caption bar (mc-designer edit, same base)
```

### Arc seeds (defined in ARC_SEEDS in build.py)
| Style  | Seed  |
|--------|-------|
| arc1   | 42001 |
| arc2   | 42002 |
| arc3   | 42003 |
| arc4   | 42004 |

### Commands

Full build (generates all panels + captions + pages + HTML):
```bash
python3 post.py build NNN --regen
```

Rebuild captions only (keep existing base panels):
```bash
rm -rf docs/thoughts/NNN/slug/panels_en docs/thoughts/NNN/slug/panels_es
python3 post.py build NNN
```

Rebuild pages + HTML only (keep existing captioned panels):
```bash
python3 post.py build NNN --skip-generate
```

Run in background:
```bash
python3 post.py build NNN --regen 2>&1 | tee /tmp/blog-NNN.log &
```

## 4. Review
- Copy to .68 desktop:
  ```bash
  scp docs/thoughts/NNN/slug/page_en.jpg michaeloneal@192.168.1.68:~/Desktop/NNN-slug_en.jpg
  scp docs/thoughts/NNN/slug/page_es.jpg michaeloneal@192.168.1.68:~/Desktop/NNN-slug_es.jpg
  ```
- Check: panels 1-4 character, panels 5-6 character, captions visible, ES captions are Spanish

## 5. Publish
```bash
python3 post.py publish NNN
```
Commits docs/, pushes to GitHub → deploys to Vercel.

## 6. Addendum
- Generated automatically during build
- File: `addendums/NNN-slug-addendum.json`

## 7. Substack Cross-Post (publish date + 7 days)
```bash
python3 post.py substack NNN
```
- Publication: **Inner Thoughts** (`inner-thoughts.substack.com`)
- Auto-scheduled to publish date + 7 days at 08:00 CT
- Auth: `mc mc-substack auth --publication inner-thoughts`

## Checklist Per Post
- [ ] Post JSON written with correct arc style and captions_es
- [ ] Base panels generated (panels/)
- [ ] EN caption panels generated (panels_en/)
- [ ] ES caption panels generated (panels_es/)
- [ ] EN and ES pages reviewed on .68 desktop
- [ ] Post published (git push → Vercel)
- [ ] Substack draft scheduled

## Common Failures
- Art differs between EN/ES → panels_en/panels_es were generated from separate Gemini calls. Delete both and rebuild with `--skip-generate` (keeps base panels).
- No captions visible → mc-designer edit failed; check canvas dimensions match panel. Run `apply_caption_mc_designer` debug manually.
- Gemini API key → uses `mc-vault export GOOGLE_API_KEY`. Run `mc-vault export GOOGLE_API_KEY` to verify.
- Substack auth expired → `mc mc-substack auth --publication inner-thoughts`
- Index not updating → run daily-blog-index-unlock cron manually
