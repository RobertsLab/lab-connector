#!/usr/bin/env python3
"""Import Ariana Huffmyer's two lab notebooks into the offline seed.

Ariana keeps two notebooks:

1. Her current open lab notebook (Quarto), live at
   https://ahuffmyer.github.io/notebook.html, sources in
   ``.../Lab-Notebooks/notebooks/ahuffmyer.github.io`` (``posts/*.qmd``).
2. Her archived Putnam-Lab notebook (Jekyll), live at
   https://ahuffmyer.github.io/ASH_Putnam_Lab_Notebook/, sources in
   ``.../Lab-Notebooks/notebooks/ASH_Putnam_Lab_Notebook`` (``_posts/*.md``).

This script reads the *local* copies of both, extracts each post's
title / date / categories / body and any ``github.com/RobertsLab/<repo>``
links (which become confidence-1.0 ``links_to`` edges), and rewrites the
``ahuffmyer`` and ``ASH_Putnam_Lab_Notebook`` entries in
``data/raw/notebooks_seed.json``. Tumbling Oysters and Sam's Notebook entries
are left untouched.

Then rebuild the graph::

    python scripts/import_ariana_notebook.py
    python run_all.py --offline

Dependency-free: uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "raw" / "notebooks_seed.json"

# Local checkouts of Ariana's two notebooks (override with CLI flags).
DEFAULT_QUARTO = Path("/Users/sr320/Documents/Claude/Projects/Lab-Notebooks/"
                      "notebooks/ahuffmyer.github.io")
DEFAULT_ARCHIVE = Path("/Users/sr320/Documents/Claude/Projects/Lab-Notebooks/"
                       "notebooks/ASH_Putnam_Lab_Notebook")

AUTHOR = "Ariana Huffmyer"
QUARTO_SITE = {
    "id": "ahuffmyer", "title": "Ariana's Lab Notebook", "author": AUTHOR,
    "url": "https://ahuffmyer.github.io/notebook.html", "platform": "Quarto"}
ARCHIVE_SITE = {
    "id": "ASH_Putnam_Lab_Notebook", "title": "ASH Putnam Lab Notebook (Archive)",
    "author": AUTHOR, "url": "https://ahuffmyer.github.io/ASH_Putnam_Lab_Notebook/",
    "platform": "Jekyll"}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
# RobertsLab repo links only -- these are the ones that live in repos.json and
# so yield a confidence-1.0 links_to edge (matches connections.score_pair).
GH_RE = re.compile(r"github\.com/RobertsLab/([A-Za-z0-9._-]+)", re.IGNORECASE)
DATE_IN_NAME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    """Split a post into a (very small) YAML-ish front-matter dict and body.

    Only the flat ``key: value`` scalars we need are parsed; that is all these
    notebooks use for title/date/categories/tags/description.
    """
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val:
            meta[key.lower()] = val
    return meta, m.group(2)


def strip_markdown(body: str) -> str:
    body = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)          # code fences
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", body)                # images
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)             # links -> text
    body = re.sub(r"[#>*_`|~-]+", " ", body)                         # md punctuation
    body = html.unescape(body)
    return re.sub(r"\s+", " ", body).strip()


def _norm_categories(raw_meta: dict) -> str:
    """Categories are ``[a, b]`` (Quarto) or ``a b`` (Jekyll); tags similar."""
    parts: list[str] = []
    for key in ("categories", "tags"):
        val = raw_meta.get(key, "")
        val = val.strip().lstrip("[").rstrip("]")
        parts.extend(re.split(r"[,\s]+", val))
    return " ".join(p for p in parts if p)


def parse_quarto(path: Path) -> dict | None:
    slug = path.stem                                    # e.g. 2026-01-06-manchester
    meta, body = parse_frontmatter(path.read_text("utf-8", "replace"))
    title = meta.get("title") or slug.replace("-", " ")
    date = meta.get("date", "")
    if not date:
        dm = DATE_IN_NAME_RE.search(slug)
        date = dm.group(1) if dm else ""
    repos = sorted({r.rstrip(".") for r in GH_RE.findall(body)})
    cats = _norm_categories(meta)
    text = (cats + " . " + meta.get("description", "") + " . " + strip_markdown(body))[:8000]
    return {
        "site": QUARTO_SITE["id"], "author": AUTHOR, "slug": slug, "title": title,
        "url": f"https://ahuffmyer.github.io/posts/{slug}.html",
        "github_links": repos, "date": date, "text": text,
    }


def _archive_url(path: Path) -> str:
    # Jekyll permalink `/:title/` with baseurl `/ASH_Putnam_Lab_Notebook`; the
    # `:title` is the filename with the leading date stripped.
    title_slug = DATE_IN_NAME_RE.sub("", path.stem).lstrip("-")
    return f"https://ahuffmyer.github.io/ASH_Putnam_Lab_Notebook/{title_slug}/"


def parse_archive(path: Path) -> dict | None:
    slug = path.stem                                    # unique: date + title
    meta, body = parse_frontmatter(path.read_text("utf-8", "replace"))
    title = meta.get("title") or slug.replace("-", " ")
    date = meta.get("date", "").strip("'\"")
    if not date:
        dm = DATE_IN_NAME_RE.search(slug)
        date = dm.group(1) if dm else ""
    repos = sorted({r.rstrip(".") for r in GH_RE.findall(body)})
    cats = _norm_categories(meta)
    text = (cats + " . " + strip_markdown(body))[:8000]
    return {
        "site": ARCHIVE_SITE["id"], "author": AUTHOR, "slug": slug, "title": title,
        "url": _archive_url(path), "github_links": repos, "date": date, "text": text,
    }


def collect(quarto_dir: Path, archive_dir: Path) -> tuple[list[dict], list[dict]]:
    quarto: list[dict] = []
    qposts = quarto_dir / "posts"
    for p in sorted(qposts.glob("*.qmd")):
        if p.stem.startswith("_"):                      # _template.qmd etc.
            continue
        post = parse_quarto(p)
        if post:
            quarto.append(post)

    archive: list[dict] = []
    for p in sorted((archive_dir / "_posts").glob("*.md")):
        post = parse_archive(p)
        if post:
            archive.append(post)
    return quarto, archive


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quarto-dir", type=Path, default=DEFAULT_QUARTO,
                    help="local ahuffmyer.github.io checkout")
    ap.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE,
                    help="local ASH_Putnam_Lab_Notebook checkout")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing the seed")
    a = ap.parse_args()

    for d in (a.quarto_dir, a.archive_dir):
        if not d.exists():
            print(f"[import] missing source directory: {d}", file=sys.stderr)
            return 1

    quarto, archive = collect(a.quarto_dir, a.archive_dir)
    q_links = sum(1 for p in quarto if p["github_links"])
    a_links = sum(1 for p in archive if p["github_links"])
    print(f"[import] parsed {len(quarto)} Quarto posts ({q_links} with RobertsLab "
          f"links) + {len(archive)} archive posts ({a_links} with RobertsLab links)",
          file=sys.stderr)
    if not quarto and not archive:
        print("[import] nothing parsed; leaving seed unchanged", file=sys.stderr)
        return 1

    seed = json.loads(SEED.read_text())
    site_ids = {s["id"] for s in seed.get("notebook_sites", [])}
    for site in (QUARTO_SITE, ARCHIVE_SITE):
        if site["id"] not in site_ids:
            seed.setdefault("notebook_sites", []).append(site)

    replaced = {QUARTO_SITE["id"]: 0, ARCHIVE_SITE["id"]: 0}
    kept_posts = []
    for p in seed["posts"]:
        if p.get("site") in replaced:
            replaced[p["site"]] += 1
            continue
        kept_posts.append(p)
    seed["posts"] = kept_posts + quarto + archive
    seed["_meta"]["posts"] = len(seed["posts"])
    seed["_meta"]["notebook_sites"] = len(seed["notebook_sites"])
    seed["_meta"]["ariana_notebook_imported"] = __import__("datetime").date.today().isoformat()

    if a.dry_run:
        print(f"[dry-run] would replace {replaced} with "
              f"{len(quarto)} ahuffmyer + {len(archive)} archive posts "
              f"(seed total {len(seed['posts'])})", file=sys.stderr)
        return 0

    SEED.write_text(json.dumps(seed, indent=2))
    print(f"[import] wrote seed: +{len(quarto)} ahuffmyer +{len(archive)} archive "
          f"(replaced {replaced}). Now run: python run_all.py --offline",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
