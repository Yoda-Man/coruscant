"""
coruscant.core.script_manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Offline, privacy-preserving SQL support-script discovery engine.

No LLMs. No external APIs. No pre-trained models. No telemetry.

Algorithm overview
------------------
1. **Parse** every .sql file from a user-supplied zip: extract filename tokens,
   ``-- @tag:`` comment headers, SQL command patterns, table references, and
   PostgreSQL error codes.  Terms are weighted by source (comment 5x, filename
   3x, SQL body 1x).

2. **Build** a NetworkX knowledge graph whose nodes are scripts and terms.
   Edges carry TF-IDF weights (script→term), PMI co-occurrence weights
   (term→term), and Jaccard similarity weights (script→script).  PageRank and
   Louvain/greedy-modularity community detection produce per-node authority
   scores and topic clusters.

3. **Search** via a lightweight multi-factor scorer:
     40% term coverage · 30% IDF importance · 20% PageRank authority
     10% community relevance · recency/severity multipliers

All data lives in ``~/.local/share/Coruscant/scripts/`` (or platform
equivalent).  A 500-script graph compresses to ≈ 10 MB on disk and loads
in < 200 ms.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import gc
import gzip
import hashlib
import json
import logging
import math
import os
import re
import sys
import tempfile
import time
import zipfile
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

try:
    import networkx as nx
    _NX_AVAILABLE = True
except ImportError:
    nx = None  # type: ignore[assignment]
    _NX_AVAILABLE = False

log = logging.getLogger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────── #

_GRAPH_FILENAME   = "script_graph.json.gz"
_MAX_FILE_BYTES   = 10 * 1024 * 1024   # skip scripts larger than 10 MB
_TRUNCATE_BYTES   = 512 * 1024          # store at most 512 KB per script
_MIN_TERM_LEN     = 3
_MIN_PMI          = 1.5
_MIN_COOCCURRENCE = 2
_MIN_JACCARD      = 0.3
_MAX_RESULTS      = 20

# ── Stop-word sets ────────────────────────────────────────────────────── #

_SYNTAX_SW = frozenset({
    "select","from","where","and","or","not","in","exists","join","left",
    "right","inner","outer","on","as","with","group","by","order","having",
    "limit","offset","distinct","case","when","then","else","end","set",
    "into","values","is","null","true","false","between","like","ilike",
    "all","union","intersect","except","begin","commit","rollback",
    "returning","using","over","partition","window","filter","rows",
    "following","preceding","unbounded","current","row","range","next",
    "fetch","only","natural","cross","full","first","last",
})

_DOMAIN_SW = frozenset({
    "fix","issue","problem","script","run","execute","use","check","show",
    "get","find","make","need","want","help","the","this","that","for",
    "how","can","will","should","see","also","note","above","below",
    "example","result","output","value","file","list","each","every",
    "some","new","old","previous","name","type","time","date","year",
    "day","hour","used","database","postgres","postgresql","sql","query",
    "version","num","number","given","based","per","via","etc","your",
    "our","its","has","had","have","may","been","were","was","are","into",
})

_STOPWORDS = _SYNTAX_SW | _DOMAIN_SW

# ── Synonym expansion dictionary ─────────────────────────────────────── #

_SYNONYMS: dict[str, list[str]] = {
    "deadlock":    ["deadlock","blocked","lock","waiting","stuck","hang","lockwait","pg_locks"],
    "blocked":     ["blocked","deadlock","lock","waiting","lockwait","pg_locks"],
    "vacuum":      ["vacuum","bloat","cleanup","freeze","autovacuum","reclaim","dead_tuples","toast"],
    "bloat":       ["bloat","vacuum","dead_tuples","table_bloat","index_bloat","pg_toast"],
    "slow":        ["slow","performance","latency","timeout","bottleneck","optimize","tuning"],
    "performance": ["performance","slow","latency","optimize","tuning","bottleneck"],
    "connection":  ["connection","session","backend","idle","pid","pg_stat_activity"],
    "idle":        ["idle","connection","session","backend","pid","terminate"],
    "index":       ["index","reindex","btree","scan","seqscan","missing"],
    "memory":      ["memory","cache","buffer","shared_buffers","work_mem"],
    "disk":        ["disk","tablespace","storage","bloat","pg_size"],
    "crash":       ["crash","corruption","recovery","wal","checkpoint","panic"],
    "lock":        ["lock","deadlock","blocked","exclusive","pg_locks"],
    "size":        ["size","bloat","space","disk","pg_size_pretty","pg_relation_size"],
    "kill":        ["kill","terminate","cancel","pg_terminate_backend","pg_cancel_backend"],
    "stat":        ["stat","statistics","pg_stat","activity","monitoring"],
    "analyze":     ["analyze","statistics","autovacuum","planner"],
    "backup":      ["backup","dump","restore","pg_dump","pitr"],
    "replica":     ["replica","replication","standby","wal","streaming"],
    "log":         ["log","logging","audit","csvlog","stderr"],
    "permission":  ["permission","role","grant","revoke","privilege","acl"],
    "error":       ["error","exception","fail","critical","panic"],
    "freeze":      ["freeze","vacuum","wraparound","xid","multixact"],
    "wraparound":  ["wraparound","freeze","vacuum","xid"],
    "replication": ["replication","replica","standby","wal","streaming"],
    "wal":         ["wal","replication","checkpoint","archive","pg_wal"],
    "checkpoint":  ["checkpoint","wal","bgwriter","pg_stat_bgwriter"],
    "autovacuum":  ["autovacuum","vacuum","analyze","bloat","dead_tuples"],
    "pg_stat_activity": ["pg_stat_activity","connection","session","backend","pid","idle"],
    "pg_locks":    ["pg_locks","lock","deadlock","blocked","waiting"],
}

# ── Data structures ───────────────────────────────────────────────────── #

@dataclass
class ParsedScript:
    """All information extracted from a single .sql file."""
    __slots__ = (
        "filename", "path", "content", "checksum",
        "terms", "metadata", "commands", "tables", "error_codes",
    )
    filename:    str                   # basename e.g. "fix_deadlock.sql"
    path:        str                   # path inside zip
    content:     str                   # raw SQL text (may be truncated)
    checksum:    str                   # SHA-256[:16] for dedup
    terms:       dict[str, float]      # term → weighted score
    metadata:    dict[str, str]        # @desc, @fixes, @requires, @tables, @date
    commands:    list[str]             # SQL command types found
    tables:      list[str]             # table/relation names
    error_codes: list[str]             # PostgreSQL SQLSTATE codes


@dataclass
class SearchResult:
    """A single ranked result from a search query."""
    __slots__ = ("script_id","filename","score","matched_terms","preview","community","path")
    script_id:     str
    filename:      str
    score:         float
    matched_terms: list[str]
    preview:       str           # first ~200 characters of content
    community:     int
    path:          str


@dataclass
class GraphStats:
    """Summary statistics for the loaded graph."""
    script_count:  int = 0
    term_count:    int = 0
    cluster_count: int = 0
    last_indexed:  str = ""

# ── Script parser ─────────────────────────────────────────────────────── #

# Patterns compiled once at import time
_TAG_RE      = re.compile(r"--\s*@(\w+)\s*:\s*(.+)", re.IGNORECASE)
_TABLE_RE    = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO|TABLE|TRUNCATE|DROP\s+TABLE)\s+"
    r"(?:IF\s+EXISTS\s+)?([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
    re.IGNORECASE,
)
_CMD_RE      = re.compile(
    r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|VACUUM|"
    r"REINDEX|CLUSTER|ANALYZE|EXPLAIN|GRANT|REVOKE|CALL|DO)\b",
    re.IGNORECASE | re.MULTILINE,
)
_ERRCODE_RE  = re.compile(r"\b([0-9][0-9A-Z]{4})\b")
_FUNC_RE     = re.compile(r"\b(pg_[a-z_]+)\s*\(", re.IGNORECASE)
_WORD_RE     = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{2,}")


class SQLScriptParser:
    """
    Parse a single SQL file into a ParsedScript.
    Uses only regex and string matching — no external libraries.
    """

    def parse_content(self, filename: str, content: str, path: str = "") -> ParsedScript:
        checksum = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]
        stored   = content[:_TRUNCATE_BYTES]
        meta     = self._extract_metadata(content)
        cmds, tables, codes, funcs = self._extract_sql_patterns(content)
        terms    = self._extract_terms(filename, stored, meta, tables, funcs)
        # Add error codes as terms (high weight — very specific)
        for code in codes:
            terms[code] = max(terms.get(code, 0), 4.0)
        return ParsedScript(
            filename=filename, path=path, content=stored, checksum=checksum,
            terms=terms, metadata=meta, commands=cmds, tables=tables,
            error_codes=codes,
        )

    # ── Private helpers ─────────────────────────────────────────────── #

    @staticmethod
    def _extract_metadata(content: str) -> dict[str, str]:
        meta: dict[str, str] = {}
        for m in _TAG_RE.finditer(content):
            tag, val = m.group(1).lower(), m.group(2).strip()
            meta[tag] = val
        return meta

    def _extract_sql_patterns(
        self, content: str
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        cmds   = list({m.group(1).upper() for m in _CMD_RE.finditer(content)})
        tables = []
        seen_t: set[str] = set()
        for m in _TABLE_RE.finditer(content):
            t = m.group(1).lower()
            if t not in seen_t and not t.isdigit():
                tables.append(t); seen_t.add(t)
        codes = list({m.group(1) for m in _ERRCODE_RE.finditer(content)
                      if len(m.group(1)) == 5})
        funcs = list({m.group(1).lower() for m in _FUNC_RE.finditer(content)})
        return cmds, tables[:30], codes, funcs

    def _extract_terms(
        self,
        filename: str,
        content: str,
        meta: dict[str, str],
        tables: list[str],
        funcs: list[str],
    ) -> dict[str, float]:
        terms: dict[str, float] = {}

        def _add(word: str, weight: float) -> None:
            w = word.lower().strip("_-.")
            if (len(w) >= _MIN_TERM_LEN and w not in _STOPWORDS
                    and not w.isdigit() and not re.fullmatch(r"v?\d[\d.]+", w)):
                terms[w] = max(terms.get(w, 0.0), weight)

        # Filename tokens (weight 3)
        stem = re.sub(r"\.(sql|txt)$", "", filename, flags=re.IGNORECASE)
        for tok in re.split(r"[_\-.\s]+", stem):
            _add(tok, 3.0)

        # @desc and @fixes tags (weight 5)
        for tag in ("desc", "fixes", "keywords", "about"):
            if tag in meta:
                for w in _WORD_RE.findall(meta[tag]):
                    _add(w, 5.0)

        # @requires (weight 3)
        if "requires" in meta:
            for w in _WORD_RE.findall(meta["requires"]):
                _add(w, 3.0)

        # @tables tag (weight 4)
        if "tables" in meta:
            for w in re.split(r"[,\s]+", meta["tables"]):
                _add(w, 4.0)

        # Extracted table references (weight 2)
        for t in tables:
            for part in t.split("."):
                _add(part, 2.0)

        # pg_* function names (weight 3 — very specific)
        for f in funcs:
            _add(f, 3.0)
            # Also add the meaningful part: pg_terminate_backend → terminate, backend
            for part in f.split("_")[1:]:
                _add(part, 2.0)

        # SQL body words (weight 1)
        # Strip comment lines first to avoid polluting body terms
        body_lines = [
            ln for ln in content.splitlines()
            if not ln.strip().startswith("--")
        ]
        body = " ".join(body_lines)
        # Deduplicate within body (count each word only once)
        for w in set(_WORD_RE.findall(body)):
            _add(w, 1.0)

        return terms


# ── Knowledge graph ───────────────────────────────────────────────────── #

class ScriptKnowledgeGraph:
    """
    NetworkX-backed knowledge graph for script discovery.

    Build phase   → constructs graph, runs PageRank + community detection,
                    precomputes inverted index and IDF scores.
    Search phase  → pure dict lookups against precomputed structures (<50 ms).
    Persistence   → gzip-compressed JSON in the user's app-data directory.
    """

    def __init__(self) -> None:
        self._scripts:  dict[str, dict[str, Any]] = {}    # id → script dict
        self._inv:      dict[str, list[str]]       = {}    # term → [script_ids]
        self._idf:      dict[str, float]           = {}    # term → IDF
        self._pr:       dict[str, float]           = {}    # script_id → PageRank
        self._comm:     dict[str, int]             = {}    # node_key → community
        self._built:    bool                       = False
        self._cache:    dict[str, list[SearchResult]] = {}
        self._cache_q:  list[str]                  = []    # FIFO for LRU eviction

    # ── Ingestion ────────────────────────────────────────────────────── #

    def add_scripts(
        self,
        scripts: list[ParsedScript],
        merge: bool = True,
    ) -> tuple[int, int]:
        """
        Add parsed scripts.  Returns (added, skipped_as_duplicate).
        If merge=False the existing collection is replaced.
        """
        if not merge:
            self._scripts.clear()
        existing_checksums = {v["checksum"] for v in self._scripts.values()}
        added = dupes = 0
        for s in scripts:
            if s.checksum in existing_checksums:
                dupes += 1
                continue
            self._scripts[s.checksum] = {
                "filename": s.filename, "path": s.path,
                "content": s.content, "checksum": s.checksum,
                "terms": s.terms, "metadata": s.metadata,
                "commands": s.commands, "tables": s.tables,
                "error_codes": s.error_codes,
            }
            existing_checksums.add(s.checksum)
            added += 1
        self._built = False
        self._cache.clear()
        return added, dupes

    def build(self, progress_cb: Callable[[str, int, int], None] | None = None) -> None:
        """
        (Re)build TF-IDF, graph, PageRank, communities, and inverted index.
        Call after add_scripts() and before search().
        """
        if not _NX_AVAILABLE:
            raise RuntimeError(
                "networkx is required for graph construction.\n"
                "Install it with:  pip install networkx"
            )

        cb = progress_cb or (lambda *_: None)
        scripts = list(self._scripts.values())
        N = len(scripts)
        if N == 0:
            self._built = True
            return

        # ── Step 1: TF and DF ──────────────────────────────────────── #
        cb("Computing term frequencies…", 0, N)
        df: dict[str, int] = defaultdict(int)        # term → doc_count
        tf_by_script: dict[str, dict[str, float]] = {}

        for i, sc in enumerate(scripts):
            sid   = sc["checksum"]
            twts  = sc["terms"]   # {term: weight}
            total = sum(twts.values()) or 1.0
            tf_by_script[sid] = {t: w / total for t, w in twts.items()}
            for t in twts:
                df[t] += 1
            if i % 10 == 0:
                cb("Computing term frequencies…", i, N)

        # ── Step 2: IDF ────────────────────────────────────────────── #
        self._idf = {
            t: math.log((1.0 + N) / (1.0 + d)) + 1.0
            for t, d in df.items()
        }

        # ── Step 3: TF-IDF per (script, term) ─────────────────────── #
        tfidf: dict[str, dict[str, float]] = {}
        for sid, tf in tf_by_script.items():
            tfidf[sid] = {t: v * self._idf[t] for t, v in tf.items()}

        # ── Step 4: Build NetworkX graph ───────────────────────────── #
        cb("Building knowledge graph…", 0, N)
        G = nx.Graph()

        for i, sc in enumerate(scripts):
            sid = sc["checksum"]
            G.add_node(f"S_{sid}", kind="script", id=sid,
                       filename=sc["filename"])
            for t, score in tfidf[sid].items():
                G.add_node(f"T_{t}", kind="term", term=t)
                G.add_edge(f"S_{sid}", f"T_{t}",
                           rel="mentions", weight=score)
            if i % 10 == 0:
                cb("Building knowledge graph…", i, N)

        # ── Step 5: Script-Script edges (Jaccard) ─────────────────── #
        cb("Computing script similarities…", 0, N)
        sids = [sc["checksum"] for sc in scripts]
        for i in range(len(sids)):
            for j in range(i + 1, len(sids)):
                a, b = sids[i], sids[j]
                ta   = set(self._scripts[a]["terms"])
                tb   = set(self._scripts[b]["terms"])
                union = len(ta | tb)
                if union == 0:
                    continue
                jac = len(ta & tb) / union
                if jac >= _MIN_JACCARD:
                    G.add_edge(f"S_{a}", f"S_{b}",
                               rel="related", weight=jac)

        # ── Step 6: Term-Term edges (PMI) ─────────────────────────── #
        cb("Computing term co-occurrences…", 0, N)
        cooccur: dict[tuple[str, str], int] = defaultdict(int)
        for sc in scripts:
            terms_in_doc = list(sc["terms"].keys())
            for ii in range(len(terms_in_doc)):
                for jj in range(ii + 1, len(terms_in_doc)):
                    key = tuple(sorted([terms_in_doc[ii], terms_in_doc[jj]]))
                    cooccur[key] += 1  # type: ignore[index]

        for (t1, t2), co in cooccur.items():
            if co < _MIN_COOCCURRENCE:
                continue
            d1, d2 = df.get(t1, 1), df.get(t2, 1)
            pmi = math.log((co * N) / (d1 * d2))
            if pmi >= _MIN_PMI:
                G.add_edge(f"T_{t1}", f"T_{t2}",
                           rel="cooccurs", weight=pmi)

        # ── Step 7: PageRank ───────────────────────────────────────── #
        cb("Running PageRank…", 0, 1)
        try:
            pr_raw = nx.pagerank(G, alpha=0.85, max_iter=100, weight="weight")
        except Exception:
            pr_raw = {n: 1.0 / len(G) for n in G.nodes}
        max_pr = max(pr_raw.values()) if pr_raw else 1.0
        self._pr = {
            n.removeprefix("S_"): v / max_pr
            for n, v in pr_raw.items()
            if n.startswith("S_")
        }

        # ── Step 8: Community detection ────────────────────────────── #
        cb("Detecting topic clusters…", 0, 1)
        try:
            # Louvain (networkx >= 2.8) or greedy fallback
            if hasattr(nx.community, "louvain_communities"):
                communities = nx.community.louvain_communities(G, weight="weight", seed=42)
            else:
                communities = nx.community.greedy_modularity_communities(G, weight="weight")
        except Exception as exc:
            log.debug("Community detection skipped: %s", exc)
            communities = []

        self._comm = {}
        for cid, nodes in enumerate(communities):
            for n in nodes:
                self._comm[n] = cid

        # ── Step 9: Inverted index ─────────────────────────────────── #
        cb("Building search index…", 0, N)
        inv: dict[str, list[str]] = defaultdict(list)
        for sc in scripts:
            sid = sc["checksum"]
            for t in sc["terms"]:
                inv[t].append(sid)
        self._inv = dict(inv)

        self._built = True
        self._cache.clear()
        del G; del cooccur; del tf_by_script; del tfidf
        gc.collect()
        cb("Complete!", N, N)

    # ── Search ───────────────────────────────────────────────────────── #

    def search(self, query: str, max_results: int = _MAX_RESULTS) -> list[SearchResult]:
        """Return up to *max_results* scripts ranked by relevance."""
        if not self._built:
            raise RuntimeError("Call build() before search().")
        if not query.strip():
            return []

        cache_key = f"{query.strip().lower()}:{max_results}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        original_terms = self._parse_query(query)
        if not original_terms:
            return []
        expanded_terms = self._expand_query(original_terms)

        # Gather candidates
        candidates: dict[str, set[str]] = defaultdict(set)
        for term in expanded_terms:
            for sid in self._inv.get(term, []):
                candidates[sid].add(term)
            # Also check term substrings for partial matching
            for idx_term, sids in self._inv.items():
                if len(term) >= 4 and idx_term.startswith(term[:4]) and idx_term != term:
                    for sid in sids:
                        candidates[sid].add(term)

        if not candidates:
            return []

        # Score candidates
        results: list[SearchResult] = []
        for sid, matched in candidates.items():
            if sid not in self._scripts:
                continue
            score, explanation = self._score(sid, list(matched), expanded_terms, original_terms)
            if score <= 0:
                continue
            sc = self._scripts[sid]
            preview = self._make_preview(sc["content"])
            results.append(SearchResult(
                script_id=sid,
                filename=sc["filename"],
                score=round(score, 4),
                matched_terms=sorted(explanation),
                preview=preview,
                community=self._comm.get(f"S_{sid}", -1),
                path=sc["path"],
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        out = results[:max_results]

        # LRU cache (keep last 50)
        if len(self._cache_q) >= 50:
            evict = self._cache_q.pop(0)
            self._cache.pop(evict, None)
        self._cache[cache_key] = out
        self._cache_q.append(cache_key)
        return out

    # ── Scoring ──────────────────────────────────────────────────────── #

    def _score(
        self,
        sid: str,
        matched: list[str],
        expanded: list[str],
        original: list[str],
    ) -> tuple[float, list[str]]:
        if not expanded:
            return 0.0, []

        unique_expanded = set(expanded)
        unique_matched  = set(matched) & unique_expanded

        # 1. Term coverage (40%)
        coverage = len(unique_matched) / len(unique_expanded) if unique_expanded else 0.0

        # 2. IDF importance (30%)
        total_idf   = sum(self._idf.get(t, 0.0) for t in unique_expanded)
        matched_idf = sum(self._idf.get(t, 0.0) for t in unique_matched)
        importance  = matched_idf / total_idf if total_idf > 0 else 0.0

        # 3. PageRank authority (20%)
        authority = self._pr.get(sid, 0.0)  # already 0-1 normalised

        # 4. Community relevance (10%)
        script_comm = self._comm.get(f"S_{sid}", -1)
        query_comms = {self._comm.get(f"T_{t}", -1) for t in original}
        community_boost = 1.0 if (script_comm >= 0 and script_comm in query_comms) else 0.0

        base = 0.40 * coverage + 0.30 * importance + 0.20 * authority + 0.10 * community_boost

        # 5. Recency multiplier
        recency = self._recency_mult(self._scripts[sid]["metadata"].get("date", ""))

        # 6. Severity multiplier (fix queries → data-modifying scripts rank higher)
        severity = self._severity_mult(set(original), self._scripts[sid]["commands"])

        final = base * recency * severity
        explanation = [t for t in original if t in unique_matched] or list(unique_matched)[:5]
        return final, explanation

    @staticmethod
    def _recency_mult(date_str: str) -> float:
        if not date_str:
            return 1.0
        try:
            dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
            age = (datetime.now() - dt).days
            return 1.2 if age <= 90 else 1.1 if age <= 365 else 1.0
        except ValueError:
            return 1.0

    @staticmethod
    def _severity_mult(query_words: set[str], commands: list[str]) -> float:
        fix_words = {"fix","repair","resolve","terminate","kill","stop","clear","remove","reset"}
        if not query_words & fix_words:
            return 1.0
        mod_cmds = {"DELETE","TRUNCATE","UPDATE","DROP","VACUUM","REINDEX",
                    "CLUSTER","ALTER","TERMINATE","CANCEL"}
        return 1.15 if any(c.upper() in mod_cmds for c in commands) else 1.0

    # ── Query processing ─────────────────────────────────────────────── #

    @staticmethod
    def _parse_query(query: str) -> list[str]:
        # Keep known compound terms as single tokens
        compounds = [
            "pg_stat_activity","pg_locks","pg_terminate_backend","pg_cancel_backend",
            "table_bloat","index_bloat","dead_tuples","transaction_wraparound",
            "shared_buffers","work_mem","autovacuum",
        ]
        q = query.lower()
        preserved: list[str] = []
        for c in compounds:
            if c in q:
                preserved.append(c)
                q = q.replace(c, " ")
        words = [w.lower() for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", q)
                 if len(w) >= _MIN_TERM_LEN and w.lower() not in _STOPWORDS]
        # PostgreSQL error codes (e.g. 40P01)
        codes = re.findall(r"\b([0-9][0-9A-Z]{4})\b", query)
        return preserved + words + codes

    @staticmethod
    def _expand_query(terms: list[str]) -> list[str]:
        seen:   set[str] = set()
        result: list[str] = []
        for t in terms:
            for syn in [t] + _SYNONYMS.get(t, []):
                if syn not in seen:
                    seen.add(syn); result.append(syn)
        return result

    # ── Utilities ────────────────────────────────────────────────────── #

    @staticmethod
    def _make_preview(content: str) -> str:
        lines = [ln for ln in content.splitlines() if ln.strip()][:5]
        preview = " | ".join(ln.strip() for ln in lines)
        return preview[:200] + ("…" if len(preview) > 200 else "")

    def stats(self) -> GraphStats:
        n_clusters = len({v for v in self._comm.values() if v >= 0})
        ts = ""
        # Use latest @date from scripts as "last indexed"
        dates = [sc["metadata"].get("date","") for sc in self._scripts.values() if sc["metadata"].get("date")]
        if dates:
            ts = max(dates)
        else:
            ts = datetime.now().strftime("%Y-%m-%d") if self._built else ""
        return GraphStats(
            script_count  = len(self._scripts),
            term_count    = len(self._idf),
            cluster_count = n_clusters,
            last_indexed  = ts,
        )

    # ── Persistence ──────────────────────────────────────────────────── #

    def save(self, path: Path | None = None) -> Path:
        """Serialize to gzip-compressed JSON.  Returns the saved path."""
        target = path or self.default_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema":  "1.0",
            "saved":   datetime.now().isoformat(timespec="seconds"),
            "scripts": self._scripts,
            "idf":     self._idf,
            "pr":      self._pr,
            "comm":    self._comm,
            "inv":     self._inv,
        }
        with gzip.open(target, "wt", encoding="utf-8", compresslevel=6) as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        log.info("Saved script graph → %s  (%d scripts)", target, len(self._scripts))
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> "ScriptKnowledgeGraph":
        """Load a previously saved graph.  Returns an empty graph if not found."""
        target = path or cls.default_path()
        g = cls()
        if not target.exists():
            return g
        try:
            with gzip.open(target, "rt", encoding="utf-8") as fh:
                data = json.load(fh)
            g._scripts = data.get("scripts", {})
            g._idf     = data.get("idf", {})
            g._pr      = data.get("pr", {})
            g._comm    = data.get("comm", {})
            g._inv     = data.get("inv", {})
            g._built   = bool(g._idf)
            log.info("Loaded script graph ← %s  (%d scripts)", target, len(g._scripts))
        except Exception as exc:
            log.warning("Failed to load script graph: %s", exc)
        return g

    @staticmethod
    def default_path() -> Path:
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home()))
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
        return base / "Coruscant" / "scripts" / _GRAPH_FILENAME


# ── Ingester ──────────────────────────────────────────────────────────── #

class ScriptIngester:
    """
    Orchestrates zip extraction, parsing, graph building, and persistence.

    The progress_cb signature is:
        callback(stage: str, current: int, total: int) -> None
    """

    def __init__(self) -> None:
        self._parser = SQLScriptParser()

    def ingest_zip(
        self,
        zip_path: str | Path,
        existing_graph: ScriptKnowledgeGraph | None = None,
        progress_cb: Callable[[str, int, int], None] | None = None,
        merge: bool = True,
        save_path: Path | None = None,
    ) -> ScriptKnowledgeGraph:
        """
        Parse all .sql files in *zip_path* and return a built graph.

        If *existing_graph* is supplied and *merge* is True, new scripts are
        added to it rather than replacing the collection.
        """
        cb = progress_cb or (lambda *_: None)
        cb("Extracting zip file…", 0, 1)

        raw_files = self._extract_from_zip(zip_path, cb)
        if not raw_files:
            raise ValueError("No .sql files found in the zip archive.")

        total = len(raw_files)
        cb(f"Found {total} SQL file(s). Parsing…", 0, total)

        parsed: list[ParsedScript] = []
        for i, (fname, fpath, content) in enumerate(raw_files):
            try:
                ps = self._parser.parse_content(fname, content, fpath)
                parsed.append(ps)
            except Exception as exc:
                log.warning("Skipped %s: %s", fname, exc)
            cb(f"Parsing script {i + 1} of {total}…", i + 1, total)

        graph = existing_graph if (existing_graph and merge) else ScriptKnowledgeGraph()
        added, dupes = graph.add_scripts(parsed, merge=merge)
        log.info("Ingested: added=%d  dupes=%d", added, dupes)

        cb("Building knowledge graph…", 0, 1)
        graph.build(progress_cb)
        graph.save(save_path)
        return graph

    @staticmethod
    def _extract_from_zip(
        zip_path: str | Path,
        cb: Callable[[str, int, int], None],
    ) -> list[tuple[str, str, str]]:
        """Return list of (filename, zip_path, content) for every .sql file."""
        results: list[tuple[str, str, str]] = []
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                sql_entries = [
                    e for e in zf.infolist()
                    if not e.is_dir()
                    and e.filename.lower().endswith(".sql")
                    and e.file_size <= _MAX_FILE_BYTES
                ]
                total = len(sql_entries)
                cb(f"Found {total} SQL file(s). Extracting…", 0, total)
                for i, entry in enumerate(sql_entries):
                    try:
                        raw = zf.read(entry.filename)
                        try:
                            content = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            content = raw.decode("latin-1", errors="replace")
                        fname = Path(entry.filename).name
                        results.append((fname, entry.filename, content))
                    except Exception as exc:
                        log.warning("Could not read %s: %s", entry.filename, exc)
                    cb("Extracting…", i + 1, total)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"Zip file is corrupted: {exc}") from exc
        return results
