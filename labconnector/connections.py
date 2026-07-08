"""
Connection detection + confidence scoring.

We build two kinds of edges:

1. ENTITY edges (structural): repo/notebook -> species, method, omics, keyword,
   project, and notebook -> person (author).  These are high-confidence by
   construction (the entity was detected in the item's own text).

2. NOTEBOOK <-> REPO edges (inferred): scored 0.2 - 1.0 using the rubric below.
   Only the single strongest relationship is emitted per notebook/repo pair,
   always with human-readable evidence and a source URL.

Confidence rubric
-----------------
  1.0  direct URL link   : notebook body links to github.com/RobertsLab/<repo>
  0.8  exact name mention : a distinctive repo token (or >=2 tokens) appears in
                            the notebook slug/title/body
  0.6  shared project / GitHub Pages link
  0.4  shared species AND method AND >=2 shared keywords
  0.2  weak keyword/species/method overlap only  -> type = possible_connection

Anything at 0.2 is explicitly labelled `possible_connection` and must not be
treated as confirmed.
"""
from __future__ import annotations
from typing import Dict, List, Tuple
from . import vocab

# Curated distinctive tokens that, on their own, justify a name-mention edge.
STRONG_TOKENS = {
    "sormi", "manchester", "mytilus", "myt", "geoduck", "trout", "cod",
    "hematodinium", "tanner", "dungeness", "resazurin", "caligus", "barnacle",
    "pycnopodia", "sablefish", "virginica", "lurida", "olurida", "cockle",
    "clam", "biomin", "wgcna", "bismark", "hisat", "megan", "klone", "e5",
    "priming", "prime", "10k", "cgigas", "synteny", "ortholog", "eelgrass",
    "microbiome", "xenobiotic", "sc-rnaseq", "caligus", "polyic", "labyrinthula",
}


def enrich_repos(repos: List[Dict]) -> List[Dict]:
    for r in repos:
        blob = " ".join([r.get("name", "").replace("-", " ").replace("_", " "),
                         r.get("description", ""),
                         " ".join(r.get("topics", [])),
                         " ".join(r.get("issue_titles", [])),
                         r.get("readme", "")])
        r["entities"] = vocab.extract_all(blob)
        r["key_tokens"] = vocab.repo_key_tokens(r.get("name", ""))
    return repos


def _shared(a: List[str], b: List[str]) -> List[str]:
    sa = set(a or [])
    return [x for x in (b or []) if x in sa]


def score_pair(post: Dict, repo: Dict) -> Tuple[float, str, str, Dict]:
    """Return (confidence, relationship, evidence, shared_entities)."""
    pe, re_ = post.get("entities", {}), repo.get("entities", {})
    shared = {
        "species": _shared(pe.get("species"), re_.get("species")),
        "methods": _shared(pe.get("methods"), re_.get("methods")),
        "keywords": _shared(pe.get("keywords"), re_.get("keywords")),
        "projects": _shared(pe.get("projects"), re_.get("projects")),
    }

    # 1.0 -- direct URL link
    if repo["name"] in (post.get("github_links") or []):
        return (1.0, "links_to",
                f"Notebook post '{post['slug']}' links directly to "
                f"github.com/RobertsLab/{repo['name']}", shared)

    # 0.8 -- name mention
    post_tokens = set(vocab.tokenize(" ".join(
        [post.get("slug", ""), post.get("title", ""), post.get("text", "")])))
    repo_tokens = repo.get("key_tokens", [])
    strong_hits = [t for t in repo_tokens if t in post_tokens and t in STRONG_TOKENS]
    all_hits = [t for t in repo_tokens if t in post_tokens]
    if strong_hits or len(all_hits) >= 2:
        toks = strong_hits or all_hits
        return (0.8, "mentions",
                f"Notebook '{post['slug']}' mentions repo token(s) "
                f"{', '.join(sorted(set(toks)))} matching '{repo['name']}'", shared)

    # 0.6 -- shared project (or GitHub Pages link, when available)
    if shared["projects"]:
        return (0.6, "part_of_project",
                f"Shared project: {', '.join(shared['projects'])}", shared)
    pages = repo.get("pages_url", "")
    if pages and pages in (post.get("text") or ""):
        return (0.6, "links_to", f"Notebook links to repo GitHub Pages {pages}", shared)

    # 0.4 -- species AND method AND >=2 keywords
    if shared["species"] and shared["methods"] and len(shared["keywords"]) >= 2:
        return (0.4, "shares_keyword",
                f"Shared species ({', '.join(shared['species'])}), "
                f"method ({', '.join(shared['methods'])}) and keywords "
                f"({', '.join(shared['keywords'])})", shared)

    # 0.2 -- weak overlap only
    weak = shared["species"] + shared["methods"] + shared["keywords"]
    if weak:
        return (0.2, "possible_connection",
                f"Weak overlap: {', '.join(sorted(set(weak)))}", shared)

    return (0.0, "", "", shared)


def detect(repos: List[Dict], posts: List[Dict]) -> List[Dict]:
    edges = []
    for post in posts:
        pid = f"notebook:{post['site']}/{post['slug']}"
        for repo in repos:
            conf, rel, ev, shared = score_pair(post, repo)
            if conf <= 0:
                continue
            edges.append({
                "source": pid,
                "target": f"repo:{repo['name']}",
                "relationship": rel,
                "confidence": conf,
                "evidence": ev,
                "source_url": post.get("url", ""),
                "target_url": repo.get("url", ""),
                "shared": shared,
            })
    return edges
