#!/usr/bin/env python3
"""
Lab Connector -- end-to-end pipeline.

Usage
-----
  python run_all.py --offline          # build the example graph from bundled seed
  python run_all.py                     # live crawl (uses $GITHUB_TOKEN if set)
  python run_all.py --max-repos 40 --max-posts 30   # bounded live crawl

Steps: crawl GitHub -> crawl notebooks -> detect connections -> build graph ->
export data/ + outputs/.  Then open app/index.html in a browser.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from labconnector import crawl_github, crawl_notebooks, graph

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description="Build the Lab Connector network map.")
    ap.add_argument("--offline", action="store_true",
                    help="use bundled seed snapshots (no network)")
    ap.add_argument("--max-repos", type=int, default=None,
                    help="cap number of repos (live crawl)")
    ap.add_argument("--max-posts", type=int, default=40,
                    help="cap notebook posts per site (live crawl)")
    ap.add_argument("--no-readme", action="store_true", help="skip README fetch")
    ap.add_argument("--no-issues", action="store_true", help="skip issue titles")
    a = ap.parse_args()

    print("== Lab Connector ==")
    print("[1/4] Crawling RobertsLab GitHub organization ...")
    repos = crawl_github.crawl(offline=a.offline, max_repos=a.max_repos,
                               with_readme=not a.no_readme, with_issues=not a.no_issues)
    (ROOT / "data" / "repos.json").write_text(json.dumps(repos, indent=2))
    print(f"      {len(repos)} repos")

    print("[2/4] Crawling lab notebooks ...")
    notebooks = crawl_notebooks.crawl(offline=a.offline, max_posts_per_site=a.max_posts)
    (ROOT / "data" / "notebooks.json").write_text(json.dumps(notebooks, indent=2))
    print(f"      {len(notebooks['posts'])} posts / {len(notebooks['notebook_sites'])} sites")

    print("[3/4] Detecting connections + building graph ...")
    g = graph.build(repos, notebooks)
    print(f"      {len(g['nodes'])} nodes / {len(g['links'])} edges")

    print("[4/4] Exporting data/ and outputs/ ...")
    analysis = graph.export(g)
    print(json.dumps(analysis["counts"], indent=2))
    print("\nDone. Open app/index.html in a browser to explore the network map.")


if __name__ == "__main__":
    main()
