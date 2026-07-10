"""
Controlled vocabularies and entity extraction for Lab Connector.

Everything here is keyword-driven and fully interpretable: given a blob of text
(a repo name + description + README, or a notebook slug + title + body) we detect
canonical species, methods, omics types, and recurring keywords by matching a
curated list of aliases with word-boundary regexes.

The vocabularies are intentionally editable -- add a term to a list and re-run
the pipeline. They can also be overridden from config.yaml (see load_config()).
"""
from __future__ import annotations
import re
from typing import Dict, List, Iterable

# --------------------------------------------------------------------------
# Controlled vocabularies.  Each entry maps a CANONICAL label -> list of
# aliases / surface forms.  Matching is case-insensitive and word-boundaried.
# --------------------------------------------------------------------------

SPECIES: Dict[str, List[str]] = {
    "Pacific oyster (Crassostrea/Magallana gigas)": [
        "crassostrea gigas", "magallana gigas", "c. gigas", "c.gigas",
        "cgigas", "gigas", "pacific oyster"],
    "Olympia oyster (Ostrea lurida)": [
        "ostrea lurida", "o. lurida", "olurida", "olympia oyster", "oly"],
    "Eastern oyster (Crassostrea virginica)": [
        "crassostrea virginica", "c. virginica", "virginica", "eastern oyster"],
    "Chilean oyster (Ostrea chilensis)": [
        "ostrea chilensis", "chilensis", "ostrea-chil"],
    "Geoduck (Panopea generosa)": [
        "panopea generosa", "p. generosa", "geoduck", "panopea", "generosa"],
    "Blue mussel (Mytilus spp.)": [
        "mytilus", "blue mussel", "myt-", "myt ", "myt-meth", "myt-crass"],
    "Manila clam / clam": ["manila clam", "ruditapes", "clam"],
    "Cockle": ["cockle"],
    "Pacific cod (Gadus macrocephalus)": ["gadus", "macrocephalus", "pacific cod", "cod"],
    "Lake trout (Salvelinus namaycush)": [
        "salvelinus", "namaycush", "lake trout", "trout"],
    "Sablefish (Anoplopoma fimbria)": ["anoplopoma", "sablefish"],
    "Dungeness crab (Metacarcinus magister)": ["dungeness"],
    "Tanner crab (Chionoecetes bairdi)": ["tanner crab", "chionoecetes", "tanner"],
    "Crab (general)": ["crab"],
    "Sunflower sea star (Pycnopodia helianthoides)": [
        "pycnopodia", "sunflower sea star", "sunflower star", "sea star", "seastar"],
    "Coral (E5 / reef corals)": [
        "coral", "acropora", "pocillopora", "montipora", "porites", "e5"],
    "Barnacle": ["barnacle"],
    "Hematodinium (parasite)": ["hematodinium"],
    "Sea louse (Caligus)": ["caligus", "rogercresseyi", "sea lice", "sea louse"],
    "Labyrinthula": ["labyrinthula", "laby-18s", "laby"],
}

METHODS: Dict[str, List[str]] = {
    "WGBS (whole-genome bisulfite seq)": ["wgbs", "whole genome bisulfite", "whole-genome bisulfite"],
    "Bisulfite / BS-seq": ["bisulfite", "bs-seq", "bsseq", "bismark"],
    "EM-seq": ["em-seq", "emseq"],
    "DNA methylation": ["methylation", "gene body methylation", "gene-meth", "myt-meth",
                        "gbm", "dna methylation", "methylome"],
    "RNA-seq": ["rna-seq", "rnaseq", "rna seq"],
    "Single-cell RNA-seq": ["single-cell", "single cell", "sc-rnaseq", "scrnaseq"],
    "ATAC-seq": ["atac-seq", "atacseq", "atac"],
    "Proteomics": ["proteomics", "proteome", "dia proteomics", "srm", "mrm"],
    "Metabolomics": ["metabolomics", "metabolome"],
    "Resazurin assay": ["resazurin"],
    "qPCR": ["qpcr", "rt-qpcr", "quantitative pcr"],
    "Differential expression": ["differential expression", "deseq", "edger", "dge", "limma"],
    "WGCNA": ["wgcna"],
    "Genome annotation": ["genome annotation", "annotation", "hisat", "stringtie", "gffread"],
    "Genome assembly / long-read": ["assembly", "nanopore", "nano-", "pacbio", "hifi", "flye"],
    "Genome browser": ["genome browser", "jbrowse", "igv"],
    "Orthology / synteny": ["ortholog", "orthofinder", "orthogroup", "synteny", "ortho-", "ortho "],
    "Liftover": ["lift-over", "liftover"],
    "SNP / variant calling": ["snp", "variant calling", "epidiverse"],
    "Metabarcoding / eDNA / taxonomy": ["edna", "18s", "metabarcoding", "megan", "metagenom", "taxonomy"],
    "Read mapping / alignment": ["bwa", "bowtie", "read mapping", "mapping", "minimap"],
    "Carbonate chemistry / titration": ["titrator", "titration", "carbonate chemistry"],
}

OMICS: Dict[str, List[str]] = {
    "Genomics": ["genome", "genomic", "assembly", "snp", "variant"],
    "Transcriptomics": ["rna-seq", "rnaseq", "transcriptome", "transcriptomic", "differential expression", "wgcna"],
    "Epigenomics": ["methylation", "wgbs", "bisulfite", "em-seq", "epigenetic", "gbm", "bismark"],
    "Proteomics": ["proteomics", "proteome"],
    "Metabolomics": ["metabolomics", "metabolome"],
    "Metagenomics": ["metagenom", "18s", "edna", "microbiome", "megan"],
}

# Recurring topical keywords worth surfacing as their own nodes.
KEYWORDS: List[str] = [
    "methylation", "rna-seq", "wgbs", "em-seq", "resazurin", "ocean acidification",
    "hardening", "conditioning", "carryover", "ploidy", "triploid", "diploid",
    "thermal", "temperature", "mortality", "larvae", "gonad", "biomineralization",
    "priming", "hatchery", "microbiome", "aquaculture", "desiccation",
    "genome browser", "synteny", "ortholog", "wgcna", "annotation", "nanopore",
    "klone", "hyak", "proteomics", "phenotype", "genome", "carbonate chemistry",
]

# Multi-token project cues -> canonical project label.
PROJECT_HINTS: Dict[str, List[str]] = {
    "Ocean Acidification (OA)": ["ocean acidification", "-oa", " oa ", "oa-", "acidification", "low ph"],
    "Gigas carryover (USDA Aquaculture)": ["carryover", "gigas-carryover", "usda aquaculture"],
    "10K seed hardening": ["10k", "10k-seed", "10k seed"],
    "SORMI": ["sormi"],
    "Manchester hardening": ["manchester"],
    "Priming / environmental memory": ["priming", "prime", "environmental memory"],
    "Coral E5 deep-dive": ["e5", "e5-orthologs", "e5-genome"],
    "Lake trout genome": ["lake-trout", "lake trout", "trout-synteny", "trout-lift", "trout-mapping"],
    "Mytilus methylation": ["mytilus-methylation", "myt-meth", "mytilus reboot"],
    "Resazurin assay development": ["resazurin"],
    "Geoduck proteomics (DNR)": ["dnr", "geoduck-eelgrass", "geoduck proteomics"],
    "Tanner crab / Hematodinium": ["tanner", "hematodinium"],
    "Biomineralization": ["biomin", "biomineralization"],
}


def _compile(alias: str) -> re.Pattern:
    """Word-boundary, case-insensitive matcher tolerant of - . spaces."""
    a = re.escape(alias.strip().lower())
    # allow the literal to be surrounded by non-word chars or string ends
    return re.compile(r"(?<![a-z0-9])" + a + r"(?![a-z0-9])", re.IGNORECASE)


_COMPILED = {
    "species": {canon: [_compile(x) for x in al] for canon, al in SPECIES.items()},
    "methods": {canon: [_compile(x) for x in al] for canon, al in METHODS.items()},
    "omics":   {canon: [_compile(x) for x in al] for canon, al in OMICS.items()},
    "keywords": {kw: [_compile(kw)] for kw in KEYWORDS},
    "projects": {canon: [_compile(x) for x in al] for canon, al in PROJECT_HINTS.items()},
}


def _match(text: str, group: str) -> List[str]:
    text = " " + (text or "").lower() + " "
    hits = []
    for canon, pats in _COMPILED[group].items():
        if any(p.search(text) for p in pats):
            hits.append(canon)
    return hits


def extract_species(text: str) -> List[str]:
    """Return canonical species, collapsing the generic 'Crab (general)' when a
    specific crab species is already present, and 'Coral' etc. stay as-is."""
    hits = _match(text, "species")
    specific_crab = {"Tanner crab (Chionoecetes bairdi)", "Dungeness crab (Metacarcinus magister)"}
    if "Crab (general)" in hits and (specific_crab & set(hits)):
        hits = [h for h in hits if h != "Crab (general)"]
    return hits


def extract_methods(text: str) -> List[str]:
    return _match(text, "methods")


def extract_omics(text: str) -> List[str]:
    return _match(text, "omics")


def extract_keywords(text: str) -> List[str]:
    return _match(text, "keywords")


def extract_projects(text: str) -> List[str]:
    return _match(text, "projects")


def extract_all(text: str) -> Dict[str, List[str]]:
    return {
        "species": extract_species(text),
        "methods": extract_methods(text),
        "omics": extract_omics(text),
        "keywords": extract_keywords(text),
        "projects": extract_projects(text),
    }


# --------------------------------------------------------------------------
# Repo-name tokenisation, used for notebook<->repo name-mention matching.
# --------------------------------------------------------------------------
_GENERIC_TOKENS = {
    "project", "paper", "poster", "repo", "data", "analysis", "dashboard",
    "assay", "development", "screenings", "seed", "control", "browser", "genome",
    "the", "and", "for", "with", "2020", "2021", "2022", "2023", "2024", "2025",
    "2026", "nsa", "oa", "meth",
}


def repo_key_tokens(name: str) -> List[str]:
    """Distinctive lowercased tokens from a repo name, dropping generic words."""
    toks = re.split(r"[-_.\s]+", name.lower())
    out = []
    for t in toks:
        if len(t) < 3 or t in _GENERIC_TOKENS:
            continue
        out.append(t)
    return out


def tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[-_.\s/]+", (text or "").lower()) if t]
