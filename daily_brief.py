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
import email as email_pkg
import html
import imaplib
import json
import os
import re
import sys
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime, parseaddr
import xml.etree.ElementTree as ET

import feedparser
import requests

# ---- Config ---------------------------------------------------------------

SUPABASE_URL = "https://kcdlsaqqcgngrwreucei.supabase.co"

OPML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deeptech-feeds.opml")
DAILY_CATEGORIES = {"Space", "Energy", "Manufacturing and Industrial",
                    "Research and Advisory", "Funding Alerts"}

# 72, not 48, because of the weekend. The cron runs Mon-Fri at 13:13 UTC,
# so Friday's run ends at Fri 13:13 and the next one is Monday. A 48h window
# would start Sat 13:13 and silently skip all of Friday's US business day --
# the densest day of the week for funding news. 72h makes Monday's window
# begin exactly where Friday's ended. The extra overlap on Tue-Fri is
# harmless: the 14-day already_covered list from Supabase dedups it.
LOOKBACK_HOURS = 72
MAX_RAW_ITEMS = 120       # cap on how much raw material goes to the model
SUMMARY_TRUNCATE = 400    # chars per RSS entry description, to control tokens

# Newsletter ingestion. Opt-in: without GMAIL_APP_PASSWORD in the environment
# the gather step skips this entirely and behaves exactly as it did before.
IMAP_HOST = "imap.gmail.com"
GMAIL_USER = os.environ.get("GMAIL_USER", "sethnewsmail@gmail.com")
MAX_EMAIL_ITEMS = 25
# Funding digests list many opportunities in one message, so an article-sized
# budget clips mid-list. Measured against a real 72h window of this mailbox:
# bodies run min 407 / p50 2,008 / p90 14,677 / max 79,474 chars. 3,000 leaves
# 10 of 23 clipped for ~10k tokens; 6,000 would cost 6k more tokens and rescue
# exactly one message, because the tail is long. Newsletters also front-load
# the substance, so a clip keeps the part that matters.
EMAIL_SUMMARY_TRUNCATE = 3000

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


_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_summary(raw):
    """Reduce a feed summary to plain text before it gets truncated.

    Most feeds put HTML in <description>, and several lead with a thumbnail
    <img> whose alt text, CSS classes and dimensions are longer than the
    truncation budget -- so the model was receiving markup attributes rather
    than the article. Strip first, then truncate, so the budget buys prose.
    """
    if not raw:
        return ""
    text = _SCRIPT_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


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
            summary = clean_summary(entry.get("summary"))[:SUMMARY_TRUNCATE]
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

# ---- Gather: newsletter email ------------------------------------------------

# Links worth keeping point at an opportunity. These do not.
_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
_URL_SKIP = re.compile(
    r"unsubscribe|list-manage|optout|opt-out|/preferences|mailchi|sendgrid|"
    r"click\.|/track|utm_|twitter\.com|x\.com|facebook\.com|linkedin\.com|"
    r"instagram\.com|youtube\.com|\.(png|jpe?g|gif|css|js)(\?|$)",
    re.I,
)


def _decode_header(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _raw_body(msg):
    """Best-effort raw body text, preferring text/plain over text/html."""
    plain, rich = [], []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
        except Exception:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = payload.decode("utf-8", errors="replace")
        (plain if ctype == "text/plain" else rich).append(text)
    return "\n".join(plain or rich)


def first_link(raw_body):
    """First URL in the body that is not tracking, social, or an unsubscribe."""
    for match in _URL_RE.finditer(raw_body or ""):
        url = match.group(0).rstrip(".,);:'\"")
        if _URL_SKIP.search(url):
            continue
        return url
    return ""


def email_item(msg, since):
    """Shape one message like an RSS entry, or None if it is out of window."""
    published_dt = None
    try:
        published_dt = parsedate_to_datetime(msg.get("Date"))
        if published_dt is not None and published_dt.tzinfo is None:
            published_dt = published_dt.replace(tzinfo=dt.timezone.utc)
    except Exception:
        published_dt = None
    # IMAP SINCE has day granularity, so re-check against the real window.
    if published_dt is not None and published_dt < since:
        return None

    sender_name, sender_addr = parseaddr(msg.get("From") or "")
    sender = _decode_header(sender_name) or sender_addr or "unknown sender"
    raw = _raw_body(msg)
    return {
        "source": f"Inbox: {sender}",
        "title": _decode_header(msg.get("Subject")) or "(no subject)",
        "link": first_link(raw),
        "summary": clean_summary(raw)[:EMAIL_SUMMARY_TRUNCATE],
        "published": published_dt.isoformat() if published_dt else None,
    }


def fetch_email_items(since, user, password, host=IMAP_HOST, limit=MAX_EMAIL_ITEMS):
    """Read recent newsletter mail over IMAP.

    The mailbox is opened readonly, so nothing here can alter or delete mail
    even though an app password would technically permit it.
    """
    items = []
    try:
        conn = imaplib.IMAP4_SSL(host, timeout=30)
    except TypeError:  # older imaplib has no timeout kwarg
        conn = imaplib.IMAP4_SSL(host)
    try:
        conn.login(user, password)
        conn.select("INBOX", readonly=True)
        typ, data = conn.search(None, "SINCE", since.strftime("%d-%b-%Y"))
        if typ != "OK" or not data or not data[0]:
            return items
        for msg_id in reversed(data[0].split()[-limit:]):
            typ, payload = conn.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not payload or not payload[0]:
                continue
            item = email_item(email_pkg.message_from_bytes(payload[0][1]), since)
            if item and item["summary"]:
                items.append(item)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return items


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

    # Email is appended after the RSS cap so a busy news day can never crowd
    # out a funding deadline, which is the whole reason it is ingested.
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if app_password:
        print("Fetching newsletter email...", file=sys.stderr)
        try:
            email_items = fetch_email_items(since, GMAIL_USER, app_password)
            print(f"  {len(email_items)} messages in the last {LOOKBACK_HOURS}h", file=sys.stderr)
            raw_items += email_items
        except Exception as e:
            # A mail outage must not cost us the RSS brief.
            print(f"  ! email: {type(e).__name__}: {e}", file=sys.stderr)
    else:
        print("  (GMAIL_APP_PASSWORD unset, skipping email)", file=sys.stderr)

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
