# Changelog

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
