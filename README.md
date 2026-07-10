# Lab Connector

An interactive network map that connects **Roberts Lab GitHub repositories** with
**lab notebooks**, and surfaces the people, projects, species, methods, omics
types, keywords, and datasets that tie them together.

It crawls two public sources —

- Lab notebook index: <https://faculty.washington.edu/sr320/notebooks.html>
- RobertsLab GitHub org: <https://github.com/RobertsLab>

— extracts entities and relationships, scores each connection with a confidence
value and supporting evidence, and renders everything as a force-directed graph
you can explore in the browser.

> Open `app/index.html` to explore the live example graph (94 repos, 115 notebook
> posts across two notebooks — Steven Roberts' *Tumbling Oysters* and Sam White's
> *Sam's Notebook* — 298 nodes, 1,213 edges built from the sources above).

---

## What the tool does

1. **Crawls the notebook index** and each linked notebook site, extracting post
   titles, URLs, outbound GitHub links, dates, authors, and text.
2. **Crawls the RobertsLab GitHub organization** (REST API, with an HTML
   fallback), collecting name, description, topics, README, language, dates,
   stars/forks/issues, GitHub Pages URL, and recent issue titles.
3. **Detects notebook⇄repo connections** using several strategies (direct links,
   name mentions, shared projects, shared species/methods/keywords) and assigns
   each a **0–1 confidence score with evidence**.
4. **Builds a graph** of typed nodes and edges and exports it as JSON, CSV, and
   GraphML.
5. **Serves an interactive visualization** (`app/index.html`) with search,
   filters, node/edge detail panels, and export buttons.
6. **Generates summary reports** answering "which repos/notebooks/species/methods
   are most connected," "what is unlinked," and "which connections need review."

A ready-to-explore **example graph built from the two live sources** ships in
`data/` and `outputs/` — just open `app/index.html`.

---

## Quick start (example graph, no network)

```bash
python run_all.py --offline      # builds the graph from bundled real snapshots
open app/index.html              # macOS; or double-click the file
```

`--offline` uses `data/raw/repos_seed.json` (a snapshot of all public RobertsLab
repos) and `data/raw/notebooks_seed.json` (real posts from *Tumbling Oysters* and
*Sam's Notebook*, each carrying its direct `github.com/RobertsLab` links), so it
runs with only the Python standard library.

## Live crawl (fresh data)

```bash
python -m pip install -r requirements.txt
export GITHUB_TOKEN=ghp_xxx        # optional but recommended (raises rate limit)
python run_all.py                  # full crawl of org + notebooks
# bounded/polite crawl:
python run_all.py --max-repos 40 --max-posts 30
open app/index.html
```

## Refresh Sam's Notebook from the web

To pull the latest **Sam's Notebook** posts into the offline seed without a full
crawl, run the dedicated refresher (standard library only, no token needed):

```bash
python scripts/refresh_sams_notebook.py   # fetch recent posts from the live site
python run_all.py --offline               # rebuild the graph
open app/index.html
```

It scans the live site newest-first, keeps recent posts that carry a direct
`github.com/RobertsLab/<repo>` link (each yields a confidence-1.0 edge), and
rewrites only the `sams-notebook` entries in `data/raw/notebooks_seed.json`
(Tumbling Oysters entries are left untouched). The year cutoff follows the
calendar automatically; override or preview with:

```bash
python scripts/refresh_sams_notebook.py --since-year 2024   # go further back
python scripts/refresh_sams_notebook.py --dry-run           # report, don't write
```

### Optional GitHub token

A token is **not required** (the tool works on public data unauthenticated), but
setting `GITHUB_TOKEN` raises the API rate limit from 60 to 5,000 requests/hour.
Create a fine-grained token with **public read** scope only, then
`export GITHUB_TOKEN=...`. The token is read from the environment and never
written to disk.

## Launch the app

`app/index.html` is a single self-contained file (D3 from CDN). Two ways to open:

- **Double-click** it — the pipeline writes `app/graph-data.js`, which the page
  loads via `<script>` so it works from `file://`.
- **Serve it** for the cleanest experience:
  `python -m http.server` then visit <http://localhost:8000/app/>.

---

## Repository structure

```
Lab Connector/
├── run_all.py                 # end-to-end pipeline (crawl → detect → graph → export)
├── requirements.txt
├── config.yaml                # editable controlled-vocabulary reference
├── labconnector/
│   ├── vocab.py               # species/method/omics/keyword/project vocab + extraction
│   ├── crawl_github.py        # GitHub org crawler (API + HTML fallback + seed)
│   ├── crawl_notebooks.py     # notebook index + post crawler (+ seed)
│   ├── connections.py         # connection detection + confidence scoring
│   └── graph.py               # graph assembly, exports, summary analytics
├── app/
│   ├── index.html             # interactive D3 network map
│   └── graph-data.js          # generated: window.GRAPH for file:// use
├── data/
│   ├── raw/                   # cached crawl results + offline seeds
│   ├── repos.json  notebooks.json
│   ├── nodes.csv   edges.csv
│   ├── graph.json  graph.graphml
├── outputs/
│   ├── top_connected_repos.csv
│   ├── top_connected_notebooks.csv
│   ├── unlinked_repos.csv
│   ├── unlinked_notebooks.csv
│   ├── possible_missing_connections.csv
│   └── analysis_summary.json
├── docs/METHODS.md            # how connections are inferred
└── .github/workflows/refresh-graph.yml   # weekly auto-refresh
```

---

## The graph data model

**Node types:** `repo`, `notebook`, `person`, `project`, `species`, `method`,
`omics`, `keyword`, `dataset`.

**Edge types:** `links_to`, `mentions`, `authored_by`, `uses_method`,
`studies_species`, `part_of_project`, `shares_keyword`, `has_omics`,
`possible_connection`.

Every edge carries: `source`, `target`, `relationship`, `confidence` (0–1),
`evidence` (human-readable), and `source_url`/`target_url`.

Node **size** scales with the number of connections (degree); node **color**
encodes type.

---

## How to interpret edge confidence

| Score | Meaning | Edge type |
|------|---------|-----------|
| **1.0** | Notebook body links directly to `github.com/RobertsLab/<repo>` | `links_to` |
| **0.8** | A distinctive repo token (or ≥2 tokens) appears in the notebook text | `mentions` |
| **0.6** | Shared project name or shared GitHub Pages link | `part_of_project` / `links_to` |
| **0.4** | Shared species **and** method **and** ≥2 shared keywords | `shares_keyword` |
| **0.2** | Weak keyword/species/method overlap only | `possible_connection` |

Structural entity edges (a repo *studies* a species, *uses* a method, etc.) are
fixed at **0.9** because the entity was detected directly in the item's own text.

**Weak overlaps are never treated as confirmed.** They are labelled
`possible_connection`, shown as dashed grey edges, and collected in
`outputs/possible_missing_connections.csv` for human review. Use the
**confidence slider** in the app to hide everything below a threshold.

> Note: direct **1.0** links come from notebook *post bodies* linking to
> `github.com/RobertsLab/<repo>`. Sam's Notebook posts in the bundled seed carry
> their real inline links, so the offline example already includes 86 direct
> `links_to` edges; a live crawl surfaces these for every post body it fetches.

---

## Summary reports

After a run, see `outputs/`:

- **top_connected_repos.csv** — repos most linked to notebooks.
- **top_connected_notebooks.csv** — notebooks mentioning the most repos.
- **unlinked_repos.csv** — repos with no apparent notebook connection.
- **unlinked_notebooks.csv** — notebooks with no apparent repo connection.
- **possible_missing_connections.csv** — low-confidence links to review.
- **analysis_summary.json** — machine-readable rollups (species/method reach,
  high-confidence links, counts), also shown live in the app's Summary panel.

---

## Extending the vocabularies

All entity detection is keyword-driven and interpretable. To add a species,
method, keyword, or project cue, edit the lists in `labconnector/vocab.py`
(mirrored for reference in `config.yaml`) and re-run the pipeline. No model
retraining, no hidden state.

---

## Export & downstream use

From the app: **Graph JSON**, **Edges CSV**, **SVG**, and **PNG** buttons.
From disk: `data/graph.graphml` opens directly in **Gephi** for advanced layout
and clustering.

---

## Known limitations

- **JS-rendered notebook indexes.** Some Quarto/Jekyll listings load post cards
  via JavaScript; the plain crawler sees static HTML. The bundled notebook seed
  uses real posts captured from the Tumbling Oysters notebook so the example is
  complete; a live crawl covers whatever static links are present.
- **Name-mention heuristics** can over- or under-match. Distinctive tokens are
  curated in `connections.STRONG_TOKENS`; tune as needed.
- **Confidence is heuristic, not ground truth.** Treat 0.2 edges as leads.
- **Rate limits.** Unauthenticated GitHub access is limited; set `GITHUB_TOKEN`
  for full crawls.
- **No large files.** Only metadata, README text, and issue titles are fetched;
  binaries and data files are never downloaded.
- **Public data only.** No private credentials are required or used.

---

## License / attribution

Built for the Roberts Lab. Uses only public data from the sources above. See
`docs/METHODS.md` for the full methodology.
