# Changelog

### 1.0.8
- **New — Live Database Monitor (📊)** — click the **📊 Dashboard** button in the status-bar footer (visible when connected) to open a real-time monitoring window. Metrics are sampled from `pg_stat_*` views on a background thread and auto-refresh at a selectable interval (2s / 5s / 10s / 30s / 60s), so the UI never blocks. Auto-refresh can be paused and the view refreshed manually at any time. The dialog is non-modal — you can keep querying while it runs — and re-opening focuses the existing window instead of stacking copies.
- **New — KPI gauges** — a strip of ten live gauges: database size, connection usage vs `max_connections` (colour-coded), buffer cache-hit %, transactions/sec, active queries with longest-running duration, server uptime, row writes/sec (insert/update/delete), rows read/sec, blocked sessions / lock waits, and commit ratio with deadlock count.
- **New — Live sparklines** — dependency-free `QPainter` trend charts (no extra packages) for transactions/sec, connection count, cache-hit %, and rows-returned/sec, each with a rolling window and min/max/current overlays.
- **New — Tabbed detail views** — ten drill-down tabs: Activity (live non-idle sessions with wait events), Connections (by state and by user/app/client), Tables (size, dead-tuple %, seq vs index scans, last vacuum/analyze), Indexes (usage, surfacing unused indexes), Cache (per-table hit ratio), Databases (cluster-wide sizes and activity), Locks (blocked/blocking sessions), Replication (standby lag), Top Queries (via `pg_stat_statements` when available), and key performance Settings. Each query degrades gracefully — a missing extension or empty result shows a friendly note instead of blanking the panel.
- **New — per-second rates** — transactions, tuple, and cache-hit rates are computed as deltas between consecutive samples (`coruscant.core.metrics.compute_rates`), with automatic detection of statistics resets to avoid false spikes.
- **Architecture** — all SQL and rate math live in the new GUI-free `coruscant/core/metrics.py`; the UI lives in `coruscant/ui/dialogs/dashboard.py`, mirroring the Database Doctor layering.

### 1.0.7
- **Improved — Recovery / Server Mode dialog** — doubled the dialog height (minimum 500 px, uncapped scroll area) to match the Database Doctor window proportions.
- **Improved — Recovery dialog primary state** — when connected to a primary server the footer button now shows **🟢 Primary** (green) instead of a red recovery indicator; the dialog itself shows a green header strip with "Database is Operating Normally — Primary Server" and a clear confirmation message instead of an error.
- **Fixed — `pg_is_wal_replay_paused()` on primary servers** — the status query now wraps the call in `CASE WHEN pg_is_in_recovery() THEN pg_is_wal_replay_paused() ELSE NULL END` so it never throws "Recovery control functions can only be executed during recovery" when the connected server is a primary.
- **Improved — tests** — `test_version.py` restored from truncation; new `tests/test_recovery.py` adds targeted unit tests covering `check_recovery_status()` SQL safety on primary servers, `promote_standby()` fallback logic, `RecoveryDialog` structure, and `MainWindow` footer button wiring for both primary and recovery states.
- **Version bump** — updated to 1.0.7 across all files.

### 1.0.6
- **New — Database Doctor (🩺)** — click the 🩺 icon in the status bar footer to open a diagnostic and repair panel. Four health checks run in parallel background threads: lock contention (`pg_blocking_pids`), table bloat (`pg_stat_user_tables` dead-tuple ratio), connection exhaustion (usage vs `max_connections`, idle-in-transaction count), and XID wraparound (transaction ID age as % of 2-billion limit). Each check renders as a colour-coded severity card (green / amber / red).
- **New — One-click repairs in Database Doctor** — every card exposes targeted repair buttons with confirmation prompts: Kill Blocker (`pg_terminate_backend`), VACUUM Selected table, VACUUM All bloated tables, Terminate Idle backends, Terminate Idle-in-Txn backends, and VACUUM FREEZE for wraparound. All repairs run off the UI thread and trigger an automatic re-diagnosis on completion.
- **New — Recovery Mode detection** — on every successful connection Coruscant silently queries `pg_is_in_recovery()`. If the server is a standby, the status bar shows a warning and the 🔴 Recovery toolbar button activates.
- **New — Recovery Mode dialog** — live status panel showing WAL receive/replay LSN positions, replication delay (colour-coded), replay-paused flag, server start time, and PostgreSQL version. Auto-refreshes every 10 seconds.
- **New — One-click promote to primary** — the Recovery dialog's ⚡ Promote to Primary button calls `pg_promote()` (PostgreSQL 12+) with automatic fallback to `pg_wal_replay_resume()` on older versions, runs off the UI thread, and refreshes the dialog to confirm promotion.
- **Version bump** — updated to 1.0.6 across all files.

### 1.0.4
- **New — QA Engine** — right-click any schema in the Schema Browser and choose **🔍 QA Engine** to run a full automated health check. Six checks fire in a background thread: orphaned tables (no FK relationships), FK columns missing a covering index (with a `CREATE INDEX CONCURRENTLY` fix script), circular FK dependency cycles, nullable FK columns, snake_case naming violations, and column type inconsistencies across tables. Results appear in a colour-coded dialog with a 0–100 health score badge (green ≥ 80, amber ≥ 50, red below 50).
- **New — QA: Suppress findings** — select any finding and click **🔕 Suppress** to hide it from all future QA runs on that table. Rules are persisted in QSettings (`qa/suppressed_findings`) as `check:table` or `check:*` (check-wide) keys. Manage or clear all rules via **🔕 Manage Suppressions**.
- **New — QA: Find Scripts** — select a finding and click **🔎 Find Scripts** to open the Script Manager pre-searched with the check name, table, and column. Requires a script index to be loaded first.
- **New — QA: Export CSV** — click **📄 Export CSV** to save all findings (including suppressed ones) to a CSV file with schema, check, severity, table, column, message, and fix SQL columns.
- **New — Auto-QA on connect** — enable **Run QA Engine on connect** in the Schema Browser ⚙ Settings panel to automatically run the QA Engine on the first schema whenever a database connection is established.
- **New — Mind Map** — right-click a schema and choose **🗺 Mind Map** to generate an interactive D3.js force-directed graph of all tables and FK relationships. Node size reflects row count; colour heat (blue → red) reflects FK degree. Renders in the system browser as a self-contained HTML file with pan, zoom, search highlight, and tooltips.
- **New — Mind Map from here** — right-click any table and choose **🗺 Mind Map from here** to open a focused mind map with a BFS wave-reveal animation starting from that table, making the table's neighbourhood immediately visible.
- **New — tests: QA Engine suite** — `tests/test_qa_engine.py` adds 68 new unit tests covering all six QA checks with synthetic metadata (no DB required), `QAReport` health score arithmetic, suppression rule logic, BFS wave computation, and mind map HTML structure via mocked cursors.
- **Improved — test coverage** — `tests/test_ui_ast.py` extended with structural checks for `_MindMapWorker`, `_QAWorker`, `search_scripts_requested` signal, mind map and QA methods in schema.py, `QADialog` class, signals, suppression helpers, and action methods.
- **Version Update** — bumped application version to 1.0.4.


### 1.0.3
- **Fixed — passwords with special characters** — passwords containing `$`, `@`, `#`, `%`, `&`, spaces, and other characters that break DSN-style connection strings now work reliably. Coruscant has always used psycopg2 keyword-argument connections (never DSN strings), so the wire protocol was never the issue; the fix adds `inputMethodHints` (`ImhHiddenText | ImhNoPredictiveText | ImhNoAutoUppercase | ImhSensitiveData`) to the password field so IME, autocorrect, and autocapitalise on all platforms cannot silently alter what the user typed.
- **Improved — show/hide password toggle** — a 👁 button beside the password field lets users reveal what they typed before clicking Test or Connect, eliminating guesswork when a password contains hard-to-distinguish characters.
- **Tests — special-character password coverage** — four new test cases verify that passwords such as `password$1` survive the full encode → serialise → deserialise → `connect_params()` round-trip intact.
- **Version Update** — bumped application version to 1.0.3.


### 1.0.2
- **New — startup splash screen** — frozen Windows/Linux builds now show a branded splash the instant the executable is launched, rendered by the PyInstaller bootloader *before* Python starts. This covers the one-file unpack and Qt initialisation delay that previously left users staring at a blank desktop. The splash caption updates through startup ("Loading interface…", "Restoring your session…") and closes as soon as the main window appears. The splash is automatically a no-op when running from source (`python main.py`) and on the macOS `.app` bundle, where PyInstaller splashes are unsupported.
- **Improved — Script Manager opens instantly** — the Support Script Manager's knowledge graph (a multi-megabyte gzip-compressed JSON file) is now loaded once in a background thread at application startup instead of synchronously the first time the dialog is opened. Opening the Script Manager — including the automatic error-driven suggestion popup — no longer freezes the UI while the graph decodes. The cached graph stays in sync after uploads and clears.
- **Version Update** — bumped application version to 1.0.2 across all components and documentation.


### 1.0.1
- **Fixed:** `_on_results`, `_on_query_error`, `_on_query_cancelled`, and `_on_explain_results` were accidentally removed from `MainWindow` in 1.0.0, causing a crash on every query execution (regression from 1.0.0).
- **Fixed:** `merge_connections()` incremented the `updated` counter on no-op merges where nothing actually changed.
- **Fixed:** `ScriptIngester.ingest_zip()` save path is now overridable via an optional `save_path` parameter instead of always writing to the default location.
- **Fixed:** `_on_run_all_tabs()` now cancels any in-flight worker before starting a new run-all, preventing overlapping concurrent executions.
- **Fixed:** Database zombie-detection ping is now skipped if the connection was active within the last 30 seconds, eliminating unnecessary round-trips on rapid successive queries.
- **Improved:** Comprehensive test suite — 416 tests across 9 files (up from ~40 passing tests in 1.0.0).


### 1.0.0
- **Line-number gutter** — the SQL editor now shows a line-number gutter to the left. The active line number renders in blue; a full-width highlight band follows the cursor. Toggle on/off in the ⚙ Settings panel of the Schema Browser. Persists across sessions.
- **Support Script Manager** — offline knowledge-graph search engine for SQL maintenance scripts. Upload a ZIP of `.sql` files and search by natural language ("fix deadlock", "table bloat", "40P01"). Uses TF-IDF, PMI co-occurrence, PageRank, and community detection — no LLM, no internet. Stores the graph in `~/.local/share/Coruscant/scripts/` as gzip-compressed JSON. Accessible via the `📜 Scripts` toolbar button.
- **Script Manager — merge and replace** — uploading a second ZIP prompts for merge (add to existing) or replace (re-index only the new ZIP). Duplicate scripts are de-duplicated by SHA-256 content checksum.
- **Script Manager — error-driven suggestions** — when a query fails with a recognisable PostgreSQL SQLSTATE code, `suggest_scripts_for_error()` opens the Script Manager pre-searched for that error.
- **F5 / Ctrl+F5 / Ctrl+Enter** — F5 now executes all editor tabs sequentially; Ctrl+F5 executes only the statement at the cursor; Ctrl+Enter executes the current tab (selection or full). Execute button is click-only.
- **Tab auto-naming** — saving a script via 💾 auto-renames the editor tab to the filename stem. Manual renames (double-click tab title) are never overridden.
- **Schema Browser improvements** — font size increased by 1 pt; ▶ SELECT button on every table/view row; ⚙ Settings panel with toggles for autocomplete, cell-viewer auto-close, and line numbers; ? Guide button opens the full in-app quick-reference.
- **Cell Viewer auto-close** — optional auto-dismiss of the Cell Content Viewer after a successful clipboard copy (1.5 s delay).
- **Row limit default** — changed from 1 000 to 100 to match generated `LIMIT 100` in SELECT scripts.
- **Autocomplete fix** — fixed a bug where `set_completer_words()` silently disabled autocomplete on every call.
- **Code quality** — removed duplicate keywords in the SQL highlighter; eliminated dead code; collapsed redundant `_current_result_widgets()` double-calls.
- **Test suite** — 216 tests (up from 48); new coverage for `split_statements_with_positions`, `normalise_ssl_mode`, `_safe_int`, deserialise/merge edge cases, scoring multipliers, query expansion, preview generation, cursor-statement matching, and all script manager features.
- **Documentation** — full rewrite of `README.md`; updated `docs/USER_MANUAL.md` with Script Manager section (§15) and line-number description; regenerated `docs/USER_MANUAL.html` with matching look and feel; added `docs/SCRIPT_MANAGER.md` full reference.
- **Version Update** — bumped application version to 1.0.0 across all components and documentation.

### 1.0.0
- **Schema Browser — SELECT Button** — every table and view row now shows a compact ▶ SELECT button that appends a `SELECT * FROM … LIMIT 100;` query directly into the active editor tab without double-clicking.
- **Schema Browser — Font & Settings** — tree font increased by 1 pt for improved readability; new ⚙ Settings panel provides in-app toggles for SQL auto-complete and cell-viewer auto-close.
- **Cell Viewer Auto-Close** — when enabled, the Cell Content Viewer dismisses itself automatically after a successful clipboard copy, eliminating the extra Close click.
- **Schema Browser — Guide Button** — a ? Guide button opens a full quick-reference dialog (with app logo) covering all keyboard shortcuts, schema browser tricks, editor features, and result-grid tips.
- **Row Limit Default** — default row limit changed from 1000 to 100 to match the `LIMIT 100` in generated SELECT scripts.
- **Keyboard Shortcuts** — F5 now executes all editor tabs sequentially; Ctrl+F5 executes only the statement at the cursor; Ctrl+Enter executes the current tab (selection or full).
- **Query Tab Naming** — saving a script auto-renames its editor tab to the filename stem; double-clicking any editor tab title opens an inline rename dialog; manually-set names are never overridden by auto-naming.
- **Autocomplete Fix** — fixed a critical bug where `set_completer_words()` silently reset the enabled flag to `False` on every call, disabling autocomplete on every fresh tab and schema refresh.
- **Code Quality** — removed duplicate KEYWORDS entries (`NOT`, `NULL`, `DEFAULT`) from the SQL highlighter; eliminated dead comment blocks and an unused variable (`abbr`) in the schema browser; collapsed a redundant double `_current_result_widgets()` call in the execute path.
- **Observability** — `history.py` exception handlers now emit `log.debug` messages instead of silently discarding errors.
- **Test Coverage** — 47 new tests added (95 total, up from 48): full coverage for `split_statements_with_positions`, `normalise_ssl_mode`, `_safe_int`, `deserialise_connections` edge cases, `merge_connections` edge cases, and `SavedConnection` key/display-name behaviour.
- **Version Update** — bumped application version to 1.0.0 across all components and documentation.

### 0.9.9
- **pgAdmin Connection Import** - added a searchable connection manager that imports pgAdmin server JSON exports, preserving server names, groups, hosts, ports, maintenance databases, usernames, SSL modes, and pgAdmin colour metadata.
- **Connection Switching UI** - replaced the small recent-connections dropdown with a two-pane saved profile library for importing, searching, editing, testing, connecting, and deleting PostgreSQL profiles.
- **Auto-reconnect Reliability (Zombie Detection)** — improved connection health monitoring by implementing a lightweight "ping" check before query execution. This ensures that "zombie" connections (closed by the server due to idle timeouts) are detected and transparently re-established, preventing "no connection to the server" errors after long periods of inactivity.
- **Version Update** — bumped application version to 0.9.9 across all components and documentation.

### 0.9.8
- **SQL Autocomplete** — the editor now provides intelligent suggestions for SQL keywords, built-in functions, and database identifiers (tables, columns, functions). Suggestions appear automatically after typing two characters or manually via `Ctrl+Space`.
- **UI Polish — Icons & Labels** — added descriptive icons to the Format (🪄), Clear (🧹), Open (📂), and Save (💾) actions in the toolbar and shortened their labels for a cleaner look.
- **Connection Management** — the delete button in the connection dialog now includes the text label "Delete" alongside its icon (🗑) for better visibility.
- **Version Update** — bumped application version to 0.9.8 across all components and documentation.

### 0.9.7
- **Database Auto-reconnect** — the application now automatically detects when a connection has been lost (e.g., due to an idle timeout) and re-establishes it before executing queries or refreshing the schema.
- **Status Indicator** — added a "Ready (Auto-reconnect)" status state in the toolbar to inform users when a connection is closed but can be seamlessly restored.
- **Improved Connection Resilience** — updated core connection logic to handle broken or server-side closed connections more reliably.
- **Version Update** — bumped application version to 0.9.7 across all components and documentation.

### 0.9.6
- **Connection Removal** — users can now delete individual saved connections from the connection dialog by clicking the 🗑 button.
- **Independent Result Tabs** — each editor tab now maintains its own set of result tabs; running a query in one tab no longer clears results from other tabs.
- **Premium Crash Handler** — unhandled exceptions now trigger a branded, dark-themed dialog (StyledMessageBox) with a detailed, monospace traceback for easier troubleshooting.
- **Custom App Icon** — replaced the generic Python icon with a custom sci-fi inspired emblem for the window, taskbar, and executable.
- **Version Update** — bumped application version to 0.9.6 across all components and documentation.


### 0.9.5
- **Cell Viewer Dialog** — added ability to view and copy massive cell contents from the results panel by double-clicking.
- **Schema Browser Layout** — fixed cut-off table names by setting the columns to resize automatically and enabling horizontal scrolling.
- **Documentation** — updated documentation versions to 0.9.5 and extracted changelog to a separate `change.md` file.

### 0.9.4
- **Banner image bundled in executable** — `coruscant3.png` is now included in the PyInstaller build via `datas`; both dialogs resolve the path via `sys._MEIPASS` when frozen so the banner always displays in distribution builds.

### 0.9.3
- **Premium message dialogs** — all `QMessageBox` calls replaced with `StyledMessageBox`: each dialog shows the Coruscant banner image, a colour-coded header strip (green / amber / red for info / warning / error), and a dark-themed body with selectable text.
- **Connection dialog — banner enlarged** — banner image scaled to 130 px height with aspect-ratio-preserving smooth scaling; subtitle text removed (redundant with banner artwork).
- **Toolbar Connect / Disconnect toggle** — the two buttons now swap visibility on connection state cha