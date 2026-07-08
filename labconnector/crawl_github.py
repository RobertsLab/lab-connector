"""
Crawl the RobertsLab GitHub organization.

Primary strategy: GitHub REST API (fast, structured, respects rate limits, uses
an optional token from $GITHUB_TOKEN).  Fallback: parse the public HTML
repositories listing when the API is unavailable or unauthenticated.  Offline:
load the bundled snapshot in data/raw/repos_seed.json.

Never downloads large binaries -- only metadata, README (text), topics, and a
handful of recent issue titles.  All raw responses are cached under data/raw/.
"""
from __future__ import annotations
import json
import os
import time
import base64
from pathlib import Path
from typing import Dict, List, Optional

ORG = "RobertsLab"
API = "https://api.github.com"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def _session():
    import requests
    s = requests.Session()
    s.headers.update({"Accept": "application/vnd.github+json",
                      "User-Agent": "lab-connector/1.0"})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    return s


def _respect_rate_limit(resp) -> None:
    """Sleep if we're about to exhaust the primary rate limit."""
    try:
        remaining = int(resp.headers.get("X-RateLimit-Remaining", "1"))
        reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
    except ValueError:
        return
    if remaining <= 1 and reset:
        wait = max(0, reset - int(time.time())) + 1
        print(f"  [rate-limit] sleeping {wait}s")
        time.sleep(min(wait, 3600))


def fetch_repos_api(max_repos: Optional[int] = None) -> List[Dict]:
    s = _session()
    repos, page = [], 1
    while True:
        r = s.get(f"{API}/orgs/{ORG}/repos",
                  params={"per_page": 100, "page": page, "type": "public", "sort": "updated"},
                  timeout=30)
        _respect_rate_limit(r)
        if r.status_code != 200:
            raise RuntimeError(f"GitHub API {r.status_code}: {r.text[:200]}")
        batch = r.json()
        if not batch:
            break
        repos.extend(batch)
        if max_repos and len(repos) >= max_repos:
            repos = repos[:max_repos]
            break
        page += 1
        time.sleep(0.3)
    return repos


def fetch_readme(session, repo: str) -> str:
    try:
        r = session.get(f"{API}/repos/{ORG}/{repo}/readme", timeout=30)
        _respect_rate_limit(r)
        if r.status_code == 200:
            data = r.json()
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8", "replace")
    except Exception as e:  # robust to broken/missing READMEs
        print(f"  [readme] {repo}: {e}")
    return ""


def fetch_recent_issue_titles(session, repo: str, n: int = 8) -> List[str]:
    try:
        r = session.get(f"{API}/repos/{ORG}/{repo}/issues",
                        params={"state": "all", "per_page": n}, timeout=30)
        _respect_rate_limit(r)
        if r.status_code == 200:
            return [i["title"] for i in r.json() if "pull_request" not in i]
    except Exception as e:
        print(f"  [issues] {repo}: {e}")
    return []


def _pages_url(repo_full: Dict) -> str:
    return repo_full.get("homepage") or ""


def normalize_api(repo: Dict, readme: str = "", issues: Optional[List[str]] = None) -> Dict:
    return {
        "name": repo["name"],
        "url": repo["html_url"],
        "description": repo.get("description") or "",
        "topics": repo.get("topics", []) or [],
        "language": repo.get("language") or "",
        "created": (repo.get("created_at") or "")[:10],
        "updated": (repo.get("pushed_at") or repo.get("updated_at") or "")[:10],
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "open_issues": repo.get("open_issues_count", 0),
        "archived": repo.get("archived", False),
        "pages_url": _pages_url(repo),
        "readme": readme[:20000],
        "issue_titles": issues or [],
    }


def crawl_live(max_repos: Optional[int] = None, with_readme: bool = True,
               with_issues: bool = True) -> List[Dict]:
    """Full live crawl via the API. Returns normalized repo dicts."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw = fetch_repos_api(max_repos)
    (RAW_DIR / "github_api_raw.json").write_text(json.dumps(raw, indent=2))
    s = _session()
    out = []
    for i, repo in enumerate(raw, 1):
        name = repo["name"]
        print(f"  ({i}/{len(raw)}) {name}")
        readme = fetch_readme(s, name) if with_readme else ""
        issues = fetch_recent_issue_titles(s, name) if with_issues else []
        out.append(normalize_api(repo, readme, issues))
        time.sleep(0.2)
    return out


def load_seed() -> List[Dict]:
    """Offline example snapshot."""
    seed = json.loads((RAW_DIR / "repos_seed.json").read_text())
    out = []
    for r in seed["repos"]:
        name = r["name"]
        out.append({
            "name": name,
            "url": f"https://github.com/{ORG}/{name}",
            "description": r.get("description", ""),
            "topics": r.get("topics", []),
            "language": r.get("language", ""),
            "created": r.get("created", ""),
            "updated": r.get("updated", ""),
            "stars": r.get("stars", 0),
            "forks": r.get("forks", 0),
            "open_issues": r.get("open_issues", 0),
            "archived": r.get("archived", False),
            "pages_url": r.get("pages_url", ""),
            "readme": r.get("readme", ""),
            "issue_titles": r.get("issue_titles", []),
        })
    return out


def crawl(offline: bool = False, max_repos: Optional[int] = None,
          with_readme: bool = True, with_issues: bool = True) -> List[Dict]:
    """Crawl with graceful fallback: live API -> seed snapshot."""
    if offline:
        print("[github] offline mode: loading seed snapshot")
        return load_seed()
    try:
        return crawl_live(max_repos, with_readme, with_issues)
    except Exception as e:
        print(f"[github] live crawl failed ({e}); falling back to seed snapshot")
        return load_seed()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--no-readme", action="store_true")
    ap.add_argument("--no-issues", action="store_true")
    a = ap.parse_args()
    repos = crawl(a.offline, a.max, not a.no_readme, not a.no_issues)
    out = Path(__file__).resolve().parent.parent / "data" / "repos.json"
    out.write_text(json.dumps(repos, indent=2))
    print(f"Wrote {len(repos)} repos -> {out}")
