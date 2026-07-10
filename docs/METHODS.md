# Methods note — how connections are inferred

This document explains, end to end, how Lab Connector turns two public web
sources into a scored relationship graph. The goal throughout is
**interpretability over complexity**: every node and edge can be traced back to
a specific piece of evidence and a source URL.

## 1. Sources and crawling

**GitHub organization** (`labconnector/crawl_github.py`). We prefer the GitHub
REST API (`/orgs/RobertsLab/repos`, paginated, 100/page, sorted by last update),
using `$GITHUB_TOKEN` when present. For each repo we additionally fetch the
README (`/readme`, base64-decoded) and up to eight recent issue titles. If the
API is unavailable or unauthenticated and rate-limited, the crawler falls back
to parsing the public HTML repositories listing, and finally to the offline
snapshot in `data/raw/repos_seed.json`. Rate-limit headers are honored
(`X-RateLimit-Remaining`/`Reset`); we sleep rather than hammer. No binaries are
downloaded — only text metadata.

**Notebook index** (`labconnector/crawl_notebooks.py`). Starting from
`notebooks.html`, we collect links to notebook sites (hosts matching
`github.io`/`notebook`). For each site we fetch the landing page, extract
`/posts/` links, and fetch each post body (bounded by `--max-posts` to stay
polite). From each post we pull outbound `github.com/RobertsLab/<repo>` links,
dates, and the visible text. All pages are cached under
`data/raw/notebooks_cache/` so re-runs are cheap and gentle on the servers. The
offline seed (`data/raw/notebooks_seed.json`) contains real posts from Tumbling
Oysters and Sam's Notebook — the latter carrying their inline
`github.com/RobertsLab` links — so the pipeline yields a meaningful graph
(including direct `links_to` edges) with no network.

## 2. Entity extraction

`labconnector/vocab.py` holds curated controlled vocabularies for **species**,
**methods**, **omics types**, **keywords**, and **project cues**. Each canonical
label maps to a list of surface forms/aliases (e.g. *Pacific oyster* ←
`crassostrea gigas`, `c. gigas`, `cgigas`, `gigas`, `pacific oyster`). Matching
is case-insensitive with word boundaries tolerant of `-`, `.`, and spaces, which
avoids substring false positives (e.g. `oa` inside `board`).

For every repo we build a text blob from name + description + topics + issue
titles + README; for every notebook post, from slug + title + body. We run the
same extractor over both, so a repo and a notebook are described in the same
vocabulary — which is what makes them comparable.

## 3. Structural (entity) edges

Whenever an entity is detected in an item's own text we emit a structural edge at
**confidence 0.9**:

- repo/notebook → species  (`studies_species`)
- repo/notebook → method   (`uses_method`)
- repo/notebook → omics    (`has_omics`)
- repo/notebook → keyword  (`shares_keyword`)
- repo/notebook → project  (`part_of_project`)
- notebook → person        (`authored_by`)
- repo/notebook → dataset  (`links_to`, when a known data host is referenced)

These are high-confidence by construction: the evidence is the detected term in
the item itself.

## 4. Inferred notebook⇄repo edges

For every (notebook post, repo) pair we compute the single **strongest**
relationship using this rubric (`labconnector/connections.py`):

| Score | Rule | Evidence recorded |
|------:|------|-------------------|
| 1.0 | Post body contains `github.com/RobertsLab/<repo>` | the linking URL |
| 0.8 | A distinctive repo token (curated `STRONG_TOKENS`) or ≥2 repo tokens appear in the post's slug/title/body | the matched token(s) |
| 0.6 | Post and repo share a project label, or the post links the repo's GitHub Pages URL | the shared project / page |
| 0.4 | Post and repo share a species **and** a method **and** ≥2 keywords | the shared entities |
| 0.2 | Any weaker keyword/species/method overlap | the overlapping terms — flagged `possible_connection` |

Only the highest applicable tier is emitted per pair, always with an evidence
string and both source URLs. **0.2 edges are explicitly non-confirmatory** and
routed to `outputs/possible_missing_connections.csv`.

Distinctive tokens (`STRONG_TOKENS`) are curated to avoid noise: matching
`sormi`, `mytilus`, `trout`, `manchester`, `geoduck`, etc. is meaningful, while
generic words (`project`, `data`, `analysis`, `oa`, `meth`) are stripped from
repo names before comparison (`vocab.repo_key_tokens`).

## 5. Graph assembly and metrics

`labconnector/graph.py` deduplicates nodes, attaches metadata, and computes each
node's **degree** (used for node size in the app). It writes `graph.json`
(and a `graph-data.js` copy for `file://` use), `nodes.csv`, `edges.csv`, and
`graph.graphml` for Gephi.

## 6. Summary analytics

The same module computes the reports in `outputs/` and `analysis_summary.json`,
answering:

- Which repos are most connected to notebooks? → `top_connected_repos.csv`
- Which notebooks mention the most repos? → `top_connected_notebooks.csv`
- Which repos/notebooks appear unlinked? → `unlinked_*.csv`
- Which species/methods bridge the most repos and notebooks? → `species_reach`,
  `method_reach`
- Which links are high-confidence (direct/name-mention) vs. need review? →
  `high_confidence_links`, `possible_missing_connections.csv`

## 7. Reproducibility and honesty

- Deterministic: same inputs → same graph.
- Cached: nothing is re-fetched unnecessarily.
- Traceable: every edge has evidence + URL.
- Bounded: `--max-repos` / `--max-posts` keep crawls polite.
- Transparent about uncertainty: heuristic scores are labelled, and weak links
  are never presented as confirmed.

### A note on the shipped example

The bundled example is built from real data captured on 2026-07-08: all public
RobertsLab repositories and 45 real Tumbling Oysters notebook posts. Because the
offline seed does not include full post *bodies*, it surfaces name-mention (0.8)
links rather than direct-URL (1.0) links. Running a live crawl
(`python run_all.py`) fetches post bodies and adds the 1.0 direct links.
