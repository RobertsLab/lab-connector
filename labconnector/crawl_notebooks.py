"""
Crawl the Roberts Lab notebook ecosystem.

Live strategy
-------------
1. Fetch the notebook index (https://faculty.washington.edu/sr320/notebooks.html)
   and extract links to individual notebook sites (Quarto/Jekyll notebooks such
   as Tumbling Oysters and Sam's Notebook).
2. For each notebook site, fetch the landing page and extract post links.
3. For each post (bounded by --max-posts to stay polite), fetch the body and
   extract: outbound github.com links, mentioned repo names, dates, and entities
   (species / methods / keywords) via labconnector.vocab.

All pages are cached under data/raw/notebooks_cache/ so re-runs are cheap.
Robust to broken links, timeouts, and missing pages.

Offline strategy
----------------
Load the bundled snapshot data/raw/notebooks_seed.json (real Tumbling Oysters
posts) so the pipeline produces a graph with no network access.
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

from . import vocab

INDEX_URL = "https://faculty.washington.edu/sr320/notebooks.html"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
CACHE = RAW_DIR / "notebooks_cache"

GITHUB_REPO_RE = re.compile(r"github\.com/RobertsLab/([A-Za-z0-9._-]+)", re.IGNORECASE)
DATE_RE = re.compile(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})")

# Hosts that look like lab notebooks (individual member notebooks live here).
NOTEBOOK_HOST_HINTS = ("github.io", "notebook")


def _get(session, url: str, cache_name: str) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / cache_name
    if cf.exists():
        return cf.read_text("utf-8", "replace")
    try:
        r = session.get(url, timeout=30)
        if r.status_code == 200:
            cf.write_text(r.text, "utf-8")
            return r.text
    except Exception as e:
        print(f"  [fetch] {url}: {e}")
    return ""


def _slug_from(url: str) -> str:
    p = urlparse(url).path.rstrip("/")
    parts = [x for x in p.split("/") if x and x != "index.html"]
    return parts[-1] if parts else url


def discover_notebook_sites(session) -> List[Dict]:
    """Parse the index page for links to notebook sites."""
    from bs4 import BeautifulSoup
    html = _get(session, INDEX_URL, "index.html")
    sites = []
    seen = set()
    if html:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(INDEX_URL, a["href"])
            text = a.get_text(" ", strip=True)
            host = urlparse(href).netloc.lower()
            if any(h in host or h in href.lower() for h in NOTEBOOK_HOST_HINTS):
                if href in seen:
                    continue
                seen.add(href)
                sites.append({"id": _slug_from(href) or host,
                              "title": text or host,
                              "url": href, "author": text})
    return sites


def crawl_site_posts(session, site: Dict, max_posts: int) -> List[Dict]:
    """Fetch a notebook landing page and extract its post links + bodies."""
    from bs4 import BeautifulSoup
    posts = []
    html = _get(session, site["url"], f"site_{site['id']}.html")
    if not html:
        return posts
    soup = BeautifulSoup(html, "html.parser")
    hrefs = []
    for a in soup.find_all("a", href=True):
        u = urljoin(site["url"], a["href"])
        if "/posts/" in u and u not in hrefs:
            hrefs.append(u)
    for u in hrefs[:max_posts]:
        slug = _slug_from(u)
        body = _get(session, u, f"post_{site['id']}_{slug}.html")
        text = ""
        if body:
            text = BeautifulSoup(body, "html.parser").get_text(" ", strip=True)
        gh = sorted(set(m.group(1) for m in GITHUB_REPO_RE.finditer(body or "")))
        dates = ["-".join(f"{int(x):02d}" if i else x for i, x in enumerate(m.groups()))
                 for m in DATE_RE.finditer(text)]
        posts.append({
            "site": site["id"], "author": site.get("author", ""),
            "slug": slug, "title": slug.replace("-", " "),
            "url": u, "github_links": gh,
            "date": dates[0] if dates else "",
            "text": text[:8000],
        })
        time.sleep(0.3)
    return posts


def crawl_live(max_posts_per_site: int = 40) -> Dict:
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": "lab-connector/1.0"})
    sites = discover_notebook_sites(s)
    all_posts = []
    for site in sites:
        print(f"  notebook site: {site['title']} ({site['url']})")
        all_posts.extend(crawl_site_posts(s, site, max_posts_per_site))
    return {"notebook_sites": sites, "posts": all_posts}


def load_seed() -> Dict:
    seed = json.loads((RAW_DIR / "notebooks_seed.json").read_text())
    posts = []
    for p in seed["posts"]:
        blob = f"{p['slug']} {p.get('title','')}"
        posts.append({**p,
                      "github_links": p.get("github_links", []),
                      "date": p.get("date", ""),
                      "text": p.get("text", blob)})
    return {"notebook_sites": seed["notebook_sites"], "posts": posts}


def enrich(posts: List[Dict]) -> List[Dict]:
    """Attach extracted entities to each post."""
    for p in posts:
        blob = " ".join([p.get("slug", ""), p.get("title", ""), p.get("text", "")])
        ent = vocab.extract_all(blob)
        p["entities"] = ent
    return posts


def crawl(offline: bool = False, max_posts_per_site: int = 40) -> Dict:
    if offline:
        print("[notebooks] offline mode: loading seed snapshot")
        data = load_seed()
    else:
        try:
            data = crawl_live(max_posts_per_site)
            if not data["posts"]:
                raise RuntimeError("no posts discovered")
        except Exception as e:
            print(f"[notebooks] live crawl failed ({e}); falling back to seed snapshot")
            data = load_seed()
    data["posts"] = enrich(data["posts"])
    return data


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--max-posts", type=int, default=40)
    a = ap.parse_args()
    data = crawl(a.offline, a.max_posts)
    out = Path(__file__).resolve().parent.parent / "data" / "notebooks.json"
    out.write_text(json.dumps(data, indent=2))
    print(f"Wrote {len(data['posts'])} posts / {len(data['notebook_sites'])} sites -> {out}")
