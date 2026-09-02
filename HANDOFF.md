# Handoff: finish setting up the deep-tech briefing pipeline

You are Claude Code, running locally with the user's Claude subscription. This
document is everything you need to finish deploying a project that was mostly
built already in a chat session. Read this whole file before starting.

## What already exists (built, don't redo)

- **A Supabase project**, live: `deeptech-briefing`, ref `kcdlsaqqcgngrwreucei`,
  region `us-west-1`, org `sethrhodes's Org`. Free tier, $0/month. Schema is
  deployed: two tables, `briefings` and `items`, RLS on with public read only.
- **Five files**, delivered alongside this handoff, meant to sit at the root of
  a new GitHub repo:
  - `daily_brief.py` — fetches RSS feeds and writes to Supabase. Two
    subcommands, `gather` and `write`. No LLM calls inside this file at all.
  - `requirements.txt` — `feedparser`, `requests`.
  - `deeptech-feeds.opml` — the RSS feed list `daily_brief.py` reads. All
    entries verified working as of this handoff.
  - `deeptech-briefing-site.html` — a static single-page frontend that reads
    from Supabase (anon key already embedded, safe, read-only). Needs to be
    renamed to `index.html` at the repo root for GitHub Pages.
  - `daily-brief.yml` — the GitHub Actions workflow. Goes at
    `.github/workflows/daily-brief.yml`.

## The architecture, and why it's shaped this way

The user does **not** want to pay for `api.anthropic.com` usage on top of
their existing Claude subscription. So the pipeline is split into three
steps, only the middle one touches an LLM, and that step authenticates with
the subscription instead of a metered API key:

1. **`daily_brief.py gather`** — plain Python + HTTP. Fetches RSS, checks
   Supabase for recently-covered headlines, writes `brief_input.json`. No
   LLM, no Anthropic anything.
2. **Claude Code itself**, via the `anthropics/claude-code-action` GitHub
   Action, authenticated with `CLAUDE_CODE_OAUTH_TOKEN` — a token tied to the
   user's Claude subscription (Pro/Max/Team/Enterprise), **not** an API key.
   Per Anthropic's docs: "If you authenticate with an OAuth token, runs use
   your Claude subscription instead of API billing." This step reads
   `brief_input.json`, synthesizes the five-section brief, writes
   `brief_output.json`.
3. **`daily_brief.py write`** — plain Python + HTTP again. Reads
   `brief_output.json`, writes it to Supabase.

**Be upfront with the user about the real tradeoff here**: this isn't free in
an absolute sense. Each run consumes some of the Claude Code usage/session
budget that comes with their subscription plan, the same budget their
interactive Claude Code use draws from. It's included in what they already
pay for rather than metered separately, which is what they asked for, but a
heavy plan-usage day elsewhere could interact with a scheduled run. Worth one
sentence to the user confirming that's the tradeoff they want, not something
to silently assume.

**Do not add an `ANTHROPIC_API_KEY` secret anywhere in this setup.** If you
find yourself about to add one, stop — that's the exact cost the user asked
to avoid.

## Your task list, in order

### 1. Confirm the architecture with the user before doing anything

Say, in your own words: this will run Claude Code in GitHub Actions on a
schedule, authenticated via a long-lived OAuth token tied to their Claude
subscription rather than a separate API key, and that scheduled runs draw
from their normal Claude Code usage limits. Get an explicit go-ahead before
generating any tokens or creating any cloud resources.

### 2. Create the GitHub repo

```bash
gh auth status || gh auth login
gh repo create deeptech-briefing --private --clone
```

(Public is fine too if the user prefers — ask, don't assume. Private is the
safer default since Supabase's anon key, while low-risk, will be visible in
the frontend HTML either way.)

Move the five delivered files into the new repo:
- `daily_brief.py`, `requirements.txt`, `deeptech-feeds.opml` at repo root
- `deeptech-briefing-site.html` at repo root, renamed to `index.html`
- `daily-brief.yml` at `.github/workflows/daily-brief.yml`

Commit and push to `main`.

### 3. Generate the Claude Code OAuth token

This step needs the user present — it opens a browser for them to approve
access to their own account. Run it and tell them what to expect:

```bash
claude setup-token
```

This prints a token to the terminal after they approve in the browser. It is
not saved anywhere automatically — copy it immediately. It's a one-year
token scoped to their subscription (Pro, Max, Team, or Enterprise required).

### 4. Get the Supabase service role key

You cannot fetch this yourself — it's the write-access credential and should
come from the user directly, not be scraped or guessed. Ask them to:

1. Open the Supabase dashboard for the `deeptech-briefing` project
   (`kcdlsaqqcgngrwreucei`)
2. Settings then API, reveal the `service_role` secret key
3. Paste it to you when you ask for it in step 5

Do not print this key back to the terminal in a way that lingers in shell
history if you can avoid it — pipe it directly into `gh secret set`.

### 5. Set both GitHub Actions secrets

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN --body "<token from step 3>"
gh secret set SUPABASE_SERVICE_ROLE_KEY --body "<key from step 4>"
```

Confirm both are set:

```bash
gh secret list
```

You should see exactly `CLAUDE_CODE_OAUTH_TOKEN` and
`SUPABASE_SERVICE_ROLE_KEY` — no `ANTHROPIC_API_KEY`.

### 6. Enable GitHub Pages

```bash
gh api repos/{owner}/{repo}/pages -X POST -f 'source[branch]=main' -f 'source[path]=/'
```

Replace `{owner}/{repo}` with the actual repo. If this API call fails, fall
back to walking the user through Settings then Pages then Source: Deploy
from branch, `main`, `/ (root)` in the browser — the API surface for Pages
has changed before and might not match exactly.

Confirm the Pages URL once it's live (usually
`https://<username>.github.io/deeptech-briefing/`, give it a minute or two
after enabling).

### 7. Trigger a manual run

Don't wait for the cron schedule to test this.

```bash
gh workflow run daily-brief.yml
gh run watch
```

Read the logs of all three steps if anything fails. Common failure points:
- Gather step: a feed URL from the OPML stopped resolving (feeds change).
  Check stderr for lines like "! source: error".
- Claude Code step: check that `brief_input.json` actually has entries in
  `raw_items` — if RSS gather found nothing, there's nothing to synthesize,
  and `brief_output.json` may not get written at all. That's a legitimate
  "nothing happened today" case, not necessarily a bug.
- Write step: will fail loudly if `brief_output.json` isn't valid JSON or
  isn't a JSON array. Read the actual JSON Claude Code produced if this
  happens — it sometimes wraps output in explanatory text despite
  instructions not to.

### 8. Verify data actually landed

Query Supabase directly rather than trusting the workflow's "success" status
alone:

```bash
curl "https://kcdlsaqqcgngrwreucei.supabase.co/rest/v1/briefings?select=*&order=brief_date.desc&limit=1" \
  -H "apikey: sb_publishable_CN7p9jB8uOtCE_JOsGUlYQ_1Rzqc-E5"
```

That's the public anon key, safe to use here, read-only. You should see a
row for today's date. To see the items too, grab the id from that response
and query items with briefing_id equal to that id.

Then open the Pages URL and confirm the frontend actually renders it.

### 9. Report back to the user

Summarize: repo URL, Pages URL, confirmation the scheduled workflow ran
successfully at least once, and the two secrets that are set (never restate
their values). Mention the workflow runs weekdays at 13:13 UTC (6:13am
Pacific during PDT) and can be re-triggered manually any time with
`gh workflow run daily-brief.yml`.

## Known gaps, tell the user about these, don't silently fix them

- SBIR and Grants.gov aren't wired in. This was a deliberate scope decision
  from the original chat session, not something missing by accident. Don't
  add them without the user asking.
- Two feed URLs in the OPML weren't independently content-verified: Ars
  Technica's space feed and Scope of Work's RSS, because the tool used to
  check the others was blocked by those two sites specifically. If the
  gather step logs an error for either on the first real run, that's why.
- The Claude Code synthesis step doesn't have a memory of yesterday beyond
  the 14-day Supabase dedup list. That's intentional and matches the
  original design, but if the user notices repeats, the fix is tuning the
  prompt in daily-brief.yml, not adding new infrastructure.
