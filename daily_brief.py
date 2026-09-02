#!/usr/bin/env python3
"""
Daily deep-tech opportunity brief — gather/write split for Claude Code.

Two subcommands, no Anthropic API key anywhere in this file. The synthesis
step (turning raw RSS items into the five-section brief) happens in Claude
Code itself, authenticated with your Claude subscription via
CLAUDE_CODE_OAUTH_TOKEN -- not this script, and not api.anthropic.com.

  python daily_brief.py gather [--out brief_input.json]
      Fetches RSS feeds from deeptech-feeds.opml, queries Supabase for
      headlines already covered in the last 14 days, writes both as JSON.
      No LLM involved. No cost beyond ordinary HTTP requests.

  python daily_brief.py write brief_output.json [--force]
      Reads a JSON array of synthesized brief items (the shape Claude Code
      is instructed to produce -- see HANDOFF.md) and writes them to
      Supabase as today's briefing. No LLM involved.

Government funding sources (Grants.gov, SBIR) aren't wired in by choice --
see HANDOFF.md for how to add them back in later.

Requires env var: SUPABASE_SERVICE_ROLE_KEY

Expects deeptech-feeds.opml in the same directory.
"""

import datetime as dt
import json
import os
import sys
import xml.etree.ElementTree as ET

import feedparser
import requests

# ---- Config ---------------------------------------------------------------

SUPABASE_URL = "https://kcdlsaqqcgngrwreucei.supabase.co"

OPML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deeptech-feeds.opml")
DAILY_CATEGORIES = {"Space", "Energy", "Manufacturing and Industrial", "Research and Advisory"}

# 72, not 48, because of the weekend. The cron runs Mon-Fri at 13:13 UTC,
# so Friday's run ends at Fri 13:13 and the next one is Monday. A 48h window
# would start Sat 13:13 and silently skip all of Friday's US business day --
# the densest day of the week for funding news. 72h makes Monday's window
# begin exactly where Friday's ended. The extra overlap on Tue-Fri is
# harmless: the 14-day already_covered list from Supabase dedups it.
LOOKBACK_HOURS = 72
MAX_RAW_ITEMS = 120       # cap on how much raw material goes to the model
SUMMARY_TRUNCATE = 400    # chars per RSS entry description, to control tokens

VALID_SECTIONS = {
    "problems_surfaced", "funding_signals", "technical_breakthroughs",
    "regulatory_shifts", "hiring_failures",
}

# ---- Gather: RSS ------------------------------------------------------------

def load_feed_urls(opml_path, categories):
    tree = ET.parse(opml_path)
    urls = []
    for category in tree.getroot().find("body"):
        if category.get("text") not in categories:
            continue
        for feed in category:
            url = feed.get("xmlUrl")
            if url:
                urls.append((feed.get("title", url), url))
    return urls


def fetch_rss_items(feed_urls, since):
    items = []
    for source_name, url in feed_urls:
        try:
            parsed = feedparser.parse(url, agent="Mozilla/5.0 (compatible; deeptech-brief/1.0)")
        except Exception as e:
            print(f"  ! {source_name}: {e}", file=sys.stderr)
            continue

        if parsed.bozo and not parsed.entries:
            print(f"  ! {source_name}: unparseable, skipping", file=sys.stderr)
            continue

        for entry in parsed.entries:
            published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
            published_dt = None
            if published_struct:
                published_dt = dt.datetime(*published_struct[:6], tzinfo=dt.timezone.utc)
                if published_dt < since:
                    continue
            summary = (entry.get("summary") or "")[:SUMMARY_TRUNCATE]
            items.append({
                "source": source_name,
                "title": entry.get("title", "(untitled)"),
                "link": entry.get("link", ""),
                "summary": summary,
                "published": published_dt.isoformat() if published_dt else None,
            })
    return items

# NOTE: government funding sources (Grants.gov, SBIR) aren't wired into
# this script by request — RSS + the email subscriptions from Step 1
# (SBIR/STTR newsletter, Grants.gov saved-search alerts) cover that ground
# manually for now. To bring Grants.gov's search2 API back in later: it's
# a POST to https://api.grants.gov/v1/api/search2 with a JSON body like
# {"keyword": "energy storage", "oppStatuses": "posted"}, response under
# data.oppHits — see the setup guide, Step 2, for the confirmed request
# shape. The field names inside each hit weren't verified from this
# environment, so check them against a live response before trusting them.

# ---- Supabase ---------------------------------------------------------------

def supabase_headers(service_key):
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }


def recent_headlines(service_key, days=14):
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/items",
        headers=supabase_headers(service_key),
        params={
            "select": "headline",
            "created_at": f"gte.{since}",
            "order": "created_at.desc",
            "limit": "200",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return [row["headline"] for row in resp.json()]


def upsert_briefing(service_key, brief_date, kind="daily"):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/briefings?on_conflict=brief_date",
        headers={
            **supabase_headers(service_key),
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
        json={"brief_date": brief_date, "kind": kind},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()[0]["id"]


def briefing_item_count(service_key, briefing_id):
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/items",
        headers=supabase_headers(service_key),
        params={"select": "id", "briefing_id": f"eq.{briefing_id}"},
        timeout=20,
    )
    resp.raise_for_status()
    return len(resp.json())


def insert_items(service_key, briefing_id, items):
    rows = []
    for it in items:
        section = it.get("section")
        if section not in VALID_SECTIONS:
            print(f"  ! skipping item with invalid section {section!r}: {it.get('headline')}", file=sys.stderr)
            continue
        if not it.get("headline") or not it.get("summary"):
            print(f"  ! skipping item missing headline/summary: {it}", file=sys.stderr)
            continue
        rows.append({
            "briefing_id": briefing_id,
            "section": section,
            "headline": it["headline"],
            "summary": it["summary"],
            "founder_note": it.get("founder_note"),
            "source_name": it.get("source_name"),
            "source_url": it.get("source_url") or None,
        })
    if not rows:
        return 0
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/items",
        headers=supabase_headers(service_key),
        json=rows,
        timeout=30,
    )
    resp.raise_for_status()
    return len(rows)

# ---- Subcommand: gather ------------------------------------------------------

def cmd_gather(args):
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=LOOKBACK_HOURS)

    print("Loading feeds...", file=sys.stderr)
    feed_urls = load_feed_urls(OPML_PATH, DAILY_CATEGORIES)
    print(f"  {len(feed_urls)} feeds in scope", file=sys.stderr)

    print("Fetching RSS...", file=sys.stderr)
    rss_items = fetch_rss_items(feed_urls, since)
    print(f"  {len(rss_items)} entries in the last {LOOKBACK_HOURS}h", file=sys.stderr)

    raw_items = rss_items[:MAX_RAW_ITEMS]

    supabase_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    print("Checking Supabase for recently covered headlines...", file=sys.stderr)
    covered = recent_headlines(supabase_key)
    print(f"  {len(covered)} headlines from the last 14 days", file=sys.stderr)

    payload = {"raw_items": raw_items, "already_covered": covered}
    output = json.dumps(payload, indent=2)

    if args.out:
        with open(args.out, "w") as f:
            f.write(output)
        print(f"Wrote {args.out} ({len(raw_items)} raw items)", file=sys.stderr)
    else:
        print(output)  # stdout, so this can be piped

# ---- Subcommand: write --------------------------------------------------------

def cmd_write(args):
    supabase_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    with open(args.path) as f:
        brief_items = json.load(f)

    if not isinstance(brief_items, list):
        print(f"Error: {args.path} must contain a JSON array of items.", file=sys.stderr)
        sys.exit(1)

    if not brief_items:
        print("Nothing to write (empty array). Exiting.", file=sys.stderr)
        return

    today = dt.date.today().isoformat()
    briefing_id = upsert_briefing(supabase_key, today, kind="daily")

    existing = briefing_item_count(supabase_key, briefing_id)
    if existing > 0 and not args.force:
        print(f"Briefing for {today} already has {existing} items. "
              f"Re-run with --force to add more anyway. Exiting.", file=sys.stderr)
        return

    n = insert_items(supabase_key, briefing_id, brief_items)
    print(f"Wrote {n} items to briefing {today} ({briefing_id})", file=sys.stderr)

# ---- Main --------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_gather = sub.add_parser("gather", help="Fetch RSS + Supabase dedup list, output JSON")
    p_gather.add_argument("--out", help="Write to this file instead of stdout")
    p_gather.set_defaults(func=cmd_gather)

    p_write = sub.add_parser("write", help="Write a synthesized JSON array to Supabase")
    p_write.add_argument("path", help="Path to the JSON file Claude Code wrote")
    p_write.add_argument("--force", action="store_true",
                          help="Write even if today's briefing already has items")
    p_write.set_defaults(func=cmd_write)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
