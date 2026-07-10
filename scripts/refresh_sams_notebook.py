#!/usr/bin/env python3
"""Refresh Sam's Notebook posts in the offline seed straight from the web.

Fetches the live Sam's Notebook site (https://robertslab.github.io/sams-notebook),
keeps recent posts that carry a direct github.com/RobertsLab/<repo> link, extracts
their title / date / categories / body, and rewrites the ``sams-notebook`` entries
in ``data/raw/notebooks_seed.json``. Tumbling Oysters entries are left untouched.

Then rebuild the graph::

    python scripts/refresh_sams_notebook.py
    python run_all.py --offline

Why "recent + has a RobertsLab link": those posts each yield a confidence-1.0
``links_to`` edge, which is what makes the notebook<->repo map useful. The cutoff
follows the calendar (default: current year and the year before), so re-running
next year automatically picks up new posts without code changes.

Dependency-free: uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

SITE_URL = "https://robertslab.github.io/sams-notebook/"
ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "raw" / "notebooks_seed.json"

POST_HREF_RE = re.compile(r'href="(\.?/?posts/(\d{4})/[^"]+?/index\.html)"')
MAIN_RE = re.compile(r"<main\b[^>]*>(.*?)</main>", re.IGNORECASE | re.DOTALL)
H1_TITLE_RE = re.compile(r'<h1 class="title[^"]*">(.*?)</h1>', re.IGNORECASE | re.DOTALL)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
DATE_META_RE = re.compile(r'<meta name="dcterms\.date" content="([^"]+)"')
CATEGORY_RE = re.compile(r'quarto-category"[^>]*>([^<]+)<')
# RobertsLab repo names -- matched inside <main> only (the navbar links to
# sams-notebook / lab-website on every page, which are not real post links).
GH_RE = re.compile(r"github\.com/RobertsLab/([A-Za-z0-9._-]+)", re.IGNORECASE)
DATE_IN_SLUG_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "lab-connector/1.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def strip_html(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = html.unescape(fragment)
    return re.sub(r"\s+", " ", fragment).strip()


def discover_post_paths(landing_html: str) -> list[tuple[str, str]]:
    """Return [(year, absolute_url)] in document order (newest-first), deduped."""
    out, seen = [], set()
    for href, year in POST_HREF_RE.findall(landing_html):
        url = urljoin(SITE_URL, href)
        if url in seen:
            continue
        seen.add(url)
        out.append((year, url))
    return out


def parse_post(url: str, page: str) -> dict | None:
    m = MAIN_RE.search(page)
    main = m.group(1) if m else page
    repos = sorted({r.rstrip(".") for r in GH_RE.findall(main)})
    if not repos:
        return None  # no direct RobertsLab link -> skip

    slug = url.rstrip("/").split("/")[-2]  # .../<slug>/index.html
    tm = H1_TITLE_RE.search(page)
    if tm:
        title = strip_html(tm.group(1))
    else:
        tt = TITLE_RE.search(page)
        title = strip_html(tt.group(1)).split(" – ")[0] if tt else slug.replace("-", " ")

    dm = DATE_META_RE.search(page)
    date = dm.group(1) if dm else ""
    if not date:
        ds = DATE_IN_SLUG_RE.search(slug)
        date = ds.group(1) if ds else ""

    cats = [html.unescape(c).strip() for c in CATEGORY_RE.findall(page)]
    text = (" ".join(cats) + " . " + strip_html(main))[:8000]
    return {
        "site": "sams-notebook",
        "author": "Sam White",
        "slug": slug,
        "title": title,
        "url": url,
        "github_links": repos,
        "date": date,
        "text": text,
    }


def main() -> int:
    this_year = _dt.date.today().year
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since-year", type=int, default=this_year - 1,
                    help="oldest post year to include (default: last year)")
    ap.add_argument("--max-posts", type=int, default=None,
                    help="cap kept posts (default: no cap)")
    ap.add_argument("--sleep", type=float, default=0.25,
                    help="seconds between page fetches (politeness)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing the seed")
    a = ap.parse_args()

    print(f"[refresh] fetching landing page {SITE_URL}", file=sys.stderr)
    paths = discover_post_paths(fetch(SITE_URL))
    print(f"[refresh] {len(paths)} unique posts listed; "
          f"keeping year >= {a.since_year} with a RobertsLab link", file=sys.stderr)

    kept: list[dict] = []
    scanned = 0
    for year, url in paths:  # newest-first
        if int(year) < a.since_year:
            break  # listing is chronological; nothing older qualifies
        scanned += 1
        try:
            post = parse_post(url, fetch(url))
        except Exception as e:  # never let one bad page kill the run
            print(f"  [skip] {url}: {e}", file=sys.stderr)
            time.sleep(a.sleep)
            continue
        if post:
            kept.append(post)
            if a.max_posts and len(kept) >= a.max_posts:
                break
        time.sleep(a.sleep)

    print(f"[refresh] scanned {scanned} recent posts, kept {len(kept)} "
          f"with direct RobertsLab links", file=sys.stderr)
    if not kept:
        print("[refresh] nothing kept; leaving seed unchanged", file=sys.stderr)
        return 1

    seed = json.loads(SEED.read_text())
    sites = {s["id"] for s in seed.get("notebook_sites", [])}
    if "sams-notebook" not in sites:
        seed.setdefault("notebook_sites", []).append(
            {"id": "sams-notebook", "title": "Sam's Notebook",
             "author": "Sam White", "url": SITE_URL, "platform": "Quarto"})
    before = sum(1 for p in seed["posts"] if p.get("site") == "sams-notebook")
    seed["posts"] = [p for p in seed["posts"] if p.get("site") != "sams-notebook"]
    seed["posts"].extend(kept)
    seed["_meta"]["posts"] = len(seed["posts"])
    seed["_meta"]["notebook_sites"] = len(seed["notebook_sites"])
    seed["_meta"]["sams_notebook_refreshed"] = _dt.date.today().isoformat()

    if a.dry_run:
        print(f"[dry-run] would replace {before} -> {len(kept)} sams-notebook "
              f"posts (seed total {len(seed['posts'])})", file=sys.stderr)
        return 0

    SEED.write_text(json.dumps(seed, indent=2))
    to = sum(1 for p in seed["posts"] if p["site"] == "tumbling-oysters")
    print(f"[refresh] wrote seed: {to} tumbling-oysters + {len(kept)} sams-notebook "
          f"(replaced {before}). Now run: python run_all.py --offline", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
