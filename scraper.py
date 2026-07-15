#!/usr/bin/env python3
"""Build an RSS podcast feed (feed.xml) for Elliot on Demand.

The site at https://www.eitmondemand.com/ server-renders the full episode
list as a JSON array inside an inline `setupLocalStorage([...])` call, so we
just fetch the page, pull that JSON out, and turn each episode into an RSS
item. Audio files live on CloudFront; the fileName field is the object key.
"""

import datetime
import html
import json
import re
import sys

import requests
from feedgen.feed import FeedGenerator

SITE_URL = "https://www.eitmondemand.com/"
AUDIO_BASE = "https://d2bso5f73cpfun.cloudfront.net/"
COVER_IMAGE = "https://www.eitmondemand.com/EITM_400x400.jpeg"
OUTPUT_FILE = "feed.xml"

# The apex domain (eitmondemand.com) resets HTTPS connections; www works.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# Boilerplate appended to every segment description on the source site.
PRIVACY_NOTE = "See omnystudio.com/listener for privacy information."


def fetch_episodes():
    """Return the list of episode dicts embedded in the homepage."""
    resp = requests.get(SITE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    match = re.search(r"setupLocalStorage\(\s*(\[.*?\])\s*\)", resp.text, re.S)
    if not match:
        raise RuntimeError("Could not find episode data (setupLocalStorage) on the page")

    episodes = json.loads(match.group(1))
    if not episodes:
        raise RuntimeError("Episode list parsed but was empty")
    return episodes


def parse_pubdate(file_name, title):
    """Derive a timezone-aware pubDate from the fileName timestamp.

    fileName looks like '2026-07-15T05:45:00.mp3'. Fall back to the human
    title ('Wed Jul 15 2026') if that fails.
    """
    stamp = file_name.rsplit(".", 1)[0]  # strip .mp3
    try:
        dt = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        dt = datetime.datetime.strptime(title, "%a %b %d %Y")
    return dt.replace(tzinfo=datetime.timezone.utc)


def build_description(episode):
    """Compose an HTML-ish item description from the episode's segments."""
    segments = episode.get("segments") or []
    lines = []
    for seg in segments:
        seg_title = (seg.get("title") or "").strip()
        seg_desc = (seg.get("description") or "").replace(PRIVACY_NOTE, "").strip()
        if seg_title and seg_desc:
            lines.append(f"{seg_title} — {seg_desc}")
        elif seg_title:
            lines.append(seg_title)
        elif seg_desc:
            lines.append(seg_desc)

    if not lines:
        return f"Elliot on Demand — episode for {episode['title']}."
    return "\n".join(f"• {line}" for line in lines)


def main():
    episodes = fetch_episodes()
    print(f"Found {len(episodes)} episodes")

    fg = FeedGenerator()
    fg.load_extension("podcast")

    fg.title("Elliot on Demand")
    fg.link(href=SITE_URL, rel="alternate")
    fg.description("New episodes of Elliot on Demand every day.")
    fg.language("en")
    # The cover art is served as .jpeg; feedgen's itunes_image only accepts
    # .jpg/.png, so we set the standard RSS <image> tag instead — iTunes and
    # other clients fall back to it when <itunes:image> is absent.
    fg.image(url=COVER_IMAGE, title="Elliot on Demand", link=SITE_URL)
    fg.podcast.itunes_category("Comedy")
    fg.podcast.itunes_explicit("no")

    # Add oldest-first; feedgen prepends by default, so the newest episode
    # ends up at the top of the feed.
    for episode in sorted(episodes, key=lambda e: parse_pubdate(e["fileName"], e["title"])):
        file_name = episode["fileName"]
        pubdate = parse_pubdate(file_name, episode["title"])
        audio_url = AUDIO_BASE + file_name

        fe = fg.add_entry()
        fe.id(audio_url)
        fe.title(f"Elliot on Demand — {episode['title']}")
        fe.description(html.unescape(build_description(episode)))
        fe.enclosure(audio_url, 0, "audio/mpeg")
        fe.pubDate(pubdate)
        fe.link(href=SITE_URL)

    fg.rss_file(OUTPUT_FILE, pretty=True)
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # surface a clear failure in CI logs
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
