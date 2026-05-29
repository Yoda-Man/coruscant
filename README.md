# Coruscant: PostgreSQL Multi-Query Tool

<p align="center">
  <img src="docs/coruscant3.png" alt="Coruscant — PostgreSQL Multi-Query Tool" width="600">
</p>

**Version:** 1.0.0  
**Author:** Marwa Trust Mutemasango

> *Named after the galactic capital of Star Wars — a city-planet that is essentially one giant information hub.*

A lightweight, open-source desktop SQL IDE for PostgreSQL built with Python and PySide6.  
Run multiple statements in one pass, browse your schema, manage transactions, search your script library, and export results — all in a single window.

---

## Why Coruscant Exists

pgAdmin has a long-standing limitation: when a script contains multiple `SELECT` statements, only the last result is shown. Earlier result sets are silently discarded.

Coruscant solves this directly. Every `SELECT` produces its own dedicated, persistent result tab. Run twenty statements, inspect any of the twenty results, pin the ones you want to keep, and compare them side by side — all without leaving the window.

---

## What Makes This Project Good

**Separate result tab per statement** is the core feature. Three `SELECT`s produce three independently sortable, filterable, exportable grids.

**Clean layered architecture:** `core/` has zero GUI imports. The SQL parser, database manager, and background worker can all be tested without a running Qt application. `MainWindow` is a pure coordinator — it wires signals but contains no SQL logic.

**Background execution with real cancellation:** queries run in a `QThread` worker; the UI never freezes. Cancel sends `pg_cancel_backend()` to PostgreSQL — the *server* stops the query, not just the client.

**Inline errors, no modal dialogs:** failed statements open an `ErrorResult` tab alongside successful ones. Read the error, fix the SQL, re-run — your other results stay visible.

**Transactional DDL:** switching off Auto-commit lets you `CREATE TABLE`, inspect the result, and roll the whole thing back. PostgreSQL supports this; Coruscant exposes it properly.

**Parameterised queries done right:** values pass through `cursor.mogrify()` — never string-concatenated. SQL injection is structurally impossible when the Parameters panel is used.

**Offline script search:** the Support Script Manager indexes your SQL script collections into a statistical knowledge graph (TF-IDF + PageRank + community detection) and answers natural-language queries like "fix deadlock" or "table bloat" — entirely offline, no LLM required.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Building a Standalone Executable](#building-a-standalone-executable)
4. [Quick Start](#quick-start)
5. [Architecture](#architecture)
6. [Connecting to a Database](#connecting-to-a-database)
7. [The Editor](#the-editor)
8. [Running Queries](#running-queries)
9. [Result Tabs](#result-tabs)
10. [Transaction Mode](#transaction-mode)
11. [Schema Browser](#schema-browser)
12. [Support Script Manager](#support-script-manager)
13. [Query History](#query-history)
14. [Parameterised Queries](#parameterised-queries)
15. [EXPLAIN / EXPLAIN ANALYZE](#explain--explain-analyze)
16. [Exporting Results](#exporting-results)
17. [Keyboard Shortcuts](#keyboard-shortcuts)
18. [Themes](#themes)
19. [Logging](#logging)
20. [Security Notes](#security-notes)
21. [Known Limitations](#known-limitations)
22. [Changelog](#changelog)

---

## Requirements

**Pre-built binaries** require no Python. Only a running PostgreSQL server (9.x – 16+) is needed.

**Running from source:**

| Dependency | Minimum version | Notes |
|---|---|---|
| Python | 3.10 | Uses modern type annotations |
| PySide6 | 6.5 | Qt6 bindings |
| psycopg2-binary | 2.9 | PostgreSQL adapter |
| sqlparse | 0.4 | Optional — needed for Format SQL only |
| networkx | 2.6 | Required for Support Script Manager |

---

## Installation

### Option 1 — Pre-built binary (recommended)

Download from the [**Releases**](https://github.com/Yoda-Man/coruscant/releases) page.

| Platform | File | Run |
|---|---|---|
| Windows | `Coruscant.exe` | Double-click |
| macOS | `Coruscant-macOS.zip` | Unzip → drag to Applications |
| Linux | `Coruscant` | `chmod +x Coruscant && ./Coruscant` |

Linux binaries require `libGL`, `libglib-2.0`, and `libdbus-1`:  
`sudo apt-get install libgl1 libglib2.0-0 libdbus-1-3`

### Option 2 — Run from source

```bash
cd DBClient                   # project root
pip install -r requirements.txt
python main.py
```

Virtual environment recommended:

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
python main.py
```

---

## Building a Standalone Executable

```bat
distribution\build_windows.bat   # Windows → distribution\dist\Coruscant.exe
bash distribution/build_macos.sh  # macOS  → distribution\dist\Coruscant-macOS.zip
bash distribution/build_linux.sh  # Linux  → distribution\dist\Coruscant
```

All scripts install dependencies and invoke PyInstaller against `distribution/coruscant.spec`. A GitHub Actions workflow triggers on version tags and publishes releases for all three platforms.

---

## Quick Start

1. Launch Coruscant (`python main.py` or double-click the binary).
2. **Connections** → choose or create a profile → **Connect**.
3. Type SQL in the editor.
4. Press **Ctrl+Enter** to execute the current tab.
5. Results appear in tabs below the editor.

---

## Architecture

```
coruscant/
├── __init__.py              # __version__, __author__, __app_name__
├── app.py                   # QApplication factory
│
├── core/                    # Business logic — zero GUI imports
│   ├── connections.py       # Saved profiles, pgAdmin import
│   ├── database.py          # DatabaseManager (connect, execute, transactions)
│   ├── worker.py            # QueryWorker — background QThread
│   ├── sql.py               # split_statements(), split_statements_with_positions()
│   └── script_manager.py   # ScriptKnowledgeGraph, SQLScriptParser, ScriptIngester
│
├── ui/
│   ├── main_window.py       # MainWindow — coordinator, no business logic
│   ├── widgets/
│   │   ├── editor.py        # SQLEditor (line numbers + autocomplete), EditorTab
│   │   ├── results.py       # ResultGrid, MessageResult, ExplainResult, ErrorResult
│   │   └── tab_bar.py       # PinnableTabBar, EditorTabBar
│   ├── dialogs/
│   │   ├── cell_viewer.py   # CellViewerDialog
│   │   ├── connection.py    # ConnectionDialog
│   │   ├── guide.py         # ShortcutGuideDialog
│   │   ├── message.py       # StyledMessageBox
│   │   └── script_manager_dialog.py  # ScriptManagerDialog
│   └── panels/
│       ├── schema.py        # SchemaBrowser + Settings panel
│       └── history.py       # HistoryPanel
│
└── utils/
    ├── highlighter.py       # SQLHighlighter (VS Code Dark+ colours)
    ├── logging_config.py    # Rotating file handler + crash excepthook
    ├── serializers.py       # json_default() for psycopg2 types
    └── themes.py            # apply_dark(), apply_light()
```

**Dependency rules:** `core` has zero GUI imports. `ui` depends on `core` and `utils`. `core` never imports from `ui`.

---

## Connecting to a Database

Click **Connections** to open the connection manager. Import a pgAdmin JSON export or create profiles manually. Double-click a profile to connect.

| SSL Mode | Behaviour |
|---|---|
| `disable` | Never use SSL |
| `prefer` | Use SSL if available *(default)* |
| `require` | Always use SSL |
| `verify-full` | SSL + verify certificate + hostname |

Passwords are base64-encoded in the OS settings store. Not encrypted — treat the store as sensitive.

---

## The Editor

Each editor tab contains a **syntax-highlighted SQL editor** with:

- **Line-number gutter** — shows the current line in blue; toggle in ⚙ Settings
- **Current-line highlight** — subtle background band on the active line
- **SQL autocomplete** — triggers after 2 characters or with **Ctrl+Space**; toggle in ⚙ Settings
- **Collapsible Parameters panel** — for `%(name)s` substitution

### Tab Management

| Action | Shortcut |
|---|---|
| New tab | **Ctrl+T** |
| Close tab | **Ctrl+W** |
| Next tab | **Ctrl+Tab** |
| Previous tab | **Ctrl+Shift+Tab** |
| Rename tab | Double-click the tab title |

Saving a script (💾) **auto-renames the tab** to the filename stem. Manual renames are never overridden.

---

## Running Queries

| Action | Shortcut | Behaviour |
|---|---|---|
| Execute all tabs | **F5** | Runs every non-empty tab sequentially |
| Execute this tab | **Ctrl+Enter** | Runs the selection, or the full tab if none |
| Execute at cursor | **Ctrl+F5** | Runs the single statement the cursor is in |
| Cancel | **Escape** | Sends `pg_cancel_backend()` to PostgreSQL |

The **Row limit** spinner (default 100, `0` = Unlimited) caps rows per `SELECT`.  
A yellow banner appears when results are truncated.

---

## Result Tabs

| Statement | Tab content |
|---|---|
| `SELECT` / `RETURNING` | Sortable, filterable **ResultGrid** |
| `INSERT` / `UPDATE` / DDL | **MessageResult** with rows affected |
| `EXPLAIN` | **ExplainResult** — monospace plan text |
| Error | **ErrorResult** — full scrollable error |

- **Double-click a cell** → Cell Content Viewer (ideal for JSON, XML, long text)  
- **Filter box** → live row filter, `setRowHidden` — fast even on large sets  
- **Ctrl+C** → copy selected rows as TSV; **Ctrl+Shift+C** → with headers  
- **Right-click a result tab** → Pin / Unpin (📌 pinned tabs survive next Execute)

---

## Transaction Mode

**Auto-commit on** (default): every statement commits immediately.  
**Auto-commit off**: use the **Commit** / **Rollback** buttons. DDL is fully transactional.

---

## Schema Browser

```
public (schema)
  ├── orders [T]        ← ▶ SELECT button  or  double-click → inserts SELECT *
  │     ├── Columns (5)
  │     ├── Indexes (2)  ← hover for DDL definition
  │     └── Foreign Keys (1)
  └── Functions / Procedures (3)
```

- **▶ SELECT** button → `SELECT * FROM "schema"."table" LIMIT 100;` at cursor  
- **Right-click a table** → SELECT / UPDATE / DELETE script templates (all columns pre-filled)  
- **⚙ Settings** → toggle Auto-complete, Line numbers, Cell-viewer auto-close  
- **? Guide** → opens the full in-app quick-reference guide

---

## Support Script Manager

Click **📜 Scripts** in the Schema Browser panel to open the Script Manager.

**First-time setup:** click **⬆ Upload Scripts ZIP** and select a `.zip` containing your `.sql` maintenance scripts. The engine indexes them into a knowledge graph in under 5 seconds.

**Daily use:** type natural language into the search box:

```
fix deadlock          → finds scripts that handle lock contention
vacuum freeze         → finds scripts for transaction wraparound
40P01                 → finds scripts mentioning that PostgreSQL error code
pg_stat_activity      → finds scripts that query activity views
```

Double-click any result to load the script directly into the active editor tab.

**Incremental updates:** upload a second ZIP and choose *Merge* to add scripts without replacing the existing collection.

**Script header format for best results:**

```sql
-- @desc:     Brief description of what this script does
-- @fixes:    deadlock, blocked, lock_wait
-- @requires: pg_stat_statements
-- @tables:   pg_locks, pg_stat_activity
-- @date:     2026-01-15

-- SQL here
```

See [`docs/SCRIPT_MANAGER.md`](docs/SCRIPT_MANAGER.md) for the full reference.

---

## Query History

The **Query History** panel stores the last 100 queries with timestamps and elapsed times. Persisted across sessions. Double-click any entry to reload it into the active editor tab.

---

## Parameterised Queries

Use `%(name)s` placeholders in SQL. Open **Parameters ▸** in the editor header.

```sql
SELECT * FROM users WHERE id = %(user_id)s AND active = %(active)s;
```

Values are substituted via `cursor.mogrify()` — SQL injection is structurally impossible.

---

## EXPLAIN / EXPLAIN ANALYZE

| Button | SQL prepended |
|---|---|
| **Explain** | `EXPLAIN <first statement>` |
| **Explain+** | `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) <first statement>` |

The plan appears in an **ExplainResult** tab. Only the first statement is explained.

---

## Exporting Results

Each ResultGrid has **Export CSV** and **Export JSON** buttons.  
CSV: UTF-8, header row, NULL → empty string.  
JSON: array of objects; dates, decimals, and bytes are serialised.

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| **F5** | Execute all editor tabs sequentially |
| **Ctrl+Enter** | Execute current tab (selection or full) |
| **Ctrl+F5** | Execute statement at cursor |
| **Escape** | Cancel running query |
| **Ctrl+T** | New editor tab |
| **Ctrl+W** | Close current editor tab |
| **Ctrl+Tab** | Next editor tab |
| **Ctrl+Shift+Tab** | Previous editor tab |
| **Ctrl+Space** | Trigger SQL autocomplete |
| **Ctrl+C** *(result grid)* | Copy selected rows as TSV |
| **Ctrl+Shift+C** *(result grid)* | Copy selected rows with headers |

---

## Themes

Click **🌙 / ☀** to toggle dark / light theme. Persists across sessions.

---

## Logging

| Platform | Log file |
|---|---|
| Windows | `%APPDATA%\Coruscant\logs\coruscant.log` |
| macOS | `~/Library/Logs/Coruscant/coruscant.log` |
| Linux | `~/.local/share/Coruscant/logs/coruscant.log` |

Files rotate at 5 MB; 3 backups kept (15 MB total).

Enable verbose logging: `CORUSCANT_LOG_LEVEL=DEBUG python main.py`

| Level | What is recorded |
|---|---|
| `INFO` | Start (version, Python, Qt, OS), connect/disconnect, schema load, query summaries, theme changes |
| `WARNING` | Truncated results, cancelled queries |
| `ERROR` | Connection failures, query errors, schema errors |
| `DEBUG` | Full SQL (120 chars), per-statement row counts and elapsed time |

---

## Security Notes

- Passwords are base64-encoded in the OS settings store — not encrypted. Treat the store as sensitive.
- Use `verify-full` SSL for production connections over untrusted networks.
- The Script Manager never executes uploaded scripts during indexing — analysis is text-only.
- No telemetry, no analytics, no external network calls from any part of the application.

---

## Known Limitations

| Area | Detail |
|---|---|
| Dollar-quoted strings | Highlighter handles `$$…$$` on a single line only |
| Single connection | All editor tabs share one PostgreSQL connection |
| No `.pgpass` support | Connection parameters must be entered manually |
| Script Manager graph | Built with NetworkX; requires `pip install networkx>=2.6` |

---

## Changelog

See [change.md](change.md) for the full version history.
