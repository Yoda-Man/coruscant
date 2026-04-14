# Coruscant: PostgreSQL Multi-Query Tool

<p align="center">
  <img src="docs/coruscant3.png" alt="Coruscant — PostgreSQL Multi-Query Tool" width="600">
</p>

**Version:** 0.9.3
**Author:** Marwa Trust Mutemasango

> *Named after the galactic capital of Star Wars — a city-planet that is essentially one giant information hub.*

A lightweight desktop SQL IDE for PostgreSQL built with Python and PySide6.
Run multiple statements in one pass, browse your schema with indexes and
foreign keys, manage transactions, and export results, all in a single window.

---

## Why Coruscant Exists

pgAdmin, the dominant GUI tool for PostgreSQL, has a long-standing
limitation in its current stable release: **when a script contains multiple
`SELECT` statements, only the result of the last one is displayed.** Earlier
result sets are silently discarded. A fix is actively under development but it has not yet shipped.
The challenge is non-trivial: holding every result set in memory
simultaneously creates real pressure on machines running large queries.

This matters in practice. Analysts and developers routinely write scripts
that query several tables in sequence, compare before-and-after states of
a data migration, or validate a series of transformations in one pass.
Switching to a single-query workflow to work around the limitation breaks
that natural flow and introduces the risk of losing context between runs.

Coruscant was built to solve this problem directly. Every `SELECT` in your
script gets its own dedicated, persistent result tab. You can run twenty
statements, inspect any of the twenty results, pin the ones you want to
keep, and compare them side by side, all without leaving the window or
re-running individual queries.

---

## What We Like About This Project

A few things in the current release that are genuinely well done:

**Separate result tab per statement** is the core feature. Three `SELECT`s
produce three independently sortable, filterable, exportable grids. This
is the problem that pgAdmin has not yet solved, and it works cleanly here.

**Clean layered architecture:** `core/` contains zero GUI imports. The
SQL parser, database manager, and background worker can all be tested or
reused without a running Qt application. `MainWindow` is a pure
coordinator: it wires signals but contains no SQL logic whatsoever. This
separation is rare in small desktop tools and makes the codebase easy to
navigate and extend.

**Background execution with real cancellation:** queries run in a
`QThread` worker; the UI never freezes. Cancel sends `pg_cancel_backend()`
to PostgreSQL, which means the *server* stops the query, not just the
client. That is the correct approach and many tools get it wrong.

**Inline errors, no modal dialogs:** failed statements open an
`ErrorResult` tab alongside the successful ones. You can read the error,
fix the SQL, and re-run without dismissing any dialog. The rest of your
results are still there.

**Transactional DDL support:** switching off Auto-commit lets you
`CREATE TABLE`, check the result, and roll the whole thing back if needed.
PostgreSQL supports this natively; Coruscant exposes it properly.

**Parameterized queries done right:** values go through
`cursor.mogrify()`, which means they are never string-concatenated into
SQL. SQL injection is structurally impossible when the Parameters panel
is used.

**Pinnable result tabs:** tabs survive subsequent runs when pinned.
This makes it straightforward to hold a reference result steady while
iterating on a query.

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
12. [Query History](#query-history)
13. [Parameterized Queries](#parameterized-queries)
14. [EXPLAIN / EXPLAIN ANALYZE](#explain--explain-analyze)
15. [Exporting Results](#exporting-results)
16. [Keyboard Shortcuts](#keyboard-shortcuts)
17. [Themes](#themes)
18. [Logging](#logging)
19. [Security Notes](#security-notes)
20. [Known Limitations](#known-limitations)
21. [Changelog](#changelog)

---

## Requirements

**Pre-built binaries** (see [Installation](#installation)) require no Python. Only a running PostgreSQL server (9.x – 16+) is needed.

**Running from source** requires:

| Dependency | Minimum version | Notes |
|---|---|---|
| Python | 3.10 | Uses modern type annotations |
| PySide6 | 6.5 | Qt6 bindings |
| psycopg2-binary | 2.9 | PostgreSQL adapter |
| sqlparse | 0.4 | Optional; only needed for Format SQL |

---

## Installation

### Option 1 — Download a pre-built binary (recommended)

Pre-built standalone executables are published automatically via GitHub Actions on every version tag. No Python installation required.

1. Go to the [**Releases** page](https://github.com/Yoda-Man/coruscant/releases) of this repository.
2. Download the file for your platform:

| Platform | File | Notes |
|---|---|---|
| Windows | `Coruscant.exe` | Double-click to run |
| macOS | `Coruscant-macOS.zip` | Unzip, move `Coruscant.app` to Applications |
| Linux | `Coruscant` | `chmod +x Coruscant` then `./Coruscant` |

Linux binaries require `libGL`, `libglib-2.0`, and `libdbus-1` on the host machine. On Debian/Ubuntu: `sudo apt-get install libgl1 libglib2.0-0 libdbus-1-3`.

### Option 2 — Run from source

```bash
# 1. Clone or download the project
cd DBClient          # project root (contains main.py)

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch
python main.py
```

**Virtual environment (recommended):**

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # macOS / Linux
pip install -r requirements.txt
python main.py
```

---

## Building a Standalone Executable

Coruscant uses [PyInstaller](https://pyinstaller.org) to produce self-contained executables. The `distribution/` folder contains everything needed.

### Automated builds via GitHub Actions

Pushing a version tag triggers the `.github/workflows/release.yml` workflow, which builds all three platforms in parallel and publishes a GitHub Release with the artifacts attached.

```bash
git tag v0.9.3
git push --tags
```

The workflow can also be triggered manually from the **Actions** tab in GitHub without a tag (useful for testing builds). When triggered without a tag the artifacts are uploaded but no release is created.

### Local builds

Each platform has its own convenience script in `distribution/`. Run from the **project root** or let the script navigate there automatically.

**Windows**
```bat
distribution\build_windows.bat
```
Output: `distribution\dist\Coruscant.exe`

**macOS**
```bash
bash distribution/build_macos.sh
```
Output: `distribution/dist/Coruscant-macOS.zip` (contains `Coruscant.app`)

**Linux**
```bash
bash distribution/build_linux.sh
```
Output: `distribution/dist/Coruscant`

All three scripts install `requirements.txt` and `pyinstaller` automatically before building. The shared PyInstaller spec file is `distribution/coruscant.spec`.

### Build output layout

```
distribution/
├── coruscant.spec       # PyInstaller spec (all platforms)
├── build_windows.bat
├── build_macos.sh
├── build_linux.sh
├── dist/                # created by build scripts (git-ignored)
│   ├── Coruscant.exe    # Windows output
│   ├── Coruscant.app/   # macOS output (before zipping)
│   ├── Coruscant-macOS.zip
│   └── Coruscant        # Linux output
└── .build/              # PyInstaller work directory (git-ignored)
```

---

## Quick Start

1. Launch Coruscant — either run the downloaded binary or `python main.py` from source.
2. Click **Connect** → fill in server details → **OK**.
3. Type SQL in the editor (e.g. `SELECT * FROM pg_tables;`).
4. Press **F5** or click **▶ Execute**.
5. Results appear in tabs below the editor.

---

## Architecture

Coruscant follows a clean layered architecture. All layers are inside the
`coruscant/` package.

```
coruscant/
├── __init__.py          # __version__, __author__, __app_name__
├── app.py               # QApplication factory (theme, Qt message handler, env snapshot)
│
├── core/                # Business logic — no GUI imports
│   ├── database.py      # DatabaseManager (connect, execute, transaction)
│   ├── worker.py        # QueryWorker — background QThread
│   └── sql.py           # split_statements() — pure SQL parser
│
├── ui/                  # Presentation layer
│   ├── main_window.py   # MainWindow — coordinator, geometry persistence, no business logic
│   ├── widgets/
│   │   ├── editor.py    # EditorTab, ParamsPanel
│   │   ├── results.py   # ResultGrid, MessageResult, ExplainResult, ErrorResult
│   │   └── tab_bar.py   # PinnableTabBar
│   ├── dialogs/
│   │   ├── connection.py  # ConnectionDialog
│   │   └── message.py     # StyledMessageBox — premium branded dialogs
│   └── panels/
│       ├── schema.py    # SchemaBrowser + _SchemaWorker (context menu script generator)
│       └── history.py   # HistoryPanel
│
└── utils/               # Shared utilities — no cross-layer dependencies
    ├── highlighter.py   # SQLHighlighter (QSyntaxHighlighter)
    ├── logging_config.py  # setup_logging() — rotating file handler + excepthook
    ├── serializers.py   # json_default() for psycopg2 types
    └── themes.py        # apply_dark(), apply_light(), current_theme()
```

### Dependency rules

```
ui  →  core  →  (stdlib + psycopg2)
ui  →  utils
core does NOT import from ui or utils
```

`MainWindow` is a **coordinator**: it constructs widgets, wires signals, and
delegates all work to `core/`. It contains no SQL logic, no database calls,
and no parsing.

---

## Connecting to a Database

Click **Connect** to open the connection dialog.

| Field | Description |
|---|---|
| Host | Server hostname or IP (default: `localhost`) |
| Port | PostgreSQL port (default: `5432`) |
| Database | Target database name |
| Username | PostgreSQL role name |
| Password | Stored base64-encoded in OS settings |
| SSL mode | See table below |

### SSL Modes

| Mode | Behaviour |
|---|---|
| `disable` | Never use SSL |
| `allow` | SSL only if the server requires it |
| `prefer` | Use SSL if available *(default)* |
| `require` | Always use SSL |
| `verify-ca` | SSL + verify server certificate |
| `verify-full` | SSL + verify certificate + hostname |

**Test Connection** verifies credentials with a short-lived throwaway
connection without affecting the current session.

Up to **5 recent connections** are saved (passwords base64-encoded).

---

## The Editor

Each editor tab contains:
- A **syntax-highlighted SQL editor** (VS Code Dark+ colour scheme).
- A collapsible **Parameters panel** for named placeholders.

### Multiple Tabs

| Action | How |
|---|---|
| New tab | **+ Tab** button or **Ctrl+T** |
| Cycle tabs | **Ctrl+Tab** / **Ctrl+Shift+Tab** |
| Close tab | **Ctrl+W** or the × on the tab |
| Reorder | Drag tabs |

### Format SQL

**Format SQL** auto-formats the editor (or selection) using `sqlparse`:
keywords → UPPER, identifiers → lower, re-indented.

---

## Running Queries

### Full script

Press **F5** or **▶ Execute** to run the entire editor. Multiple statements
separated by `;` each produce their own result tab.

### Selection only

Select any SQL text before pressing **F5** to run only that portion.

### Row limit

The **Row limit** spinner (default 1 000, `0` = Unlimited) caps rows per
`SELECT`. A yellow truncation warning appears when results are cut.

### Cancelling

While a query runs:
- Click **⏹ Cancel** in the toolbar, or
- Press **Escape**.

PostgreSQL receives `pg_cancel_backend()`. The status bar shows
*"Query cancelled."* No error dialog.

---

## Result Tabs

| Statement | Tab content |
|---|---|
| `SELECT` / `RETURNING` | **ResultGrid:** sortable table |
| `INSERT` / `UPDATE` / DDL | **MessageResult:** rows affected |
| `EXPLAIN` | **ExplainResult:** monospace plan |
| Error | **ErrorResult:** full scrollable error message |

### Filtering

Each ResultGrid has a **Filter** box. Typing hides non-matching rows
instantly using `setRowHidden`. No widget reconstruction; fast even on large sets.

### Sorting

Click any column header to sort; click again to reverse.

### Copying rows

Select rows in a grid and press **Ctrl+C** to copy as TSV (headers included).
Paste directly into Excel.

### Pinning tabs

Right-click a result tab to **Rename** or **Pin**. Pinned tabs (📌) survive
the next Execute. Double-click a tab title to rename it.

### NULL display

`NULL` values appear as grey italic *NULL*, visually distinct from the
string `"NULL"`.

---

## Transaction Mode

By default **Auto-commit** is on: every statement commits immediately.

To use manual transactions:

1. **Uncheck Auto-commit** in the toolbar.
2. Run statements normally.
3. Click **Commit** to persist or **Rollback** to discard.

> Disconnecting while a transaction is open causes the server to roll it back
> automatically.

> DDL (`CREATE TABLE`, `ALTER TABLE`, etc.) is transactional in PostgreSQL
> and can be rolled back when Auto-commit is off.

---

## Schema Browser

The **Database Explorer** dock shows:

```
public  (schema)
  ├── users  [T]
  │     ├── Columns (3)
  │     │     id         integer
  │     │     name       text
  │     │     created_at timestamp
  │     ├── Indexes (2)
  │     │     users_pkey        (hover for DDL)
  │     │     users_name_idx
  │     └── Foreign Keys (1)
  │           fk_role           (hover for definition)
  └── Functions / Procedures (2)
        get_user_count   integer
        reset_sequence   void
```

- **T** = base table, **V** = view.
- **Hover** over an index or FK to see its full definition.
- **Double-click a table/view** → inserts `SELECT * FROM "schema"."table" LIMIT 100;`
- **Double-click a function** → inserts `SELECT "schema"."fn"();`
- **Right-click a table** → context menu with three script generators:
  - **SELECT script** — explicit column list, `WHERE` placeholder, `LIMIT 100`
  - **UPDATE script** — `SET` clause for every column, `WHERE` placeholder
  - **DELETE script** — `WHERE` clause seeded with the first column
- Click **Refresh** after schema changes.

---

## Query History

The **Query History** panel (bottom of the left dock) stores the last 100
queries with timestamps and execution times. Persisted across sessions.

- **Click** an entry to load it into the active editor tab.
- **Clear History** removes all entries.

---

## Parameterized Queries

Use `%(name)s` placeholders in SQL. Open the **Parameters** panel
(click "Parameters ▸" in the editor header) and fill in the values.

**Example**

```sql
SELECT * FROM users WHERE id = %(user_id)s AND active = %(active)s;
```

| Parameter | Value |
|---|---|
| `user_id` | `42` |
| `active` | `true` |

Values are substituted via `cursor.mogrify()`, making them SQL-injection safe.
The same parameter dict applies to every statement in a multi-statement script.

---

## EXPLAIN / EXPLAIN ANALYZE

| Button | SQL prepended |
|---|---|
| **Explain** | `EXPLAIN <first statement>` |
| **Explain+** | `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) <first statement>` |

The query plan appears in an **ExplainResult** tab.
Only the **first** statement is explained when the editor contains multiple.

---

## Exporting Results

Each ResultGrid has two export buttons:

| Button | Format |
|---|---|
| **Export CSV** | UTF-8, header row, `NULL` → empty string |
| **Export JSON** | Array of objects; dates/decimals/bytes serialised |

A file-save dialog prompts for the destination path.

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| **F5** | Execute (full script or selection) |
| **Escape** | Cancel running query |
| **Ctrl+T** | New editor tab |
| **Ctrl+W** | Close current editor tab |
| **Ctrl+Tab** | Next editor tab |
| **Ctrl+Shift+Tab** | Previous editor tab |
| **Ctrl+C** *(in result grid)* | Copy selected rows as TSV |

---

## Themes

Click **🌙 / ☀** in the toolbar to toggle dark / light theme.
The preference persists across sessions.

---

## Logging

Coruscant writes a structured log on every run.

**Log file location**

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\Coruscant\logs\coruscant.log` |
| macOS | `~/Library/Logs/Coruscant/coruscant.log` |
| Linux | `~/.local/share/Coruscant/logs/coruscant.log` |

Files rotate at 5 MB; up to 3 backups are kept (15 MB total).

**Log levels**

| Level | What is recorded |
|---|---|
| `INFO` *(default)* | App start with version + Python + Qt + OS, connect/disconnect, schema load (schema/table counts), query execution summaries, theme changes, clean shutdown |
| `WARNING` | Truncated result sets, cancelled queries |
| `ERROR` | Connection failures, query errors, schema load errors, unexpected exceptions |
| `DEBUG` | Full SQL preview (120 chars), per-statement row counts and elapsed time, Qt internal messages |

**Enabling DEBUG mode**

```bash
# Windows
set CORUSCANT_LOG_LEVEL=DEBUG
python main.py

# macOS / Linux
CORUSCANT_LOG_LEVEL=DEBUG python main.py
```

**Crash handling**

Unhandled exceptions are caught by a custom `sys.excepthook`, logged with a full traceback at `CRITICAL` level, and shown to the user in a dialog that includes the log file path. The Qt internal message system is also routed into the log under the `Qt` logger name.

---

## Security Notes

- **Saved passwords** are base64-encoded in the OS settings store
  (Windows Registry / macOS plist / Linux `.config`). This prevents casual
  inspection but is **not encryption**. Treat the settings store as sensitive.
- For shared machines, clear recent connections after use, or use
  `~/.pgpass` / a secrets manager instead.
- **`verify-full`** SSL provides the strongest server authentication and is
  recommended for production connections over untrusted networks.

---

## Known Limitations

| Area | Detail |
|---|---|
| Dollar-quoted strings | The syntax highlighter handles `$$…$$` on a single line only |
| Single connection | All editor tabs share one PostgreSQL connection |
| No `.pgpass` support | Connection parameters must be entered manually |

---

## Changelog

### 0.9.3
- **Premium message dialogs** — all `QMessageBox` calls replaced with `StyledMessageBox`: each dialog shows the Coruscant banner image, a colour-coded header strip (green / amber / red for info / warning / error), and a dark-themed body with selectable text.
- **Connection dialog — banner enlarged** — banner image scaled to 130 px height with aspect-ratio-preserving smooth scaling; subtitle text removed (redundant with banner artwork).
- **Toolbar Connect / Disconnect toggle** — the two buttons now swap visibility on connection state change so only the relevant action occupies toolbar space, giving all other buttons room to show their full labels.

### 0.9.2
- Documentation cleanup and repository hygiene improvements.

### 0.9.1
- **Structured logging** — rotating log file written on every run (`logging_config.py`).
  Level controlled by `CORUSCANT_LOG_LEVEL` env var; default `INFO`, set `DEBUG` for full SQL traces.
- **Crash handler** — `sys.excepthook` logs unhandled exceptions with full tracebacks and shows a user-facing dialog with the log file path.
- **Qt message routing** — Qt's internal warnings and errors are now captured via `qInstallMessageHandler` and written to the log under the `Qt` logger.
- **Startup environment snapshot** — each session logs Python, PySide6, Qt, and OS version at `INFO`.
- **Window geometry persistence** — window size, position, dock layout, and both splitter positions are saved to QSettings on close and restored on next launch.
- **Graceful shutdown** — `closeEvent` logs the shutdown, saves geometry, and disconnects cleanly from the database.
- **Schema browser context menu** — right-click any table to generate a ready-to-edit SELECT, UPDATE, or DELETE script populated with the table's actual column names.
- **Dark mode arrow fix** — QSpinBox and QComboBox up/down/drop-down arrows are now visible in dark mode using CSS triangle rendering.

### 0.9.0  *(initial public release)*
- Renamed from DBClient → **Coruscant**
- Clean layered architecture: `core/`, `ui/`, `utils/` packages
- Cancel query (⏹ / Escape) works during both Execute and EXPLAIN
- Cancelled queries show a status bar message with no error dialog
- Transaction mode: Auto-commit toggle + Commit / Rollback
- SSL mode selector in connection dialog
- Passwords base64-encoded in QSettings (no more plaintext)
- Expanded schema browser: indexes, foreign keys, functions/procedures
- Result filter uses `setRowHidden` (O(n), no widget reconstruction)
- Errors shown as inline **ErrorResult** tabs with no blocking modals
- Dropped connections detected after query errors
- Keyboard shortcuts: Ctrl+T, Ctrl+W, Ctrl+Tab, Ctrl+Shift+Tab
- Author: Marwa Trust Mutemasango
