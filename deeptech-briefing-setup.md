# Deep-Tech Daily Briefing — Setup Guide

Goal: a weekday morning brief that surfaces *problems, funding, and technical breakthroughs* in manufacturing, energy, and space — oriented toward finding a company to start, not toward staying informed.

Two tasks, different cadences:
- **Daily (weekday mornings)** — trade press + government solicitations. Fast-moving, deadline-driven.
- **Weekly (Sunday)** — arXiv, VC theses, Stanford TechFinder, department seminars. Slower signal, would drown you daily.

Total setup: about 45 minutes. Steps 1–5 are the daily brief. Step 6 is the weekly. Step 7 is the Stanford layer.

---

## Step 1 — Create a dedicated inbox (5 min)

Several of the highest-signal sources are email-only. Don't try to scrape them.

Make a new Gmail — something like `yourname.intel@gmail.com` — and subscribe there to:

| Source | Where | Why |
|---|---|---|
| Volts | volts.wtf | David Roberts, deep energy |
| CTVC (Sightline Climate) | ctvc.co | Weekly climate-tech deals — your funding backbone |
| Space Capital "Space IQ" | spacecapital.com/space-iq | Quarterly space investment data |
| DOE Loan Programs / Energy Dominance Financing | energy.gov/edf | Monthly, GovDelivery |
| Eclipse Ventures | eclipse.vc | Industrial-tech thesis |
| Payload | payloadspace.com | Also has RSS, but email is more reliable |
| SBIR/STTR newsletter | share.hsforms.com/1x9GR73-zTrGq021OvemHVApv9kv | Solicitation announcements — the reliable route while their API is down |
| Grants.gov opportunity alerts | grants.gov/connect/manage-subscriptions | Daily new-opportunity digest, or saved searches on your keywords. Their RSS feeds are broken, so this is the working route |

Not on this list, despite my earlier suggestion: **Lux Capital**. Their newsletter is Riskgaming (blog.riskgaming.com), a Substack about the design and policy tradeoffs of their wargaming scenarios — interesting, but a step removed from deep-tech company-building. It has an RSS feed, so it's in the OPML as optional weekly reading rather than a daily email. For Lux specifically, luxcapital.com/news and Josh Wolfe's quarterly LP letters are the thing worth reading. Also note *Lux Research* (luxresearchinc.com) is an unrelated company spun off in 2017.

Then connect that Gmail as a connector in Claude so the scheduled task can read it. Keep it separate from your real inbox — you want the agent scoped to this and nothing else.

---

## Step 2 — Get your API keys (10 min)

Only one requires registration.

**SBIR.gov** — ⚠️ **The API is currently down.** SBIR.gov's own API docs page carries a maintenance notice directing people to their helpdesk (sba.sbir.support@decisionpointcorp.com, Mon–Fri 9–5 ET). Don't build against `api.www.sbir.gov` until that clears.

Use these instead, in priority order:

1. **Topics page — the main workaround.** https://www.sbir.gov/topics lists Open, Future, and Closed topics, filterable, with CSV export (10,000 records per download). Topics are *more* granular than solicitations — each one is a specific technology area with a description of the problem. This is the single densest list of funded-but-unsolved technical problems you'll find. Point the agent at this page directly; no API needed.

2. **SBIR newsletter.** Sign up at https://share.hsforms.com/1x9GR73-zTrGq021OvemHVApv9kv and add it to the intel Gmail from Step 1. Push instead of pull.

3. **Legacy API endpoint**, which may still respond: `https://legacy.www.sbir.gov/api/solicitations.json?keyword=manufacturing`. Test it before relying on it — it's the old system and could go away.

4. **Bulk award data**, if you ever want to analyze historical patterns: `https://data.www.sbir.gov/awarddatapublic/award_data.csv` (290 MB, with abstracts) or the no-abstract version (65 MB). Not for daily use, but a good one-time pull to see who has been winning what in your domains.

Retest the main API in a few weeks. When it comes back the endpoint is `https://api.www.sbir.gov/public/api/solicitations?keyword=<term>` (JSON default, `?format=xml` for XML).

**Grants.gov** — no key. ⚠️ **Their RSS feeds are broken.** All four `/rss/*.xml` URLs (including the one their own documentation tells you to use) now return the site's HTML shell rather than XML — they migrated to a JavaScript app and the RSS paths were never repointed. Don't bother with them.

Use instead:

1. **The search2 API** — this is the real answer, and it's better than RSS was. No auth required; Grants.gov's own API guide confirms authentication is not needed for this endpoint.

   **It is POST-only.** Opening the URL in a browser sends a GET and returns `{"message":"Missing Authentication Token"}` — that's AWS API Gateway's stock response for a route mismatch, not an actual auth problem. Misleading error string, working endpoint. Test it from a terminal instead:

   ```bash
   curl --location 'https://api.grants.gov/v1/api/search2' \
     --header 'Content-Type: application/json' \
     --data '{"keyword": "energy storage", "oppStatuses": "posted", "rows": 25}'
   ```

   Useful parameters: `keyword` (singular), `agencies`, `oppStatuses` (`posted`, `forecasted`, `closed`, `archived`), `fundingCategories`, `aln`, plus `rows` and `startRecord` for paging. Results come back under `data.oppHits`, with `hitCount` and `startRecord` for pagination.

2. **Email subscriptions** — https://grants.gov/connect/manage-subscriptions. Subscribe "All New Opportunities" for a daily digest, or set up saved searches on your keywords and get notified only on matches. Route to the intel Gmail from Step 1. This is the zero-effort option and probably what you should start with.

3. **XML Extract** — https://grants.gov/xml-extract publishes a bulk daily XML of every posted opportunity. Overkill for a morning brief, useful if you later want to do your own filtering or historical analysis.

**SAM.gov** — needed for DARPA BAAs and defense contract opportunities. Register at sam.gov, request an API key from your account page. Endpoint:
```
https://api.sam.gov/prod/opportunities/v2/search
```
Unregistered/public keys are throttled to roughly 10 requests/day. Register an entity for real limits. If you skip this, you lose DARPA visibility but keep everything else — fine to defer.

---

## Step 3 — RSS feeds: done, here's what changed

All 16 daily-tier feeds (Space, Energy, Manufacturing and Industrial) have been checked directly. Results:

**12 confirmed correct, live, current** — Payload, SpaceNews, NASASpaceflight, Heatmap News, Latitude Media, Utility Dive, Volts, Construction Physics, Semianalysis, IEEE Spectrum Robotics, IEEE Spectrum Semiconductors, Manufacturing Dive.

**3 had real errors, now fixed in `deeptech-feeds.opml`:**
- **Ars Technica** — the path was wrong (`/science/space/feed/` instead of `/space/feed/`). Corrected, but this site blocks the tool I checked feeds with, so I confirmed the right path via third-party RSS directories rather than by reading the feed's actual content directly. Worth a manual glance the first time it runs.
- **Canary Media** — path was wrong (`/rss` instead of `/rss.rss`). Confirmed working with live content.
- **The Prepared** — this one was a real mess. The domain I had (`theprepared.org`) is dead, and the similar `theprepared.com` turned out to be an unrelated disaster-preparedness site, not Spencer Wright's manufacturing newsletter. Wright renamed the whole publication to **Scope of Work** back in December 2022 — I was working from information that predated the rename. New feed: `scopeofwork.net/rss/`. I've confirmed the platform (Ghost 6.61, which always serves RSS at that exact path) but couldn't independently pull the feed's actual content to verify — same site-blocking issue as Ars Technica.

**1 removed entirely** — The Orbital Index stopped regular publication on January 7, 2026. The operators said future posts would be "sporadic" on a new Substack, which doesn't fit a daily brief. Dropped rather than replaced.

**Still unverified** (weekly-tier, not used by the daily script, lower priority): Works in Progress, The Diff, Riskgaming.

If you want to double check the two site-blocked ones yourself, `check_feeds.py` still works for that — run it from a machine that isn't blocked:
```bash
pip install feedparser requests
python check_feeds.py deeptech-feeds.opml
```

---

## Step 4 — Create the daily scheduled task (10 min)

Open Claude Cowork → Scheduled tasks → new task. Cadence: **weekdays**, time: whenever you actually read things (7:00 AM if you read before lab, 8:30 if after).

Paste this as the task:

```
Every weekday, produce my deep-tech opportunity brief.

STEP 1 — Read memory
Open deeptech-memory.md. Note everything already covered. Skip repeats
unless there is a material update (new number, reversal, new party involved).

STEP 2 — Gather
Check the last 24 hours from these sources:

SPACE: Payload, SpaceNews, Ars Technica space section (Rocket Report),
NASASpaceflight, The Orbital Index
ENERGY: Heatmap AM, Latitude Media, Canary Media, Utility Dive
MANUFACTURING: Construction Physics, The Prepared, Semianalysis,
IEEE Spectrum (robotics + semiconductors), Manufacturing Dive
INBOX: check the connected intel Gmail for new newsletter issues

Then check for new funding opportunities:
- https://www.sbir.gov/topics — filter to Open topics, look for anything
  matching: manufacturing, propulsion, energy storage, grid, materials,
  thermal, in-space, robotics, sensors. Report the topic title, agency,
  close date, and the actual technical problem stated in the topic
  description. (Note: the SBIR API is down for maintenance — read the
  Topics page directly rather than calling api.www.sbir.gov.)
- Grants.gov for new DOE, NASA, DOD, and NSF opportunities. Their RSS
  feeds are broken — check the subscription emails in the intel Gmail,
  or query the API: POST (not GET) to
  https://api.grants.gov/v1/api/search2 with Content-Type:
  application/json and a body like
  {"keyword": "<term>", "oppStatuses": "posted"}
  Results are under data.oppHits.

STEP 3 — Output
Five sections. Every item gets a source link and one line of founder
implication. If a section has nothing real today, write "nothing
significant" — do not pad, do not summarize old news to fill space.

## PROBLEMS SURFACED
Specific technical or operational pain someone stated out loud. Quote the
problem, not the article's framing. This is the most important section.

## FUNDING SIGNALS
New rounds, FOAs, solicitations, government awards. Who got money, for
what, how much, from whom. Include SBIR/Grants.gov hits here with
deadlines.

## TECHNICAL BREAKTHROUGHS
Demonstrated results only — records, first flights, qualified parts,
validated data. Not announcements of intent.

## REGULATORY SHIFTS
Rule changes, interconnection/licensing/permitting moves, export
controls. Only if something actually changed.

## HIRING & FAILURES
Hiring surges, layoffs, shutdowns, pivots. Both directions are signal:
hiring shows where capital is going, failure shows what's harder than
people thought.

STEP 4 — Update memory
Append today's items to deeptech-memory.md as one line each:
date | section | headline | source. Keep it terse.

TONE: Write like a memo to one person who already knows the industry.
No throat-clearing, no "the landscape continues to evolve," no
restating what I obviously already know. If nothing interesting
happened today, a five-line brief is the correct output.
```

The last paragraph matters more than it looks. Without it you get polished summaries of nothing.

---

## Step 5 — Tune it for two weeks

Run it and watch for these failure modes:

| Symptom | Fix |
|---|---|
| Same stories every day | Memory file isn't being read/written — confirm it exists and check the file is actually updating |
| Generic, could-be-about-anything summaries | Tighten the tone paragraph; add "each item must name a specific company, number, or technical claim" |
| Skipping sources | Cowork picks its own path each run — coverage is best-effort. If a source matters and gets missed repeatedly, that's your signal to move to Step 8 |
| Too long | Add "maximum 12 items total; cut the weakest" |
| Missing SBIR entirely | Agents are inconsistent with APIs. Move that piece to a script (Step 8) |

Give it ten runs before judging. The first few will be worse than the tenth.

---

## Step 6 — Create the weekly task (5 min)

Separate scheduled task. Cadence: **weekly, Sunday evening**.

```
Weekly deep-tech deep scan. Longer horizon than the daily brief —
looking for emerging technical directions and commercialization
opportunities, not news.

1. arXiv new submissions from the past week in:
   physics.app-ph, eess.SY, cond-mat.mtrl-sci, physics.space-ph
   Surface only papers with a plausible path to a product in 3-7 years.
   For each: what's the result, what would have to be true for it to
   become a company, who are the authors and where.

2. New posts and portfolio announcements from: Eclipse Ventures,
   Lux Capital (luxcapital.com/news — check for new quarterly LP Letters
   from Josh Wolfe, which are the real thesis reading), DCVC,
   Prime Movers Lab, Breakthrough Energy Ventures, Founders Fund.
   Read the theses, ignore the marketing. What are they signaling
   they'll fund in the next 12 months?

3. New essays from Works in Progress and The Diff.

4. Stanford OTL TechFinder (techfinder.stanford.edu) — new listings in
   mechanical engineering, energy, materials, aerospace. For each:
   what is it, which lab, is it licensable now.

Output: max 10 items. Each one gets a "why this could be a company"
paragraph, not a sentence. Depth over coverage this time.

Append to deeptech-memory.md under a WEEKLY heading.
```

---

## Step 7 — The Stanford layer (do this manually)

This is the part that actually finds you a co-founder, and automation is the wrong tool for it.

**Every week, manually:**
- Check seminar calendars for ME, Materials Science & Engineering, ChemE, Applied Physics, and the Doerr School. A seminar listing tells you what a lab is working on *right now* and gives you a legitimate reason to be in the room and ask a question.
- Scan TomKat Center Innovation Grant awardees. That list is pre-filtered for Stanford people who already want to commercialize something — the single highest-density source of potential co-founders you have access to.

**Once at the start of the quarter:**
- Go through OTL TechFinder systematically for your three domains. Note every listing where you can name the lab.
- Register for Stanford Venture Studio and look at Startup Garage. You're MS&E — this is your home turf.

Cross-reference: when the daily brief flags a problem, check whether any Stanford lab is working on it. That intersection is your actual target list.

---

## Step 8 — When to graduate to code

Cowork's limitation is that it decides its own path through the web each run, so per-source coverage is best-effort. If after a month you find it's reliably missing SBIR topics or skipping feeds you care about, switch to deterministic ingestion:

- GitHub Actions scheduled workflow (cron at an odd minute — `7 13 * * *`, not `0`, since top-of-hour runs get delayed; always add `workflow_dispatch:` for manual triggers)
- Python: `feedparser` over the OPML for gathering, plain HTTP for Supabase — no LLM in this part at all
- Synthesis via Claude Code, authenticated with your Claude subscription (not a metered API key) — see Step 9 and `HANDOFF.md`
- Writes to Supabase instead of a memory file — see Step 9

Cost: included in your existing Claude subscription rather than metered separately. Scheduled runs do draw down the same Claude Code usage budget your interactive sessions use, so it's not literally free, just not an *additional* charge.

The advantage isn't the model — it's that ingestion becomes guaranteed rather than best-effort. Don't build this first. Let the Cowork version tell you what's broken, then build exactly that.

---

## Step 9 — The website and write pipeline

**Supabase is live.** Project `deeptech-briefing`, ref `kcdlsaqqcgngrwreucei`, `us-west-1`, in your `sethrhodes's Org` account, $0/month on the free tier. Two tables: `briefings` (one row per day) and `items` (one row per brief item, with `section`, `headline`, `summary`, `founder_note`, `source_name`, `source_url`). RLS is on — public read, no public write.

**Frontend is built.** `deeptech-briefing-site.html` — a single-file static page, date rail, click a day to see it grouped by section, click an item to expand. The anon key (`sb_publishable_CN7p9jB8uOtCE_JOsGUlYQ_1Rzqc-E5`) is embedded and safe — RLS only lets it read.

**⚠️ The write side changed architecture — this section is superseded.** The original plan called for `daily_brief.py` to call `api.anthropic.com` directly with an `ANTHROPIC_API_KEY`, billed separately from any Claude subscription. That's been replaced: the current `daily_brief.py` has no LLM calls in it at all (just `gather` and `write` subcommands, pure HTTP), and synthesis happens in **Claude Code itself** inside the GitHub Actions run, authenticated with a `CLAUDE_CODE_OAUTH_TOKEN` tied to your Claude subscription — not a metered API key.

**Full setup instructions for this are in `HANDOFF.md`**, delivered alongside this doc, written directly for Claude Code to execute: creating the repo, generating the OAuth token (`claude setup-token` — needs you present for a browser approval step), setting the two required secrets (`CLAUDE_CODE_OAUTH_TOKEN` and `SUPABASE_SERVICE_ROLE_KEY` — no `ANTHROPIC_API_KEY` anywhere), enabling Pages, and verifying it all worked. Hand that file to Claude Code and it has everything it needs.

One thing worth knowing going in: this isn't free in an absolute sense, it's included-in-your-subscription rather than metered. Scheduled runs draw from the same Claude Code usage budget as your interactive sessions.

---

## Source reference

Full list with feed URLs is in `deeptech-feeds.opml`. Email-only sources are in Step 1 and are not in the OPML.

Sources deliberately excluded: general tech press (TechCrunch, The Verge) — too shallow and too late for deep tech; aggregators — you want primary sources; anything paywalled without a free tier worth reading.
