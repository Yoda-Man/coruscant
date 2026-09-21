# Changelog

### 1.1.7

**The results grid was discarding your ORDER BY.**

A query ending `ORDER BY "modifieddate" DESC` came back sorted by something
else entirely. The SQL was never at fault: the statement splitter passes
`ORDER BY` and `LIMIT` through untouched, `execute()` runs the statement
verbatim, and `fetchmany()` preserves row order. PostgreSQL returned the rows
correctly sorted every time.

The grid then re-sorted them. Building the table called:

```python
table.setSortingEnabled(True)
```

`setSortingEnabled(True)` does not merely permit sorting — Qt sorts
immediately, by the current sort indicator, which on a freshly built table is
column 0. The population step then re-enabled it a second time after filling
the rows. So every result set was silently reordered by its first column, and
an `ORDER BY` on any other column was thrown away. With a wide result the
first column is often scrolled off-screen, which is why the grid simply looked
unsorted rather than obviously sorted by the wrong thing.

Sorting is no longer switched on while the grid is built. Rows stay in the
order the server returned them, and sorting turns on the first time a column
header is clicked — which is the behaviour the manual has always described.

**Filtering hid the wrong rows once a grid was sorted**

`_apply_filter` read each row's values from `_all_rows[row_idx]` but called
`setRowHidden(row_idx)` on the table. Those two indices agree only until the
grid is sorted, after which the filter tested one row and hid another. Clicking
a header is now the ordinary way to sort, putting this directly in the path, so
each row carries its source index and filtering is correct in any sort order.

**Documentation corrected**

Section 7.3 claimed a third click on a column header removes the sort. Tested
with real clicks, Qt toggles ascending and descending indefinitely; there is no
third state. The section now says so, records that results arrive in the
query's own order, and notes the consequence — once a grid has been sorted,
re-running the query is the only way back to the `ORDER BY` order.

**Tests**

18 new tests, driving a real results grid through Qt. Both fixes were verified
by mutation: restoring the original sorting call fails 6 of them, and restoring
the index-based filter lookup fails 2. The fixture data is deliberately shaped
like the report — first column unsorted, rows ordered by a later column — and
one test asserts that shape, so the data cannot quietly stop being able to
expose the defect.

    CORUSCANT_QT_TESTS=1 pytest tests/test_ui_behaviour.py


### 1.1.6

Two fixes to the editor tabs and the toolbar, and the suite's first tests that
drive a real Qt window.

**The close button on editor tabs never existed**

The user manual has said "Click the **×** on the tab, or press **Ctrl+W**"
since it was written. Only Ctrl+W worked, and nothing about the source
suggested otherwise:

```python
self._editor_tabs.setTabsClosable(True)      # set on the default tab bar…
self._editor_tabs.setMovable(True)
self._editor_tabs.setTabBar(EditorTabBar())  # …which is then thrown away
```

Both flags live on the tab bar, so installing a replacement discarded them:
the close buttons never rendered and tabs could not be dragged. Every call a
reader would look for was present, and neither took effect. The result tabs
built a few lines below already had the order right. The flags now follow
`setTabBar()`.

**Closing a tab could destroy another tab's results**

`_close_editor_tab` looked a tab's result area up by index in the result
stack. Tab order and stack order match only until a tab is dragged, at which
point closing one tab removed a different tab's results and left the survivor
pointing at a deleted widget. It was unreachable while the movable flag was
being discarded, and live the moment that was fixed — so the two had to be
fixed together. The area is now read off the tab itself, and the closed tab is
deleted rather than leaked.

**Connections and Disconnect share a toolbar slot**

Connections was previously always visible, on the reasoning that switching
profiles should not need extra steps. It is now hidden while connected and
returns on disconnect, so exactly one connection action is offered at a time.
The trade is explicit: switching profiles means disconnecting first. The
status chip at the bottom of the window still opens the Connection Manager.

**Tests that build a real window**

Every previous UI test reads the AST. That catches a missing handler but not
what Qt does with a call, and both defects above lived in that gap — the first
especially, where a structural test would have found all three calls present
and passed. `tests/test_ui_behaviour.py` builds a real `MainWindow` offscreen
and asks Qt what it actually did. Each of the three fixes was reverted in turn
and confirmed to fail the suite.

These run in their own process. `test_worker.py` and `test_ui_ast.py`
deliberately delete PySide6 from `sys.modules` so Qt-free code can be imported
without it; dropping the last reference can finalise the shiboken extension
underneath, and constructing a widget afterwards is undefined behaviour — in
practice an access violation partway through `MainWindow.__init__`. The module
skips unless `CORUSCANT_QT_TESTS=1`, and CI runs it as a separate step with a
floor on passes, the same arrangement the live SQL tests already use:

    CORUSCANT_QT_TESTS=1 pytest tests/test_ui_behaviour.py

A plain `pytest` now reports 780 passed and 73 skipped. The skips are those 20
Qt tests and the 53 live SQL tests, both of which need infrastructure a bare
run does not have; the floor assertions in CI are what stop either from
quietly skipping there.


### 1.1.5

Object source in the Schema Browser. Right-click a function, procedure, view
or materialised view and choose **Show definition**: its source opens in a new
editor tab, named for the object. `CREATE OR REPLACE` already executed, so
this closes the loop — read the definition, change it, press F5.

**The schema tree moved from information_schema to pg_catalog**

The old queries could not support this, for three reasons:

* `information_schema.tables` has no materialised views — they are not in the
  SQL standard — so they were missing from the tree entirely, along with their
  columns.
* `information_schema.routines` identifies a routine by name, and a name is
  not unique: PostgreSQL allows overloading. `calc(integer)` and
  `calc(numeric)` arrived as two identical rows that nothing could tell apart,
  let alone fetch the source of.
* Neither exposed an OID, which is the only stable handle a definition lookup
  can be keyed on.

Routines are now listed by signature rather than by name, so overloads are
distinct on screen. Column types render through `format_type()`, so a
`varchar(50)` reads as `varchar(50)` instead of a bare `character varying`.
`has_table_privilege()` preserves the visibility rule `information_schema`
applied for free: a relation the current role holds no privilege on stays out
of the tree.

`pg_proc.prokind` replaced `proisagg`/`proiswindow` in PostgreSQL 11, and
naming a column the server does not have is a parse error rather than an empty
result — so the pre-11 form is a separate statement selected by server
version. An unreported version takes the modern query: guessing the other way
would break every supported server to accommodate an unsupported one.

**What comes back**

Functions and procedures come back as the server renders them —
`pg_get_functiondef()` emits a complete, directly re-runnable statement.

Views do not. `pg_get_viewdef()` returns the `SELECT` body alone, so the
`CREATE OR REPLACE VIEW` is rebuilt around it, with identifiers quoted so a
view called `"Order Details"` survives the round trip.

Materialised views come back as a plain `CREATE MATERIALIZED VIEW` under a
comment explaining why: PostgreSQL has no replace form for one, so changing it
means `DROP` then `CREATE`, discarding the stored rows along with every index,
grant and policy on it. Presenting that as a safe in-place edit would be a
trap.

Aggregates have no source form at all — `pg_get_functiondef()` raises on one —
so the tree marks them and the menu entry is disabled rather than offering an
action that can only fail.

**A failed lookup no longer costs you uncommitted work**

These lookups share the connection queries run on. With auto-commit off, a
failed statement aborts the surrounding transaction and every later statement
in it — so asking for the source of something another session had just dropped
would silently discard whatever was uncommitted. The lookup now runs inside a
savepoint. The guard keys on auto-commit rather than on an already-open
transaction, because with auto-commit off the lookup itself is what opens one.

Definitions are fetched on a background thread and open in a **new** tab, never
the one being edited: a definition is a whole statement and would overwrite
work in progress.

**Tests**

117 new tests, 716 to 833.

The live-SQL suite carries the weight here, because a mock cursor accepts any
string and cannot tell whether `relkind` `'m'` really surfaces a materialised
view. Against a real PostgreSQL 16 the suite now fetches a function's source,
executes it, calls the function and checks the answer; does the same for a
view, including one named `"Order Details"` to exercise quoting; confirms the
server genuinely refuses an aggregate, which is what the disabled menu entry
rests on; and confirms a failed lookup leaves an open transaction usable —
something no mock can demonstrate.

Two live cases skip with stated reasons: `STATEMENTS_SQL` needs
`pg_stat_statements`, and the pre-11 routines query is rejected by design on a
modern server, so it remains unexercised until someone runs against
PostgreSQL 10 or older.

The UI tests assert against the AST rather than the source text, so a docstring
mentioning `insert_sql` cannot satisfy a test that the handler does not call
it.

**Unchanged**

Triggers, sequences and job scheduling are still absent. Editing remains the
SQL editor's job: there is no object editor, no Save button, no validation,
and no warning about dependents when a view is replaced.


### 1.1.4

Documentation corrections and test coverage. No behavioural change to the
application; the binaries differ from 1.1.3 only in version metadata.

**Tests — the Database Doctor's severity logic was entirely untested**

Coverage measurement put `core/doctor.py` at **31%**: all four `assess_*`
functions and the duration formatter had no behavioural coverage at all. The
only thing referencing them was `test_severity_functions_present`, which
asserts the function *names* exist — it passes whether they return the correct
severity or always return OK.

These decide whether a user is shown Healthy, Warning or Critical, and
therefore whether they reach for a repair button. They are pure functions —
row tuples in, `(severity, message)` out — so there was no reason for the gap.

35 tests now cover them, asserted at the threshold boundaries where an
off-by-one would actually bite: 60 seconds is still a warning but 61 is
critical; 30% dead tuples escalates but 29.9% does not; ten mildly bloated
tables escalate on breadth alone; five idle-in-transaction sessions are
critical even on an otherwise quiet server. Also covered: `Decimal` values as
psycopg2 actually returns them from `round()`, a `NULL` `query_start`, and
`max_connections` of zero, which would otherwise divide by zero.

Verified by mutation rather than assumed: each of six threshold changes to the
source was reintroduced and confirmed to fail the suite. `core/doctor.py` is
now at 100%, and `core/` overall at 93%.

**Docs — every checkable claim verified against the source**

- The README architecture tree was missing six modules, among them
  `core/doctor.py`, `core/metrics.py`, `ui/dialogs/dashboard.py` and
  `ui/dialogs/recovery.py` — the Database Doctor, the Live Monitor and
  Recovery Mode, three headline features absent from the diagram entirely.
- `VACUUM FULL` was documented nowhere, having shipped in 1.1.3. The most
  destructive action in the application is now described in both documents,
  including why there is no "FULL All", and both now state the lock level of
  plain `VACUUM` rather than leaving it unsaid.
- The Doctor's blocker button is labelled **Kill Selected Blocker**; both
  documents called it "Kill Blocker", sending readers to look for a button
  that does not exist.
- The README's SSL table listed four of the six modes psycopg2 accepts,
  omitting `allow` and `verify-ca`.
- The managed-PostgreSQL note still told users to expect permission errors.
  Since 1.1.3 ownership is checked against the catalog first.

Checked and found already correct: six QA checks, ten KPI gauges, four
sparklines, ten dashboard tabs, the keyboard shortcuts, and the requirements
table.

Two of these are now enforced by `tests/test_docs.py`: every module under
`coruscant/` must appear in the architecture tree, and every Doctor repair
button must be described in at least one document. The first missed its own
regression when written — it compared basenames, and `doctor.py` exists in two
directories — so it compares counts now.

689 tests, up from 652.

### 1.1.3

Architectural cleanup, plus two user-visible changes to the Database Doctor.

**New — VACUUM FULL, behind a warning proportionate to the risk**

`vacuum_table()` had always accepted a `full` argument, but nothing in the UI
passed it, and no test covered it: an untested code path that looked available.
It is now a separate danger-styled **VACUUM FULL…** button on the Table Bloat
card, selection-only — there is deliberately no "FULL All", because doing this
to twenty tables at once is almost never what anyone means. The confirmation
states plainly that it takes an ACCESS EXCLUSIVE lock, blocks *every* query
including `SELECT`, needs roughly twice the table's size in free disk, cannot
be undone partway, and should not run outside a maintenance window.

**Fixed — the VACUUM confirmations were not accurate**

Both plain-VACUUM dialogs claimed the operation was "safe and non-blocking".
VACUUM takes a SHARE UPDATE EXCLUSIVE lock: it does not block `SELECT`,
`INSERT`, `UPDATE` or `DELETE`, but it does contend with `ALTER TABLE`,
`CREATE INDEX` and `REINDEX` on the same table. The dialogs now say which is
which, rather than implying the operation is free of consequences.

**Fixed — skip detection no longer depends on the server's language**

v1.1.2 detected a refused VACUUM by matching the English words "skipping" and
"can vacuum it" in `conn.notices`. PostgreSQL translates those messages
according to `lc_messages`, so on a non-English server the check silently
stopped matching — and failed *open*, back to reporting success for work that
never happened. Ownership now comes from the catalog before the statement is
issued (`pg_has_role`, `rolsuper`, and `pg_maintain` on PostgreSQL 16+), which
is locale-independent and avoids a round-trip the server would refuse anyway.
Verified against a live server: 279 tables correctly reported as
un-maintainable.

**Architecture — the layering is now enforced rather than described**

The README claimed rules the code had quietly drifted from. Each is now true,
and `tests/test_architecture.py` fails the build if it stops being true:

- `ui/dialogs/connection.py` imported psycopg2 and opened its own connection
  for **Test Connection**, so that button bypassed everything added centrally
  and had drifted to its own connect timeout. It now goes through
  `DatabaseManager`, which gained a `timeout` parameter.
- `utils/logging_config.py` imported a dialog from `ui/`, inverting the
  dependency. The UI now registers a presenter via `set_crash_reporter()`;
  when none is registered the crash is still logged, just not shown.
- `core/worker.py` imported psycopg2 only to catch its error type.
  `core/database.py` — which documents itself as the single point of contact
  with the driver — now re-exports `DatabaseError`, making that true.
- `LOCKS_SQL` was defined in **both** `core/doctor.py` and `core/metrics.py`
  with different text: different truncation, only one normalising whitespace,
  only one bounding the row count. One definition now, with the better
  behaviour of the two, and `WAIT_SECS_COL` naming the positional coupling
  that `assess_locks()` depends on.
- The README's "core/ has zero GUI imports" was simply false —
  `core/worker.py` imports `QThread`. It is now described accurately, as the
  one deliberate exception, and the test that enforces the rule names it and
  checks the exemption is still warranted.

**Tests**

- `tests/test_architecture.py` — seven checks covering dependency direction,
  driver confinement, Qt confinement, and duplicate SQL definitions. Each was
  verified by reintroducing the corresponding defect.
- The seven Doctor repairs each hand-rolled an identical result dialog; that
  duplication is why the VACUUM bug needed fixing in two places. Collapsed
  into `_run_repair()`, and thirteen function-local imports of
  `StyledMessageBox` — which were working around a circular import that does
  not exist — reduced to one at module level.

652 tests, up from 645.

### 1.1.2

**Fixed — Database Doctor reported VACUUM success having vacuumed nothing**

The Table Bloat card's **VACUUM Selected** and **VACUUM All** buttons reported
"VACUUM ANALYZE complete on 20 table(s)" while no table was touched. Reconnecting
showed the same 20 bloated tables, with `Last Vacuum` still reading `Never`.

PostgreSQL does not raise an error when you VACUUM a table you do not own. It emits
a warning and continues, reporting overall success:

```
WARNING:  skipping "tgorganisationidentification" --- only table or database owner can vacuum it
```

`vacuum_table()` treated "no exception raised" as "work done", and nothing in the
codebase read `conn.notices`, so every skip was invisible to the application. The
behaviour was reproduced against PostgreSQL 15.8 with a non-owning, non-superuser
role: the call returns normally, the warning is emitted, and both `n_dead_tup` and
`last_vacuum` are unchanged.

`vacuum_table()` and `vacuum_freeze()` now clear stale notices before running,
then return any ownership-skip warnings. The Doctor counts them and reports what
actually happened — everything skipped, partially completed, or fully completed —
naming the affected tables and pointing at the owning role or a superuser.

This surfaces the condition rather than working around it. A non-owner still cannot
vacuum those tables; it is no longer told otherwise. Note that `pg_maintain`, which
grants maintenance rights without ownership, is PostgreSQL 16+; on earlier servers
ownership or superuser remains the only route.

Five tests cover the new behaviour, including that stale notices from an earlier
statement are not misattributed and that routine `INFO` chatter is not mistaken for
a skip.

**Housekeeping**
- Version bumped to 1.1.2 across the package, `main.py`, `build_windows.bat`,
  `distribution/coruscant.spec`, `README.md`, `docs/USER_MANUAL.md`, and the version test.
- `docs/USER_MANUAL.html` regenerated from the Markdown.

### 1.1.1

A maintenance release. Every change here is to the build script, the test
suite, or the documentation — the application code is identical to 1.1.0, so
there is no functional reason to upgrade if 1.1.0 already runs for you.

**Fixed — local Windows build failed with "'pyinstaller' is not recognized"**
`build_windows.bat` invoked the bare `pyinstaller` console shim. On a machine where an
interrupted `pip install` had left PyInstaller importable but never wrote
`pyinstaller.exe`, the build aborted at step 3 even though PyInstaller 6.19.0 was
installed and `Scripts` was on `PATH`. The script now calls `python -m PyInstaller`,
which does not depend on the shim and runs the build in the same interpreter the
dependencies were installed into; `pip` is likewise invoked as `python -m pip`. This
also matches how the macOS and Linux CI jobs already invoke PyInstaller. Verified by a
clean end-to-end run producing `distribution/dist/Coruscant.exe`.

**Fixed — the v1.1.0 release build failed CI on the first tag push**
`tests/test_docs.py`, added in 1.1.0, hardcoded the readme path as `Readme.md`. Git
tracks the file as `README.md` and the Windows working tree holds it as `Readme.md`, so
the path resolved on a case-insensitive filesystem but raised `FileNotFoundError` on the
Linux runner, failing four tests and blocking the release. Documentation filenames are
now resolved case-insensitively within their directory, so neither spelling can break the
suite on either platform. The fix was validated against a fresh Linux clone before
re-tagging; no v1.1.0 release or artefact had been published at the point the tag was
moved.

**Changed — the User Manual no longer carries its own changelog**
The manual ended with five "What's New in …" sections duplicating this file. They had
already fallen behind — the newest entry was 1.0.9, with no mention of 1.1.0 — and the
final section was truncated mid-sentence (`**Version 1.0.4** adds automated sche`). All
five are removed in favour of a short pointer to `change.md`, which is now the single
place release notes live. This drops the manual from 1,602 to 1,531 lines and removes
the truncated text from both the Markdown and the generated HTML.

**Housekeeping**
- Version bumped to 1.1.1 across `coruscant/__init__.py`, `main.py`, `build_windows.bat`,
  `distribution/coruscant.spec`, `README.md`, `docs/USER_MANUAL.md`, and the version test.
- `docs/USER_MANUAL.html` regenerated from the Markdown by `scratch/build_manual_html.py`.

### 1.1.0
- **New — Supabase connection preset** — click **Supabase…** in the connection manager, paste a project reference, and pick a region. Coruscant fills in the pooler host, port, `postgres` database, the project-qualified `postgres.<project-ref>` username, and SSL mode `require`. Only the password is left for you to enter. The endpoint dropdown defaults to the session pooler and warns when the transaction pooler is chosen. No new dependencies — the preset is pure form-filling with no network calls.
- **New — hosted-instance advisories** — the connection form now detects managed PostgreSQL by hostname (Supabase, Neon, Amazon RDS, Azure Database) and shows an advisory panel naming the provider and the features that need superuser rights the tenant role does not have: Recovery Mode promotion, VACUUM FREEZE, and terminate-connections. Selecting a transaction-pooler port replaces it with a stronger warning, because that endpoint reassigns a backend per statement and so breaks query cancellation, transactional DDL with Auto-commit off, and explicit COMMIT/ROLLBACK.
- **New — `coruscant.core.connections` helpers** — `supabase_profile()`, `managed_provider()`, and `is_transaction_pooler()`, all GUI-free and unit-tested. Provider detection matches on host suffix, so lookalike hostnames such as `supabase.co.internal.lan` are correctly treated as self-hosted.
- **Docs — hosted PostgreSQL** — new "Hosted PostgreSQL" section in the Readme and section 4.8 in the User Manual covering connection setup, the session-vs-transaction pooler choice, and a table of which features work on managed instances. Recovery Mode and the Doctor repair sections gained matching caveats, and two rows were added to Known Limitations.
- **Fixed — documentation accuracy** — the Readme described cancellation as sending `pg_cancel_backend()`. `DatabaseManager.cancel()` actually issues a libpq cancel request via `psycopg2`'s `connection.cancel()`. The server-side effect is the same; the wording now matches the implementation.
- **Fixed — test suite on Windows** — `tests/test_ui_ast.py` read `connection.py` without an explicit encoding, so the `👁` glyph made ten tests fail under the Windows default codepage; `tests/test_logging_config.py` asserted a POSIX string prefix that cannot hold when the test runs on Windows. Both are fixed; the full suite now passes on Windows.
- **New — constant-binding regression guard** — `TestDialogConstantsAreBound` walks the AST of each dialog module and fails when an ALL_CAPS constant is referenced but never imported or defined. This catches a class of bug that syntax checks miss and that CI, which has no PySide6, cannot catch by import.
- **Fixed — User Manual section numbering** — the table of contents omitted **§12 ERD** entirely and then ran one number ahead of the body from §13 to §21, leaving 11 broken anchor links; the body itself skipped §21. Recovery Mode, Database Doctor, Live Database Monitor, and Security Guidance are renumbered §21–§24, the TOC now matches the body exactly, and all internal links resolve. Also corrected two cross-references that were wrong beforehand: a Logging link labelled "Section 14" pointing at `#16-logging`, and a Script Manager link numbered §19.
- **Fixed — contradictory guidance on deleting connections** — the Security section stated that saved entries "can only be removed by clearing the settings store manually", contradicting §4.5 and the **Delete** button that has always existed in the connection manager.
- **Docs — Cell Content Viewer** — new §7.7 documents double-clicking a result cell to open the viewer, its character count, the **Word Wrap** toggle, **Copy to Clipboard**, and the auto-close-after-copy behaviour. The viewer was mentioned in the Readme but absent from the manual, and the Word Wrap toggle appeared in neither.
- **Docs — Schema Browser toolbar** — new §9.5 documents all five toolbar buttons, including **📖 Guide** and **ℹ About**, plus the four **⚙ Settings** options in one table. The Guide button was previously undocumented in the manual.
- **Fixed — lost emoji in the Readme** — the Schema Browser list rendered the Guide entry as `**? Guide**`; restored to `**📖 Guide**`.
- **Fixed — Database Doctor: Table Bloat check never worked** — `BLOAT_SQL` selected `tablename` from `pg_stat_user_tables`, but that view calls the column `relname` (`tablename` belongs to `pg_tables`). Every run raised `column "tablename" does not exist`, so the Table Bloat card always rendered as an error and the VACUUM repairs behind it were unreachable. Found while capturing documentation screenshots against a live server. A new test validates every identifier in `BLOAT_SQL` against the real column set of `pg_stat_user_tables`; the previous test only checked that the constant existed.
- **Docs — regenerated HTML user manual** — `docs/USER_MANUAL.html` was hand-maintained, several versions stale, and had no build step. It is now generated from `USER_MANUAL.md` by `scratch/build_manual_html.py`, so the Markdown is the single source of truth. The page has a filterable sidebar with scroll-spy, styled tables, tip/warning callouts, a click-to-zoom lightbox, print styles, and a responsive layout. Screenshots are embedded as data URIs, so the file stays self-contained and can be opened or emailed on its own.
- **Docs — 11 UI screenshots** — captured from a live instance by `scratch/shoot_docs.py` against a throwaway PostgreSQL container. The script redirects `QSettings` to a temporary INI file so no real query history or saved connections can appear in shipped documentation, and renders windows off-screen so the desktop is not disturbed.
- **Fixed — window layout never persisted** — the Main toolbar and the Database Explorer dock were created without an `objectName`. `QMainWindow.saveState()` serialises docks and toolbars by object name, so it skipped both and logged `QMainWindow::saveState(): 'objectName' not set for …` on every shutdown; a moved, resized, or closed Database Explorer never came back on the next launch. Both now set one, and `saveState()` returns real data.
- **New — documentation integrity tests** (`tests/test_docs.py`) — 13 checks covering the defect class that produced this release's documentation fixes: every internal anchor link resolves, heading anchors are unique, the manual's contents and body agree on both section numbers and titles, numbering has no gaps, subsections are sequential, no emoji has been lost to an encoding round-trip, and both documents report the current package version. Each was verified by reintroducing the original defect and confirming the suite fails. The anchor checker replicates GitHub's slug algorithm exactly, including that it does not collapse runs of spaces.
- **New — encoding guard for the test suite** — an AST check that every `open()` / `read_text()` / `write_text()` in `tests/` names its encoding, so the Windows default codepage cannot break the suite on a non-ASCII glyph again.
- **New — layout-persistence regression guard** — `TestSaveStateWidgetsHaveObjectNames` walks the AST and fails when any `QToolBar` or `QDockWidget` is created without `setObjectName()`.
- **Version bump** — updated to 1.1.0 across all files and documentation.

### 1.0.9
- **New — Visual Query Builder (⚡)** — right-click any schema in the Schema Browser and choose **⚡ Query Builder** to compose a SELECT statement visually. Pick a base table, stack any number of **INNER / LEFT / RIGHT joins**, and tick the output fields per table (nothing ticked = `SELECT *`). Optional WHERE, ORDER BY (with ASC/DESC), and LIMIT controls round out the statement.
- **New — FK auto-linking** — when a join table is selected, the builder parses the schema's foreign-key definitions and pre-fills the `ON` condition automatically, flagging it with an **⚡ auto-linked** badge (hover for the detected relationship).
- **New — Live SQL preview** — a syntax-highlighted preview regenerates on every change. **⧉ Copy SQL** copies it to the clipboard; **▶ Insert into Editor** places it at the cursor in the active editor tab (never executed automatically), matching the behaviour of the existing script generators.
- **Fixed — Query Builder field list truncation** — column and table names in the Select Fields tree now resize to their contents instead of being cut off (e.g. `rel…`, `sta…`); a horizontal scrollbar appears when needed.
- **Version bump** — updated to 1.0.9 across all files and documentation.

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
