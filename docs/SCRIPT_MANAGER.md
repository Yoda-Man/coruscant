# Support Script Manager

**Version:** 1.0.0  
**Author:** Marwa Trust Mutemasango

---

## Overview

The Support Script Manager lets you upload a ZIP archive of SQL maintenance scripts and find the right one using plain English — no database access, no internet connection, and no AI required.

Everything runs entirely on your machine using a statistical knowledge graph built from TF-IDF scores, pointwise mutual information (PMI) co-occurrence, PageRank authority, and community detection.

---

## Quick Start

1. Click **📜 Scripts** in the Schema Browser panel.
2. Click **⬆ Upload Scripts ZIP** and select a `.zip` file containing your `.sql` scripts.
3. Wait for the progress bar to complete (typically < 5 seconds for 100 scripts).
4. Type into the search box: `fix deadlock` or `table bloat` or `40P01`.
5. Double-click any result to load the script into the active SQL editor.

---

## How to Format Your Scripts for Best Results

The search engine extracts metadata from three sources, weighted in priority order:

| Source | Weight | Example |
|---|---|---|
| `-- @tag:` comment headers | 5× | `-- @fixes: deadlock, blocked` |
| Filename tokens | 3× | `fix_deadlock.sql` → "fix", "deadlock" |
| SQL body text | 1× | `pg_stat_activity`, `VACUUM` |

### Recommended Script Header

Add these comment tags at the top of each script:

```sql
-- @desc:     Brief description of what this script does
-- @fixes:    problem1, problem2, problem3
-- @requires: pg_stat_statements
-- @tables:   pg_locks, pg_stat_activity
-- @date:     2026-01-15

-- Your SQL starts here
SELECT pid, query, state
FROM pg_stat_activity
WHERE wait_event_type = 'Lock';
```

### Tag Reference

| Tag | Purpose | Example |
|---|---|---|
| `@desc` | One-line description of the script | `-- @desc: Kills idle blocking connections` |
| `@fixes` | Comma-separated problem keywords | `-- @fixes: deadlock, lock_wait, idle` |
| `@requires` | Prerequisites or extensions needed | `-- @requires: pg_stat_statements` |
| `@tables` | Tables/views the script touches | `-- @tables: pg_locks, pg_stat_activity` |
| `@date` | Script date (YYYY-MM-DD) for recency boost | `-- @date: 2026-01-15` |

### Naming Tips

| Good | Bad | Why |
|---|---|---|
| `fix_deadlock.sql` | `script1.sql` | Filename tokens are indexed |
| `vacuum_table_bloat.sql` | `maintenance.sql` | Specific > generic |
| `kill_idle_connections.sql` | `temp.sql` | Describes the action |
| `emergency_kill_long_tx.sql` | `s.sql` | Includes urgency and domain |

---

## Search Query Guide

### Natural Language Queries

| Query | What the engine does |
|---|---|
| `fix deadlock` | Expands "deadlock" to: blocked, lock, waiting, stuck, pg_locks |
| `table bloat` | Expands "bloat" to: vacuum, dead_tuples, autovacuum, pg_toast |
| `slow queries` | Expands "slow" to: performance, latency, timeout, bottleneck |
| `kill idle connections` | Expands each term; "kill" triggers severity boost for destructive scripts |
| `vacuum freeze wraparound` | Multi-term query; scripts matching more terms rank higher |

### Error Code Queries

Type a PostgreSQL SQLSTATE code directly:

```
40P01           → deadlock detected
57014           → query cancelled
23505           → unique constraint violation
53300           → too many connections
```

Scripts that mention the error code in their `-- @fixes:` header or body will be returned first.

### Table-Focused Queries

```
pg_stat_activity
pg_locks
pg_stat_statements
```

Scripts that reference the table in SQL body, `@tables`, or `@requires` will rank highly.

---

## Scoring Algorithm

Each result is scored using five factors:

| Factor | Weight | Description |
|---|---|---|
| Term Coverage | 40% | Fraction of query terms matched |
| IDF Importance | 30% | Rare, distinctive terms score higher than common ones |
| PageRank Authority | 20% | Scripts connected to many important terms rank higher |
| Community Relevance | 10% | Bonus when script belongs to the same topic cluster as the query |
| Recency Multiplier | ×1.0–1.2 | Scripts with `@date` within 90 days get a small boost |
| Severity Multiplier | ×1.0–1.15 | Fix/kill queries prefer scripts that use DELETE/TRUNCATE/TERMINATE |

---

## Adding More Scripts

Upload additional ZIP files at any time. When prompted, choose:

- **Merge** — add new scripts to your existing collection (recommended)
- **Replace** — clear everything and re-index from the new ZIP only

Identical scripts (same content, different filename) are de-duplicated automatically.

---

## Storage and Privacy

| Item | Location |
|---|---|
| Windows | `%APPDATA%\Coruscant\scripts\script_graph.json.gz` |
| macOS | `~/Library/Application Support/Coruscant/scripts/script_graph.json.gz` |
| Linux | `~/.local/share/Coruscant/scripts/script_graph.json.gz` |

- **No internet access** — the entire engine is local
- **No telemetry** — your scripts never leave your machine
- **No code execution** — scripts are analysed as text only
- **Compressed storage** — a 500-script graph is typically < 10 MB

---

## Error-Driven Suggestions

When a SQL query fails with a PostgreSQL error code, Coruscant will automatically search your loaded scripts for relevant help. A notification appears in the status bar; clicking it opens the Script Manager with the error code pre-filled in the search box.

---

## Performance

| Operation | Target |
|---|---|
| Ingest 100 scripts | < 5 seconds |
| Graph load at startup | < 200 ms |
| Search query | < 50 ms |
| Memory footprint (500 scripts) | < 100 MB |

---

## Troubleshooting

**"My script is never found"**  
Add a `-- @fixes:` header with the key terms you expect to search for.

**"Wrong scripts appear first"**  
Use more specific terms. Generic words like "fix", "problem", "script" are filtered as stopwords.

**"Search is slow"**  
Reduce the collection size. Split into separate ZIPs for different topic areas.

**"Graph file corrupted"**  
Click **🗑 Clear All** in the Script Manager to delete the saved graph, then re-upload.

**"networkx not installed"**  
Run: `pip install networkx>=2.6`

---

## Developer Notes

The engine lives entirely in `coruscant/core/script_manager.py`:

| Class | Responsibility |
|---|---|
| `SQLScriptParser` | Extracts terms, metadata, and SQL patterns from a single file |
| `ScriptKnowledgeGraph` | Builds the graph, computes PageRank and communities, answers queries |
| `ScriptIngester` | Orchestrates ZIP extraction → parsing → graph build → save |
| `ParsedScript` | Data-only dataclass for one parsed script |
| `SearchResult` | Data-only dataclass for one search result |

The graph is stored as a gzip-compressed JSON document. It is built once during ingestion, then loaded into memory at startup. No NetworkX graph object persists between sessions — only the precomputed inverted index, IDF scores, PageRank values, and community assignments are serialised.
