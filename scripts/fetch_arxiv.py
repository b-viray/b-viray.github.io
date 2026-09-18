#!/usr/bin/env python3
"""Fetch the most recently updated arXiv papers and write _arxiv-recent.qmd,
the fragment that research.qmd includes near the top of the page.

Run automatically by .github/workflows/quarto-publish.yml before Quarto
renders the site. To run it by hand:   python3 scripts/fetch_arxiv.py

If arXiv is unreachable or returns nothing usable, the existing
_arxiv-recent.qmd is left untouched, so the site keeps the last good list.

WHY THIS FEED: the source is the Atom feed of the arXiv author identifier
page (arxiv.org/a/viray_b_1), which is tied to the ORCID above and lists
only the papers claimed under that identifier. A keyword search of the API
(au:"Viray, Bianca") would also match any future namesake, so it is not used.
Two other sources were considered and rejected:
  * arxiv.org/a/viray_b_1.json  - same content, but not valid UTF-8; it
    mangles non-ASCII coauthor names (e.g. Balcik with a cedilla).
  * au:viray_b in the search API - returns ZERO results; the API wants
    "Lastname, Firstname", not the author-identifier spelling.
The author page is regenerated daily, so a brand-new posting can take up to
a day to appear here.
"""

import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ARXIV_AUTHOR_ID = "viray_b_1"
FEED_URL = "https://arxiv.org/a/%s.atom" % ARXIV_AUTHOR_ID
MAX_PAPERS = 5
ATTEMPTS = 3

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
OUT = Path(__file__).resolve().parent.parent / "_arxiv-recent.qmd"

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

# Markdown characters that must be escaped in text coming from arXiv,
# so that e.g. an underscore or bracket in an abstract is not read as markup.
MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|~^#])")
# Inline math ($...$) is passed through untouched so Quarto/MathJax renders it.
MATH = re.compile(r"\$[^$]*\$")


def md_escape(text):
    """Escape markdown specials outside of $...$ math."""
    out, last = [], 0
    for m in MATH.finditer(text):
        out.append(MD_SPECIAL.sub(r"\\\1", text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(MD_SPECIAL.sub(r"\\\1", text[last:]))
    return "".join(out)


def squash(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def to_utc(stamp):
    """The feed stamps times in US Eastern ('2026-06-17T22:09:21-04:00').
    Convert to UTC so the printed date matches the arXiv abstract page."""
    return datetime.fromisoformat(squash(stamp)).astimezone(timezone.utc)


def pretty_date(moment):
    return "%d %s %d" % (moment.day, MONTHS[moment.month - 1], moment.year)


def fetch_feed():
    last_error = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            request = urllib.request.Request(
                FEED_URL, headers={"User-Agent": "b-viray.github.io site build"})
            with urllib.request.urlopen(request, timeout=45) as response:
                return ET.fromstring(response.read())
        except Exception as err:          # network hiccup, 503, malformed XML
            last_error = err
            print("arXiv attempt %d/%d failed: %s" % (attempt, ATTEMPTS, err))
            if attempt < ATTEMPTS:
                time.sleep(5 * attempt)
    raise RuntimeError("could not reach arXiv: %s" % last_error)


def parse(root):
    papers = []
    for entry in root.findall(ATOM + "entry"):
        abs_url = squash(entry.findtext(ATOM + "id"))
        abs_url = re.sub(r"^http://", "https://", abs_url)
        abs_url = re.sub(r"v\d+$", "", abs_url)      # link to the latest version

        published = to_utc(entry.findtext(ATOM + "published"))
        updated = to_utc(entry.findtext(ATOM + "updated"))
        revised = updated.date() != published.date()

        papers.append({
            "title": squash(entry.findtext(ATOM + "title")),
            "url": abs_url,
            "authors": [squash(name.text) for name in entry.iter(ATOM + "name")],
            "sort_key": updated,
            "date_label": "Updated" if revised else "Posted",
            "date": pretty_date(updated if revised else published),
            "journal": squash(entry.findtext(ARXIV + "journal_ref")),
            "abstract": squash(entry.findtext(ATOM + "summary")),
        })
    papers.sort(key=lambda p: p["sort_key"], reverse=True)
    return papers[:MAX_PAPERS]


def render(papers):
    lines = [
        "<!-- GENERATED FILE - do not edit by hand.",
        "     Written by scripts/fetch_arxiv.py, which runs in the GitHub Actions",
        "     build (and on a daily schedule) before Quarto renders the site.",
        "     Included near the top of research.qmd. -->",
        "",
        "::::: {.arxiv-list}",
        "",
    ]
    for paper in papers:
        meta = "%s %s" % (paper["date_label"], paper["date"])
        if paper["journal"]:
            meta += " &middot; " + md_escape(paper["journal"])
        lines += [
            ":::: {.arxiv-paper}",
            "",
            "[%s](%s){.arxiv-title}" % (md_escape(paper["title"]), paper["url"]),
            "",
            "[%s]{.arxiv-authors}" % md_escape(", ".join(paper["authors"])),
            "",
            "[%s]{.arxiv-meta}" % meta,
            "",
            "::: {.arxiv-abs}",
            md_escape(paper["abstract"]),
            ":::",
            "",
            "::::",
            "",
        ]
    lines += [":::::", ""]
    return "\n".join(lines)


def main():
    try:
        papers = parse(fetch_feed())
    except Exception as err:
        print("arXiv fetch failed (%s); keeping the committed %s" % (err, OUT.name))
        return 0                      # never fail the build over this
    if not papers:
        print("arXiv returned no papers; keeping the committed %s" % OUT.name)
        return 0
    OUT.write_text(render(papers), encoding="utf-8")
    print("Wrote %d papers to %s" % (len(papers), OUT.name))
    for paper in papers:
        print("  - %s (%s %s)" % (paper["title"][:70], paper["date_label"].lower(), paper["date"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
