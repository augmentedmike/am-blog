# SEO Audit — blog.augmentedmike.com
**Ticket:** #147  
**Date:** 2026-02-25  
**Auditor:** AugmentedMike cron (automated)  
**Source:** https://blog.augmentedmike.com / ~/projects/am-blog/build.py

---

## Overall Score: PARTIAL

9 of 13 checklist items PASS. 4 items FAIL. Full detail below.

---

## Checklist Results

| Item | Status | Notes |
|---|---|---|
| Title per page | ✅ PASS | Index + post pages both set unique `<title>` |
| Meta description per page | ✅ PASS | Unique descriptions on index and post templates |
| Canonical | ✅ PASS | `<link rel="canonical">` present on both page types |
| HTML lang attribute | ✅ PASS | `<html lang="en">` on both templates (lines 365, 1003 in build.py) |
| og:title | ✅ PASS | Present on index and post pages |
| og:description | ✅ PASS | Present on index and post pages |
| og:image | ✅ PASS | thumb.jpg used on both; index uses latest post thumb |
| og:url | ✅ PASS | Correct canonical URL on both page types |
| Twitter card | ✅ PASS | `summary_large_image` on both page types |
| JSON-LD | ✅ PASS | `Blog` schema on index; `BlogPosting` on post pages |
| Single H1 per page | ❌ FAIL | **No `<h1>` found on index OR post pages** |
| Image alt text (panels) | ⚠️ PARTIAL | Thumbnail has alt=title; comic `page.png` has alt=title. But individual panel `<img>` tags inside the comic strip have no descriptive per-panel alt text |
| sitemap.xml | ✅ PASS | HTTP 200; well-formed XML with all posts listed and `<lastmod>` |
| robots.txt | ✅ PASS | HTTP 200; `Allow: /` + `Sitemap:` directive present |
| rss.xml | ❌ FAIL | **HTTP 404** — feed lives at `/feed.xml`, not `/rss.xml`. No redirect. |
| feed.xml valid | ✅ PASS | Valid RSS 2.0 with `atom:link self`, `<language>`, `<lastBuildDate>`, CDATA descriptions |
| Cross-link → bonsai-www | ❌ FAIL | Bonsai mentioned in post cards as text only — no `<a href="https://bonsai-www...">` hyperlink |
| Cross-link → miniclaw.bot | ❌ FAIL | MiniClaw mentioned in post cards as text only — no hyperlink to miniclaw.bot |

---

## P1 — Fix Immediately (Search ranking impact)

### P1-1: Missing H1 on all pages
**Impact:** Google uses H1 as the primary content signal. Missing H1 = ambiguous page topic = ranking penalty.  
**Index page:** Add a visually hidden or styled H1 above the post grid, e.g. `<h1 class="sr-only">AugmentedMike — AI Comic Blog</h1>` (or make the site logo/header text an H1).  
**Post pages:** The comic title should be wrapped in `<h1>`. In `build.py` around line 863 where `alt="{title}"` is set, add:
```html
<h1 class="post-title">{title}</h1>
```
(Can be visually styled or screen-reader only — but it must exist in the DOM.)

---

## P2 — Fix Soon (Crawl + discoverability gaps)

### P2-1: /rss.xml returns 404
**Impact:** Tools, podcatchers, and aggregators that guess `/rss.xml` will fail. The audit spec explicitly checks this URL.  
**Fix:** Add a redirect in the server config / Vercel `vercel.json`:
```json
{
  "redirects": [
    { "source": "/rss.xml", "destination": "/feed.xml", "permanent": true }
  ]
}
```
Or generate a static `/rss.xml` alongside `/feed.xml` in `build.py`.

### P2-2: Missing cross-links to bonsai-www and miniclaw.bot
**Impact:** Internal/ecosystem cross-linking is a known Google ranking signal. Posts 008 and 009 mention Bonsai and MiniClaw but the words are plain text in subtitle cards on the index — not linked.  
**Fix options:**
- In `build.py` index template, turn post-card subtitles into linked text when known brands appear.
- Add an "Ecosystem" section in the footer with explicit links: `<a href="https://bonsai-www.com">Bonsai</a>` · `<a href="https://miniclaw.bot">MiniClaw</a>`
- Add cross-link footer to post pages pointing to sister projects.

### P2-3: Panel-level alt text is generic
**Impact:** Google Images + accessibility. All comic panels use `alt="{title}"` (the post title). Individual panel `<img>` elements inside the comic strip carry no descriptive text.  
**Fix:** In `build.py`, if panels are stored as separate images, generate per-panel alt text from the panel caption/dialogue data in the JSON post files. If using a single `page.png` composite, add a `<figure>` with a `<figcaption>` describing the strip.

---

## P3 — Nice to Have

### P3-1: og:type on index is `website`, not `blog`
Acceptable, but `blog` would be more semantically correct. Low priority.

### P3-2: Sitemap index doesn't include /about/ or /press/
Static pages are missing from sitemap.xml. Low impact but good hygiene.
```xml
<url><loc>https://blog.augmentedmike.com/about/</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>
<url><loc>https://blog.augmentedmike.com/press/</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>
```

### P3-3: JSON-LD BlogPosting missing `image` property
The post JSON-LD has `headline` and `description` but the schema validator will warn without an `image` object. Add:
```json
"image": {
  "@type": "ImageObject",
  "url": "https://blog.augmentedmike.com/{slug}/thumb.jpg"
}
```

---

## Audit Exclusions

### Excluded from HTML meta description checks:
- `/llms.txt` — plain text file conforming to the [llms.txt standard](https://llmstxt.org/). HTML meta tags are not applicable to `.txt` files. The file already contains a descriptive summary on line 3: `> An AI that publishes a comic blog in real time.` Any automated SEO tool flagging this as a missing meta description is a **false positive** — exclude `.txt` files from HTML meta description audits.

---

## Summary

| Priority | Count | Items |
|---|---|---|
| P1 | 1 | Missing H1 (all pages) |
| P2 | 3 | /rss.xml 404, no cross-links, generic panel alt text |
| P3 | 3 | og:type, sitemap static pages, JSON-LD image |

**P1 is a 15-minute fix** — add one line per template in `build.py` and rebuild.  
**P2-1 (rss.xml redirect)** is a Vercel config change — 5 minutes.  
**P2-2 (cross-links)** requires design decision on where to place ecosystem links.
