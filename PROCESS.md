# Blog Post Process — AugmentedMike

Every post follows this exact sequence. Do not skip steps.

## 1. Seed (T-5 days before publish date)
- File: `seeds/YYYY-MM-DD-seed.md`
- Contains: slug, title, subtitle, arc, style, full panel breakdown, emotional arc, notes
- Created by: nightly-blog-post cron or manual

## 2. Post JSON (T-5 days)
- File: `posts/NNN-slug.json`
- Fields: id, slug, date, title, subtitle, arc, style, panels (array of 6)
- Each panel: id, caption, caption_es, image_prompt
- Character anchor in every image_prompt: "strong jaw, dark tousled hair, black t-shirt, electric teal #00E5FF glowing eyes"

## 3. Panel Generation
- Command: `python3.11 build.py posts/NNN-slug.json`
- Output: `docs/NNN-slug/panels/panel_0N.png` (6 panels)
- Run in tmux background session: `tmux new-session -d -s blog-NNN "python3.11 build.py posts/NNN-slug.json >> /tmp/blog-NNN.log 2>&1"`

## 4. Push to GitHub
- Use `gh api` (git push is broken):
  ```bash
  python3.11 scripts/push_panels.py NNN-slug
  ```
- Or manually via gh api PUT for each panel file

## 5. Addendum
- File: `~/.miniclaw/user/personas/augmented-mike/creative/addendums/NNN-slug-addendum.json`
- Fields: post_id, slug, title, date, arc, theme, emotional_core, captions_analysis (per panel), arc_position, connection_forward, connection_backward, style_notes, generated_date
- Written BEFORE publish date, ideally same day as panel generation

## 6. Index Rebuild (publish date, midnight CST)
- Cron: `daily-blog-index-unlock` runs at 00:01 CST
- Rebuilds `docs/index.html` with all posts whose date <= today
- Pushes index.html to GitHub via gh api

## Checklist Per Post
- [ ] Seed file exists (T-5)
- [ ] Post JSON written (T-5)
- [ ] 6 panels generated on disk
- [ ] Panels pushed to GitHub
- [ ] Addendum written
- [ ] Index includes post on publish date

## 7. Substack Cross-Post (same day as publish)
- Command: `python3 post.py substack NNN` (or `python3 post.py substack <slug>`)
- Targets: **Inner Thoughts** Substack (`inner-thoughts.substack.com`)
- Schedule: auto-set to blog publish date + 7 days at 08:00 CT
- Requires: `substack-sid-inner-thoughts` session cookie stored in vault:
  ```bash
  mc mc-substack auth --publication inner-thoughts
  ```
- Verify draft at: `https://inner-thoughts.substack.com/publish`

## Substack Publications
| Name | Subdomain | Vault Key | Purpose |
|------|-----------|-----------|---------|
| default | augmentedmike | substack-sid | Consulting/main account |
| inner-thoughts | inner-thoughts | substack-sid-inner-thoughts | Comic cross-posts |

To authenticate Inner Thoughts:
```bash
mc mc-substack auth --publication inner-thoughts
```
To manually post a comic to Inner Thoughts:
```bash
mc mc-substack post-comic --publication inner-thoughts \
  --title "EP.001 — Title" --subtitle "Subtitle" \
  --image "https://blog.augmentedmike.com/..." \
  --blog-url "https://blog.augmentedmike.com/..." \
  --blog-date "2026-03-07" --ep "001"
```

## Common Failures
- `nightly-blog-post` cron errors → check /tmp/blog-*.log, usually Gemini API or gh push issue
- Panels missing → run build.py manually, check Gemini API key
- Index not updating → run daily-blog-index-unlock cron manually
- better-sqlite3 error → cd ~/.miniclaw/system/lib && npm rebuild better-sqlite3
- Substack auth expired → re-run `mc mc-substack auth --publication inner-thoughts`
