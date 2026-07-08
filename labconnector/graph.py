"""
Assemble nodes + edges into a graph, export every deliverable, and compute the
analysis summaries.

Node types : repo, notebook, person, project, species, method, omics, keyword, dataset
Edge types : links_to, mentions, authored_by, uses_method, studies_species,
             part_of_project, shares_keyword, has_omics, possible_connection

Outputs written:
  data/nodes.csv, data/edges.csv, data/graph.json, data/graph.graphml
  outputs/top_connected_repos.csv
  outputs/top_connected_notebooks.csv
  outputs/unlinked_repos.csv
  outputs/unlinked_notebooks.csv
  outputs/possible_missing_connections.csv
  outputs/analysis_summary.json
"""
from __future__ import annotations
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from . import connections as conn

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "outputs"

STRUCTURAL_CONF = 0.9
DATASET_HOSTS = ["gannet", "owl", "raven", "eagle", "osf.io", "figshare",
                 "zenodo", "ncbi", "/sra", "gigas-data", "srx", "biosample"]

ENTITY_EDGE = {
    "species": ("studies_species", "species"),
    "methods": ("uses_method", "method"),
    "omics": ("has_omics", "omics"),
    "keywords": ("shares_keyword", "keyword"),
    "projects": ("part_of_project", "project"),
}


def _nid(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def build(repos: List[Dict], notebooks: Dict) -> Dict:
    posts = notebooks["posts"]
    sites = {s["id"]: s for s in notebooks["notebook_sites"]}
    repos = conn.enrich_repos(repos)

    nodes: Dict[str, Dict] = {}
    edges: List[Dict] = []

    def add_node(nid, label, ntype, **meta):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": label, "type": ntype, "degree": 0, **meta}
        else:
            nodes[nid].update({k: v for k, v in meta.items() if v})

    def add_edge(src, tgt, rel, conf, ev, surl="", turl=""):
        edges.append({"source": src, "target": tgt, "relationship": rel,
                      "confidence": round(conf, 2), "evidence": ev,
                      "source_url": surl, "target_url": turl})

    # ---- repo nodes + entity edges ----
    for r in repos:
        rid = _nid("repo", r["name"])
        add_node(rid, r["name"], "repo", url=r["url"], description=r.get("description", ""),
                 language=r.get("language", ""), updated=r.get("updated", ""),
                 created=r.get("created", ""), stars=r.get("stars", 0),
                 forks=r.get("forks", 0), open_issues=r.get("open_issues", 0),
                 pages_url=r.get("pages_url", ""))
        for grp, (rel, ntype) in ENTITY_EDGE.items():
            for val in r["entities"].get(grp, []):
                nid = _nid(ntype, val)
                add_node(nid, val, ntype)
                add_edge(rid, nid, rel, STRUCTURAL_CONF,
                         f"Detected '{val}' in repo '{r['name']}' text", r["url"])
        # dataset nodes from readme/description text
        blob = (r.get("readme", "") + " " + r.get("description", "")).lower()
        for host in DATASET_HOSTS:
            if host in blob:
                did = _nid("dataset", host.strip("/"))
                add_node(did, host.strip("/"), "dataset")
                add_edge(rid, did, "links_to", STRUCTURAL_CONF,
                         f"Repo '{r['name']}' references dataset host '{host}'", r["url"])

    # ---- notebook (post) nodes + entity/person edges ----
    for p in posts:
        pid = _nid("notebook", f"{p['site']}/{p['slug']}")
        site = sites.get(p["site"], {})
        add_node(pid, p.get("title") or p["slug"], "notebook", url=p.get("url", ""),
                 site=p["site"], site_title=site.get("title", p["site"]),
                 author=p.get("author", ""), date=p.get("date", ""))
        # author
        if p.get("author"):
            per = _nid("person", p["author"])
            add_node(per, p["author"], "person")
            add_edge(pid, per, "authored_by", STRUCTURAL_CONF,
                     f"Post '{p['slug']}' authored by {p['author']}", p.get("url", ""))
        for grp, (rel, ntype) in ENTITY_EDGE.items():
            for val in p.get("entities", {}).get(grp, []):
                nid = _nid(ntype, val)
                add_node(nid, val, ntype)
                add_edge(pid, nid, rel, STRUCTURAL_CONF,
                         f"Detected '{val}' in notebook '{p['slug']}'", p.get("url", ""))
        for gh in p.get("github_links", []):
            rid = _nid("repo", gh)
            if rid in nodes:
                continue  # handled by inferred edges below

    # ---- inferred notebook <-> repo edges ----
    for e in conn.detect(repos, posts):
        add_edge(e["source"], e["target"], e["relationship"], e["confidence"],
                 e["evidence"], e["source_url"], e["target_url"])

    # ---- degree ----
    for e in edges:
        if e["source"] in nodes:
            nodes[e["source"]]["degree"] += 1
        if e["target"] in nodes:
            nodes[e["target"]]["degree"] += 1

    return {"nodes": list(nodes.values()), "links": edges}


# ------------------------------------------------------------------ exports
def _w(path, rows, header):
    with open(path, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=header)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: r.get(k, "") for k in header})


def export(graph: Dict) -> Dict:
    DATA.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    nodes, links = graph["nodes"], graph["links"]

    (DATA / "graph.json").write_text(json.dumps(graph, indent=2))
    # Also emit a JS-wrapped copy so app/index.html works when opened directly
    # via file:// (browsers block fetch() of local files, but allow <script src>).
    (ROOT / "app" / "graph-data.js").write_text(
        "window.GRAPH = " + json.dumps(graph) + ";\n")

    _w(DATA / "nodes.csv", nodes,
       ["id", "label", "type", "degree", "url", "language", "updated",
        "stars", "forks", "open_issues", "author", "site", "date", "description"])
    _w(DATA / "edges.csv", links,
       ["source", "target", "relationship", "confidence", "evidence",
        "source_url", "target_url"])

    _export_graphml(graph, DATA / "graph.graphml")

    # ---------------- summary analytics ----------------
    nb = {n["id"] for n in nodes if n["type"] == "notebook"}
    rp = {n["id"] for n in nodes if n["type"] == "repo"}
    node_by_id = {n["id"]: n for n in nodes}

    repo_nb_links = defaultdict(list)   # repo -> [notebook edges]
    nb_repo_links = defaultdict(list)   # notebook -> [repo edges]
    for e in links:
        if e["source"] in nb and e["target"] in rp:
            repo_nb_links[e["target"]].append(e)
            nb_repo_links[e["source"]].append(e)

    top_repos = sorted(rp, key=lambda r: len(repo_nb_links[r]), reverse=True)
    top_repos_rows = [{
        "repo": node_by_id[r]["label"],
        "notebook_connections": len(repo_nb_links[r]),
        "max_confidence": max([e["confidence"] for e in repo_nb_links[r]], default=0),
        "url": node_by_id[r].get("url", ""),
        "example_notebooks": "; ".join(sorted({node_by_id[e["source"]]["label"]
                                               for e in repo_nb_links[r]})[:5]),
    } for r in top_repos if repo_nb_links[r]]
    _w(OUT / "top_connected_repos.csv", top_repos_rows,
       ["repo", "notebook_connections", "max_confidence", "example_notebooks", "url"])

    top_nb = sorted(nb, key=lambda n: len(nb_repo_links[n]), reverse=True)
    top_nb_rows = [{
        "notebook": node_by_id[n]["label"],
        "repo_connections": len(nb_repo_links[n]),
        "url": node_by_id[n].get("url", ""),
        "example_repos": "; ".join(sorted({node_by_id[e["target"]]["label"]
                                           for e in nb_repo_links[n]})[:5]),
    } for n in top_nb if nb_repo_links[n]]
    _w(OUT / "top_connected_notebooks.csv", top_nb_rows,
       ["notebook", "repo_connections", "example_repos", "url"])

    unlinked_repos = [{"repo": node_by_id[r]["label"], "url": node_by_id[r].get("url", ""),
                       "description": node_by_id[r].get("description", ""),
                       "updated": node_by_id[r].get("updated", "")}
                      for r in rp if not repo_nb_links[r]]
    _w(OUT / "unlinked_repos.csv", unlinked_repos, ["repo", "updated", "description", "url"])

    unlinked_nb = [{"notebook": node_by_id[n]["label"], "url": node_by_id[n].get("url", ""),
                    "author": node_by_id[n].get("author", "")}
                   for n in nb if not nb_repo_links[n]]
    _w(OUT / "unlinked_notebooks.csv", unlinked_nb, ["notebook", "author", "url"])

    possible = [{
        "notebook": node_by_id[e["source"]]["label"],
        "repo": node_by_id[e["target"]]["label"],
        "confidence": e["confidence"], "evidence": e["evidence"],
        "notebook_url": e["source_url"], "repo_url": e["target_url"],
    } for e in links if e["relationship"] == "possible_connection"]
    possible.sort(key=lambda x: x["confidence"])
    _w(OUT / "possible_missing_connections.csv", possible,
       ["notebook", "repo", "confidence", "evidence", "notebook_url", "repo_url"])

    # species / method reach
    def reach(ntype):
        out = []
        for n in nodes:
            if n["type"] != ntype:
                continue
            r = sum(1 for e in links if (e["source"] == n["id"] and node_by_id.get(e["target"], {}).get("type") == "repo")
                    or (e["target"] == n["id"] and node_by_id.get(e["source"], {}).get("type") == "repo"))
            nbc = sum(1 for e in links if (e["source"] == n["id"] and node_by_id.get(e["target"], {}).get("type") == "notebook")
                      or (e["target"] == n["id"] and node_by_id.get(e["source"], {}).get("type") == "notebook"))
            out.append({"label": n["label"], "repos": r, "notebooks": nbc, "total": r + nbc})
        return sorted(out, key=lambda x: x["total"], reverse=True)

    analysis = {
        "counts": {
            "nodes": len(nodes), "edges": len(links),
            "repos": len(rp), "notebooks": len(nb),
            "by_type": {t: sum(1 for n in nodes if n["type"] == t)
                        for t in sorted({n["type"] for n in nodes})},
        },
        "top_connected_repos": top_repos_rows[:15],
        "top_connected_notebooks": top_nb_rows[:15],
        "unlinked_repo_count": len(unlinked_repos),
        "unlinked_notebook_count": len(unlinked_nb),
        "species_reach": reach("species")[:15],
        "method_reach": reach("method")[:15],
        "high_confidence_links": [
            {"notebook": node_by_id[e["source"]]["label"],
             "repo": node_by_id[e["target"]]["label"],
             "confidence": e["confidence"], "relationship": e["relationship"],
             "evidence": e["evidence"]}
            for e in sorted(links, key=lambda x: -x["confidence"])
            if e["source"] in nb and e["target"] in rp and e["confidence"] >= 0.8][:25],
        "possible_connection_count": len(possible),
    }
    (OUT / "analysis_summary.json").write_text(json.dumps(analysis, indent=2))
    return analysis


def _export_graphml(graph: Dict, path: Path) -> None:
    """Minimal GraphML for Gephi (no external deps)."""
    def esc(x):
        return (str(x).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
             '<key id="label" for="node" attr.name="label" attr.type="string"/>',
             '<key id="type" for="node" attr.name="type" attr.type="string"/>',
             '<key id="degree" for="node" attr.name="degree" attr.type="int"/>',
             '<key id="rel" for="edge" attr.name="relationship" attr.type="string"/>',
             '<key id="conf" for="edge" attr.name="confidence" attr.type="double"/>',
             '<graph edgedefault="undirected">']
    for n in graph["nodes"]:
        lines.append(f'<node id="{esc(n["id"])}">'
                     f'<data key="label">{esc(n["label"])}</data>'
                     f'<data key="type">{esc(n["type"])}</data>'
                     f'<data key="degree">{int(n.get("degree",0))}</data></node>')
    for i, e in enumerate(graph["links"]):
        lines.append(f'<edge id="e{i}" source="{esc(e["source"])}" target="{esc(e["target"])}">'
                     f'<data key="rel">{esc(e["relationship"])}</data>'
                     f'<data key="conf">{e["confidence"]}</data></edge>')
    lines += ["</graph>", "</graphml>"]
    path.write_text("\n".join(lines))
