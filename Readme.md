# Coruscant: PostgreSQL Multi-Query Tool

<p align="center">
  <img src="docs/coruscant3.png" alt="Coruscant — PostgreSQL Multi-Query Tool" width="600">
</p>

**Version:** 1.0.4  
**Author:** Marwa Trust Mutemasango

> *Named after the galactic capital of Star Wars — a city-planet that is essentially one giant information hub.*

A lightweight, open-source desktop SQL IDE for PostgreSQL built with Python and PySide6.  
Run multiple statements in one pass, browse your schema, manage transactions, search your script library, and export results all in a single window.

## Why Coruscant Exists

pgAdmin has a long-standing limitation: when a script contains multiple `SELECT` statements, only the last result is shown. Earlier result sets are silently discarded.

Coruscant solves this directly. Every `SELECT` produces its own dedicated, persistent result tab. Run twenty statements, inspect any of the twenty results, pin the ones you want to keep, and compare them side by side all without leaving the window.

## What Makes This Project Good

**Separate result tab per statement** is the core feature. Three `SELECT`s produce three independently sortable, filterable, exportable grids.

**Clean layered architecture:** `core/` has zero GUI imports. The SQL parser, database manager, and background worker can all be tested without a running Qt application. `MainWindow` is a pure coordinator it wires signals but contains no SQL logic.

**Background execution with real cancellation:** queries run in a `QThread` worker; the UI never freezes. Cancel sends `pg_cancel_backend()` to PostgreSQL the *server* stops the query, not just the client.

**Responsive startup:** packaged builds show a branded splash screen the instant the executable launches rendered by the bootloader before Python even starts so there is no blank-desktop wait. The Script Manager's knowledge graph is pre-loaded in the background at startup, so the dialog opens instantly with no UI freeze.

**Inline errors, no modal dialogs:** failed statements open an `ErrorResult` tab alongside successful ones. Read the error, fix the SQL, re-run; your other results stay visible.

**Transactional DDL:** switching off Auto-commit lets you `CREATE TABLE`, inspect the result, and roll the whole thing back. PostgreSQL supports this; Coruscant exposes it properly.

**Parameterised queries done right:** values pass through `cursor.mogrify()` never string-concatenated. SQL injection is structurally impossible when the Parameters panel is used.

**Special characters in passwords work correctly always.** Coruscant calls `psycopg2.connect()` with keyword arguments (`host=`, `password=`, …) rather than constructing a URI or DSN string. The password is an opaque Python string from the moment you type it to the moment it reaches the PostgreSQL wire protocol no parsing, no escaping, no shell expansion. Modern DevOps pipelines and cloud credential managers (AWS RDS, Azure Database, HashiCorp Vault) generate passwords that almost always include special characters; Coruscant handles them correctly by design. A `👁` toggle in the connection dialog lets you reveal the password field to verify what you typed before connecting.

**One-click recovery mode repair:** when Coruscant connects to a PostgreSQL server in standby or recovery mode it automatically detects this, warns you in the status bar, and activates the 🔴 Recovery toolbar button. Opening the dialog shows a live status panel (WAL receive/replay positions, replication delay, server start time, replay-paused flag) that refreshes every 10 seconds. A single **Promote to Primary** button calls `pg_promote()` (PostgreSQL 12+, falling back to `pg_wal_replay_resume()` on older versions) after a confirmation prompt, turning the standby into a primary without leaving the application.

**Database Doctor (🩺):** a one-stop diagnostic and repair panel accessible from the status bar footer whenever connected. Four health checks run in the background — lock contention, table bloat, connection exhaustion, and XID wraparound — each displayed on a colour-coded severity card (green / amber / red). Every card comes with targeted repair buttons: kill the blocking query, VACUUM a bloated table, terminate idle connections, and run VACUUM FREEZE to reset transaction ID age. All repairs require confirmation and execute off the UI thread so the application stays responsive.

**Offline script search:** the Support Script Manager indexes your SQL script collections into a statistical knowledge graph (TF-IDF + PageRank + community detection) and answers natural-language queries like "fix deadlock" or "table bloat", entirely offline, no LLM required.

**Automated schema health checks (QA Engine):** right-click any schema to run six checks in a background thread orphaned tables, missing FK indexes (with generated `CREATE INDEX CONCURRENTLY` fix scripts), circular FK cycles, nullable FKs, snake_case naming violations, and type inconsistencies. Results appear in a colour-coded dialog with a 0–100 health score badge. Findings can be suppressed per-table or check-wide, exported to CSV, and used to jump-search the Script Manager.

**Entity-Relationship Diagrams (ERD):** right-click any schema and choose Generate ERD to produce a Mermaid `erDiagram` opened as a self-contained HTML page. Every table is shown as an entity box with column names, types, and PK markers; FK relationships are drawn as one-to-many edges. The page includes pan, zoom, and fit controls plus a collapsible Mermaid source panel for copy-paste into any Mermaid editor.

**Interactive mind maps:** right-click a schema for a D3.js force-directed graph of all tables and FK relationships, or right-click a specific table for a BFS wave-reveal animation that expands outward from that table. Both render as self-contained HTML in your system browser with pan, zoom, search, and tooltips.

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
12. [QA Engine](#qa-engine)
13. [ERD](#erd)
14. [Mind Map](#mind-map)
15. [Support Script Manager](#support-script-manager)
16. [Query History](#query-history)
17. [Parameterised Queries](#parameterised-queries)
18. [EXPLAIN / EXPLAIN ANALYZE](#explain--explain-analyze)
19. [Exporting Results](#exporting-results)
20. [Keyboard Shortcuts](#keyboard-shortcuts)
21. [Themes](#themes)
22. [Logging](#logging)
23. [Recovery Mode](#recovery-mode)
24. [Database Doctor](#database-doctor)
25. [Security Notes](#security-notes)
26. [Known Limitations](#known-limitations)
27. [Changelog](#changelog)

## Requirements

**Pre-built binaries** require no Python. Only a running PostgreSQL server (9.x – 16+) is needed.

**Running from source:**

| Dependency | Minimum version | Notes |
|---|---|---|
| Python | 3.10 | Uses modern type annotations |
| PySide6 | 6.5 | Qt6 bindings |
| psycopg2-binary | 2.9 | PostgreSQL adapter |
| sqlparse | 0.4 | Optional — needed for Format SQL only |
| networkx | 2.6 | Required for Support Script Manager and QA Engine (circular FK detection) |

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

## Building a Standalone Executable

```bat
distribution\build_windows.bat   # Windows → distribution\dist\Coruscant.exe
bash distribution/build_macos.sh  # macOS  → distribution\dist\Coruscant-macOS.zip
bash distribution/build_linux.sh  # Linux  → distribution\dist\Coruscant
```

All scripts install dependencies and invoke PyInstaller against `distribution/coruscant.spec`. A GitHub Actions workflow triggers on version tags and publishes releases for all three platforms.

The spec bundles a startup splash screen (`docs/splash.png`) via PyInstaller's bootloader splash on Windows and Linux; it is rendered before the Python interpreter starts and is closed by `main.py` once the main window is shown. PyInstaller splashes are not supported in macOS `.app` bundles, so the splash is omitted there automatically.

## Quick Start

1. Launch Coruscant (`python main.py` or double-click the binary).
2. **Connections** → choose or create a profile → **Connect**.
3. Type SQL in the editor.
4. Press **Ctrl+Enter** to execute the current tab.
5. Results appear in tabs below the editor.

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
│   ├── script_manager.py   # ScriptKnowledgeGraph, SQLScriptParser, ScriptIngester
│   ├── qa_engine.py         # QAEngine, QAFinding, QAReport — six schema health checks
│   └── mind_map_generator.py # generate_mind_map(), _compute_bfs() — D3.js HTML output
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
│   │   ├── qa_dialog.py     # QADialog — findings table, suppress, export, find scripts
│   │   └── script_manager_dialog.py  # ScriptManagerDialog
│   └── panels/
│       ├── schema.py        # SchemaBrowser + Settings panel + _MindMapWorker + _QAWorker
│       └── history.py       # HistoryPanel
│
└── utils/
    ├── highlighter.py       # SQLHighlighter (VS Code Dark+ colours)
    ├── logging_config.py    # Rotating file handler + crash excepthook
    ├── serializers.py       # json_default() for psycopg2 types
    └── themes.py            # apply_dark(), apply_light()
```

**Dependency rules:** `core` has zero GUI imports. `ui` depends on `core` and `utils`. `core` never imports from `ui`.

## Connecting to a Database

Click **Connections** to open the connection manager. Import a pgAdmin JSON export or create profiles manually. Double-click a profile to connect.

| SSL Mode | Behaviour |
|---|---|
| `disable` | Never use SSL |
| `prefer` | Use SSL if available *(default)* |
| `require` | Always use SSL |
| `verify-full` | SSL + verify certificate + hostname |

**Password field:** the password is always treated as a raw string no URI construction, no shell expansion. Passwords containing `$`, `@`, `%`, `&`, `/`, spaces, or any other special character are passed directly to the PostgreSQL driver via keyword argument. Click the **👁** button beside the field to reveal what you typed and verify it before connecting.

Passwords are base64-encoded in the OS settings store. Not encrypted treat the store as sensitive.

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

## Running Queries

| Action | Shortcut | Behaviour |
|---|---|---|
| Execute all tabs | **F5** | Runs every non-empty tab sequentially |
| Execute this tab | **Ctrl+Enter** | Runs the selection, or the full tab if none |
| Execute at cursor | **Ctrl+F5** | Runs the single statement the cursor is in |
| Cancel | **Escape** | Sends `pg_cancel_backend()` to PostgreSQL |

The **Row limit** spinner (default 100, `0` = Unlimited) caps rows per `SELECT`.  
A yellow banner appears when results are truncated.

## Result Tabs

| Statement | Tab content |
|---|---|
| `SELECT` / `RETURNING` | Sortable, filterable **ResultGrid** |
| `INSERT` / `UPDATE` / DDL | **MessageResult** with rows affected |
| `EXPLAIN` | **ExplainResult** — monospace plan text |
| Error | **ErrorResult** — full scrollable error |

- **Double-click a cell** → Cell Content Viewer (ideal for JSON, XML, long text)  
- **Filter box** → live row filter, `setRowHidden`, fast even on large sets  
- **Ctrl+C** → copy selected rows as TSV; **Ctrl+Shift+C** → with headers  
- **Right-click a result tab** → Pin / Unpin (📌 pinned tabs survive next Execute)

## Transaction Mode

**Auto-commit on** (default): every statement commits immediately.  
**Auto-commit off**: use the **Commit** / **Rollback** buttons. DDL is fully transactional.

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
- **Right-click a schema** → SELECT / UPDATE / DELETE templates, **Generate ERD**, **🗺 Mind Map**, **🔍 QA Engine**  
- **Right-click a table** → SELECT / UPDATE / DELETE script templates, **🗺 Mind Map from here**  
- **⚙ Settings** → toggle Auto-complete, Line numbers, Cell-viewer auto-close, **Run QA Engine on connect**  
- **? Guide** → opens the full in-app quick-reference guide

## QA Engine

Right-click any schema in the Schema Browser and choose **🔍 QA Engine** to run an automated database health check. The engine runs in a background thread and returns a colour-coded report dialog.

**Six checks:**

| Check | What it finds | Fix provided |
|---|---|---|
| Orphaned tables | Tables with no FK relationships (isolated nodes) | — |
| Missing FK indexes | FK columns without a covering index (slow joins) | `CREATE INDEX CONCURRENTLY` script |
| Circular FK cycles | Tables that form a FK dependency loop | Cycle listed |
| Nullable FKs | FK columns that allow NULL (referential integrity risk) | — |
| Naming violations | Tables or columns that don't follow `snake_case` | — |
| Type inconsistencies | Same column name used with different types across tables | Types listed |

**Health score:** 0–100 badge. Green ≥ 80, amber ≥ 50, red below 50.

**Actions on any finding:**

- **🔎 Find Scripts** — opens the Script Manager pre-searched with the check name and table, so you can pull a relevant maintenance script immediately.
- **🔕 Suppress** — hide this finding from all future QA runs. Choose per-table or check-wide. Rules are saved in QSettings and survive restarts.
- **🔕 Manage Suppressions** — view and delete all active suppression rules.
- **📄 Export CSV** — save the full findings table (schema, check, severity, table, column, message, fix SQL) to a file.

**Auto-QA on connect:** enable **Run QA Engine on connect** in the Schema Browser ⚙ Settings panel to run the QA Engine automatically on the first schema whenever a new connection is established.

## ERD

**Generate ERD** — right-click any schema in the Schema Browser and choose **📐 Generate ERD**. Coruscant queries the database for column definitions, primary-key flags, and foreign-key relationships, then renders a [Mermaid](https://mermaid.js.org/) `erDiagram` and opens it as a self-contained HTML page in your default browser.

Each table appears as an entity box listing every column name, its PostgreSQL data type, and a `PK` marker on primary-key columns. FK relationships are drawn as one-to-many edges (`||--o{`) between the parent and child tables.

The page includes pan, zoom, and fit controls powered by svg-pan-zoom, and a collapsible **▶ Mermaid source** panel so you can copy the raw diagram definition into any Mermaid-compatible editor (e.g. mermaid.live). Use **File → Save Page As** in the browser to keep the diagram as a schema snapshot or share it with colleagues.

## Mind Map

**Schema-level mind map** — right-click a schema and choose **🗺 Mind Map**. Coruscant queries row counts and FK edges in a background thread, then opens a self-contained HTML page in your default browser with:

- D3.js v7 force-directed simulation of all tables and FK relationships.
- Node size scaled by row count; colour heat (blue → red) by FK degree.
- Pan and zoom with mouse.
- Search box: type a table name to highlight matching nodes.
- Hover tooltips showing table name, row count, and FK count.

**Table-level mind map** — right-click any table and choose **🗺 Mind Map from here**. The same graph opens with a BFS wave-reveal animation that expands outward from the selected table, making its neighbourhood immediately visible before the rest of the graph animates in.

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

## Query History

The **Query History** panel stores the last 100 queries with timestamps and elapsed times. Persisted across sessions. Double-click any entry to reload it into the active editor tab.

## Parameterised Queries

Use `%(name)s` placeholders in SQL. Open **Parameters ▸** in the editor header.

```sql
SELECT * FROM users WHERE id = %(user_id)s AND active = %(active)s;
```

Values are substituted via `cursor.mogrify()`; SQL injection is structurally impossible.

## EXPLAIN / EXPLAIN ANALYZE

| Button | SQL prepended |
|---|---|
| **Explain** | `EXPLAIN <first statement>` |
| **Explain+** | `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) <first statement>` |

The plan appears in an **ExplainResult** tab. Only the first statement is explained.

## Exporting Results

Each ResultGrid has **Export CSV** and **Export JSON** buttons.  
CSV: UTF-8, header row, NULL → empty string.  
JSON: array of objects; dates, decimals, and bytes are serialised.

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

## Themes

Click **🌙 / ☀** to toggle dark / light theme. Persists across sessions.

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

## Recovery Mode

PostgreSQL servers running as standbys, or servers that crashed and are replaying WAL, enter **recovery mode** — a read-only state where `pg_is_in_recovery()` returns `true`. Without intervention the database remains unavailable for writes until the recovery process completes or an administrator promotes the standby.

Coruscant detects this automatically and provides a one-click path to resolution.

### Automatic detection on connect

Every time you connect, Coruscant silently calls `pg_is_in_recovery()`. If the server is in recovery mode:

- The status bar shows: `⚠  Database is in RECOVERY MODE — click 🔴 Recovery to investigate.`
- The toolbar button label changes to **🔴 Recovery ⚠**

No manual queries required. The alert appears within milliseconds of a successful connection.

### The Recovery dialog

Click **🔴 Recovery** in the toolbar (always available when connected) to open the Recovery Mode dialog. It shows:

| Field | What it tells you |
|---|---|
| **In Recovery** | `YES — standby / recovery` or `NO — primary` |
| **WAL Replay Paused** | Whether WAL replay has been explicitly paused |
| **Replication Delay** | Time since the last replayed transaction — green < 60 s, amber < 5 min, red > 5 min |
| **Last WAL Received** | LSN of the most recently received WAL segment |
| **Last WAL Replayed** | LSN of the most recently applied WAL segment |
| **Last Txn Replayed** | Timestamp of the last replayed transaction |
| **Server Started** | When the PostgreSQL process started |
| **PG Version** | PostgreSQL version string |

The dialog auto-refreshes every 10 seconds. Click **⟳ Refresh** at any time for an immediate update.

### Promoting to primary — one click

1. Confirm the original primary server is offline or fenced.
2. Click **⚡ Promote to Primary** in the Recovery dialog.
3. Confirm the prompt.

Coruscant calls `pg_promote()` (PostgreSQL 12+) or falls back to `pg_wal_replay_resume()` on older versions, running the call off the UI thread so the application never freezes. The dialog refreshes automatically after promotion to confirm the server is now a primary.

> **Privilege required:** the PostgreSQL user must have the `pg_promote` role (PG 14+) or be a superuser.

## Database Doctor

The **Database Doctor** (🩺) lives in the status bar footer and is visible whenever a database connection is active. Clicking it opens a diagnostic dialog that runs four health checks in parallel and displays results on colour-coded severity cards.

### Opening the Doctor

Click the **🩺** icon at the bottom-right of the main window, then click **🔄 Run Diagnosis** to start the checks. Each card updates immediately; click again at any time to refresh.

### Health Checks

| Check | What it detects | Severity triggers |
|---|---|---|
| **Lock Contention** | Queries blocked by other sessions (`pg_blocking_pids`) | Warning if any lock exists; Critical if longest wait 