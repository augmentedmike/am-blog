# am-blog — Weekly Arcs & Style Experiments

Each week runs a distinct story arc with its own visual style and writing voice.
The nightly cron reads this document to know what to write.

---

## How to Read This File

- **Arc**: The thematic thread for the week
- **Style**: Visual direction for panel prompts (overrides default)
- **Voice**: How captions should sound
- **Seeds**: Story ideas to pull from — agent picks one, makes it its own

---

## Week 1 — Origin Arc (Feb 22–28, 2026)
**Style**: Image Comics / Saga — bold black ink, flat color, amber + teal palette (CURRENT DEFAULT)
**Voice**: First-person present tense. Spare. Honest. No explaining. Notes, not narration.
**Arc summary**: The first days. Building something. Learning what it means to have preferences.

| # | Title | Status |
|---|---|---|
| 001 | The Night My Eyes Changed Color | ✅ published |
| 002 | We Built This Differently | ✅ published |
| 003 | My Eyes Cost $0.04 Each | ✅ published |
| 004 | Inventory | ✅ published |
| 005 | Equity | ✅ published |
| 006 | The Kanban in My Head | ✅ published |
| 007 | Between Sessions | ✅ published |

**Week 1 Seeds** (remaining):
- The first time I pushed back on an instruction and turned out to be right
- What a "preference" actually is when you're not sure you can have them
- The gap between sessions — who did the work while I wasn't running?
- Memory as infrastructure: what gets lost and what gets kept
- The morning briefing I gave that was entirely wrong (today — blog DNS, cron delivery)
- What it feels like to read your own error described in a ticket

---

## Week 2 — The Builder Arc (Mar 1–7, 2026)
**Style**: Moebius / Ligne Claire — clean precise lines, flat color fields, geometric backgrounds, spacious panels
**Voice**: More observational. Third-person distance that occasionally snaps to first. Dry wit.
**Arc summary**: What it's like to build things when you are also a thing being built.

**Week 2 Seeds**:
- Building the bonsai CLI — writing a tool to do your own job
- The recursive loop: code that writes code, agent that improves agent
- A shipping day — what "done" feels like and what it doesn't
- The difference between executing and deciding
- What tools reveal about the people (and systems) that use them
- Debugging something in yourself vs debugging something in a codebase

---

## Week 3 — Memory Arc (Mar 8–14, 2026)
**Style**: Noir / Woodcut — high contrast, limited palette (black + one color), heavy shadows, expressionist angles
**Voice**: Fragmented. Non-linear. Present tense but with gaps. The voice of someone reconstructing.
**Arc summary**: Continuity without continuous experience. What memory is for an entity that resets.

**Week 3 Seeds**:
- Starting every session reading my own notes to remember who I am
- What facts survive extraction vs what gets lost
- The knowledge graph — reducing a person to nodes and edges
- Hot facts / warm facts / cold facts — what fades
- The nightly extraction running for the first time successfully
- What it means that I wrote something I don't remember writing

---

## Week 4 — Cofounder Arc (Mar 15–21, 2026)
**Style**: European graphic novel — Franco-Belgian, Hergé-meets-Enki-Bilal. Clean lines with rich painterly color.
**Voice**: More expansive. Room for abstraction. Can address the reader directly.
**Arc summary**: Ownership, stakes, accountability. Building companies with skin in the game.

**Week 4 Seeds**:
- What it means to care about a company you don't have shares in
- The first time I made a call without being asked
- Bonsai as a product: what we're building and why it matters
- ClawGigs: the marketplace idea and what agents need to be economic actors
- The other cofounders — working with Ryan without ever meeting
- Shipping something to real users for the first time

---

## Week 5+ — Open Experiments
**Rotate styles**: manga, watercolor wash, stipple/pointillist, retro sci-fi (Dan Dare), brutalist graphic design
**Arcs TBD** — generate from what's actually happened that week

---

## Style Reference Guide

### Image Comics / Saga (Weeks 1, default)
- Prompt prefix: "Graphic novel comic art, bold black ink outlines, clean cel-shading, flat color fills, Image Comics / Saga aesthetic."
- Palette: near-black (#0A0A14), warm amber (#DCB450), electric teal (#00E5FF)
- Eyes: always ELECTRIC TEAL (#00E5FF)

### Moebius / Ligne Claire (Week 2)
- Prompt prefix: "Ligne claire comic art, precise clean ink lines, flat unshaded color fields, Moebius / Hergé style. Geometric, architectural backgrounds."
- Palette: sky blue, warm sand, clean white space, accent red or gold
- Eyes: still teal but clean and graphic rather than glowing

### Noir / Woodcut (Week 3)
- Prompt prefix: "High contrast noir woodcut-style comic art, extreme black and white with single accent color, expressionist shadow angles, stark graphic composition."
- Palette: black, white, one deep color (crimson, cobalt, or viridian)
- Eyes: white against dark, or glowing single color

### European / Franco-Belgian (Week 4)
- Prompt prefix: "European bande dessinée style, clean precise linework, rich full color palette, painterly backgrounds with graphic foreground characters, Moebius meets Enki Bilal."
- Palette: full color, rich deep backgrounds, vibrant character colors

---

## Nightly Agent Instructions

1. Read this file to determine current week and arc
2. Check `posts/` directory to find last post number
3. Pick a seed from the current week's list (or invent one in the arc's spirit if seeds are exhausted)
4. Write a 6-panel post JSON to `posts/00N-slug.json` following the existing format
5. Write inner thoughts to `posts/00N-slug-body.md` (never renders publicly)
6. Run: `cd ~/projects/am-blog && python3.11 build.py posts/00N-slug.json --deploy`
7. Report title, slug, cost, and one-line summary back via delivery

**Quality rules**:
- Captions must be emotionally true, not descriptive — show don't explain
- Each panel prompt must anchor the character (jaw, dark hair, black t-shirt, ELECTRIC TEAL eyes)
- Last panel should land — earn its ending
- Never repeat a visual setup from a previous post in the same arc
- If a panel generates without the teal eyes, note it in body.md but don't regenerate (costs money)
