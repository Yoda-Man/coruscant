# Coruscant User Manual

**Version:** 0.9.0
**Author:** Marwa Trust Mutemasango

> *Named after the galactic capital of Star Wars — a city-planet that is essentially one giant information hub.*

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Getting Started](#2-getting-started)
   - 2.1 [System Requirements](#21-system-requirements)
   - 2.2 [Installation](#22-installation)
   - 2.3 [Launching the Application](#23-launching-the-application)
3. [The Interface at a Glance](#3-the-interface-at-a-glance)
4. [Connecting to PostgreSQL](#4-connecting-to-postgresql)
   - 4.1 [Opening the Connection Dialog](#41-opening-the-connection-dialog)
   - 4.2 [Filling in Connection Details](#42-filling-in-connection-details)
   - 4.3 [SSL Mode](#43-ssl-mode)
   - 4.4 [Testing a Connection](#44-testing-a-connection)
   - 4.5 [Recent Connections](#45-recent-connections)
   - 4.6 [Disconnecting](#46-disconnecting)
5. [Writing SQL](#5-writing-sql)
   - 5.1 [The SQL Editor](#51-the-sql-editor)
   - 5.2 [Multiple Editor Tabs](#52-multiple-editor-tabs)
   - 5.3 [Opening a SQL Script from File](#53-opening-a-sql-script-from-file)
   - 5.4 [Saving Your SQL to a File](#54-saving-your-sql-to-a-file)
   - 5.5 [Formatting SQL](#55-formatting-sql)
   - 5.6 [Clearing the Editor](#56-clearing-the-editor)
6. [Running Queries](#6-running-queries)
   - 6.1 [Executing the Full Script](#61-executing-the-full-script)
   - 6.2 [Running a Selection Only](#62-running-a-selection-only)
   - 6.3 [Setting a Row Limit](#63-setting-a-row-limit)
   - 6.4 [Cancelling a Running Query](#64-cancelling-a-running-query)
7. [Working with Results](#7-working-with-results)
   - 7.1 [Result Tab Types](#71-result-tab-types)
   - 7.2 [Filtering Rows](#72-filtering-rows)
   - 7.3 [Sorting Columns](#73-sorting-columns)
   - 7.4 [Copying Rows to the Clipboard](#74-copying-rows-to-the-clipboard)
   - 7.5 [Pinning and Renaming Result Tabs](#75-pinning-and-renaming-result-tabs)
   - 7.6 [NULL Values](#76-null-values)
   - 7.7 [Exporting Results](#77-exporting-results)
8. [Transaction Mode](#8-transaction-mode)
   - 8.1 [Auto-commit (Default)](#81-auto-commit-default)
   - 8.2 [Manual Transaction Mode](#82-manual-transaction-mode)
   - 8.3 [Committing](#83-committing)
   - 8.4 [Rolling Back](#84-rolling-back)
9. [Schema Browser](#9-schema-browser)
   - 9.1 [Navigating the Tree](#91-navigating-the-tree)
   - 9.2 [Inserting a SELECT Statement](#92-inserting-a-select-statement)
   - 9.3 [Refreshing the Schema](#93-refreshing-the-schema)
10. [Query History](#10-query-history)
11. [Parameterized Queries](#11-parameterized-queries)
12. [EXPLAIN and Query Plans](#12-explain-and-query-plans)
13. [Themes](#13-themes)
14. [Keyboard Shortcuts Reference](#14-keyboard-shortcuts-reference)
15. [Troubleshooting](#15-troubleshooting)
16. [Security Guidance](#16-security-guidance)

---

## 1. Introduction

### The Problem

If you have used pgAdmin, the most widely used GUI tool for PostgreSQL,
you have likely run into this: you write a script with several `SELECT`
statements, press Execute, and only the last result appears. The earlier
result sets are gone. This is a known limitation of pgAdmin's current
stable release. A fix is in development as of late 2025, but it has not
yet been released to users.

The impact is real. A migration script that validates data before and after
the change requires two queries. A diagnostic script may need five. Forcing
each into its own separate run breaks the logical flow of the work and
makes it harder to compare results side by side.

### The Solution

**Coruscant** was built specifically to address this gap. Every statement
in your script runs independently and produces its own result tab. Ten
`SELECT` statements produce ten tabs, each one sortable, filterable, and
exportable. You can pin the ones you want to keep, rename them for clarity,
and compare them without re-running anything.

### What Coruscant Does

Beyond multi-statement result display, Coruscant provides a complete
desktop SQL environment for PostgreSQL:

- **Write and run SQL:** syntax-highlighted editor with multi-tab support.
- **View results:** sortable, filterable tables with live row filtering.
- **Browse your schema:** tables, views, columns, indexes, foreign keys, and functions, with hover-to-view definitions.
- **Manage transactions:** auto-commit or manual mode with explicit Commit and Rollback.
- **Cancel queries cleanly:** sends `pg_cancel_backend()` to the server; the UI never freezes.
- **Parameterized queries:** named placeholders with safe server-side substitution.
- **Export results:** CSV or JSON with a single click.
- **Load and save SQL files:** open any `.sql` script and save your work to disk.

Everything runs in a single window. The application requires no server of
its own; it connects directly to your PostgreSQL instance.

---

## 2. Getting Started

### 2.1 System Requirements

| Item | Requirement |
|---|---|
| Operating System | Windows 10/11, macOS 11+, or Linux |
| PostgreSQL server | Any version from 9.x to 16+ |
| Python | 3.10 or newer *(only required when running from source)* |
| Screen resolution | 1280 × 720 minimum (1920 × 1080 recommended) |

### 2.2 Installation

There are two ways to install Coruscant.

---

**Option A — Download a pre-built binary (recommended)**

No Python installation required. Pre-built executables for all platforms are published on the GitHub Releases page.

1. Open the [**Releases** page](https://github.com/Yoda-Man/coruscant/releases) of the Coruscant repository.
2. Download the file for your operating system:

| Platform | File | How to run |
|---|---|---|
| Windows | `Coruscant.exe` | Double-click the file |
| macOS | `Coruscant-macOS.zip` | Unzip, then move `Coruscant.app` to your Applications folder and open it |
| Linux | `Coruscant` | Open a terminal: `chmod +x Coruscant && ./Coruscant` |

> **Linux note:** The binary requires `libGL`, `libglib-2.0`, and `libdbus-1` on the host machine. If the app does not start, install them:
> ```bash
> # Debian / Ubuntu
> sudo apt-get install libgl1 libglib2.0-0 libdbus-1-3
> # Fedora / RHEL
> sudo dnf install mesa-libGL glib2 dbus-libs
> ```

---

**Option B — Run from source**

Use this option if you want to inspect or modify the code.

```bash
cd DBClient
pip install -r requirements.txt
python main.py
```

> **Tip:** Using a virtual environment keeps dependencies isolated:
> ```bash
> python -m venv .venv
> .venv\Scripts\activate      # Windows
> source .venv/bin/activate   # macOS / Linux
> pip install -r requirements.txt
> ```

### 2.3 Launching the Application

**Pre-built binary:** open or double-click the downloaded file as described above.

**From source:**
```bash
python main.py
```

The Coruscant window opens with a dark theme by default. You can switch to a light theme at any time using the **🌙** button in the toolbar.

---

## 3. The Interface at a Glance

```
┌─────────────────────────────────────────────────────────────────────────┐
│  TOOLBAR                                                                │
│  [Connect] [Disconnect] | [▶ Execute] [⏹ Cancel] [Explain] [Explain+]  │
│  [Format SQL] [Clear] | [Open SQL…] [Save SQL…] | [+ Tab]              │
│  [Auto-commit ✓] [Commit] [Rollback] | Row limit: [1000] | [🌙] | [●]  │
├───────────────┬─────────────────────────────────────────────────────────┤
│               │                                                         │
│  Schema       │   SQL EDITOR TABS                                       │
│  Browser      │   ┌─────────────────────────────────────────────────┐  │
│               │   │  Query 1  │  Query 2  │  + Tab                  │  │
│  ─────────    │   │                                                  │  │
│               │   │  -- Write your SQL here                         │  │
│  Query        │   │  SELECT * FROM users;                           │  │
│  History      │   │                                                  │  │
│               │   └─────────────────────────────────────────────────┘  │
│               ├─────────────────────────────────────────────────────────┤
│               │                                                         │
│               │   RESULT TABS                                           │
│               │   ┌─────────────────────────────────────────────────┐  │
│               │   │  Query 1 (12 ms, 5 rows)  │  Query 2 (3 ms)    │  │
│               │   │  Filter: [          ]  Export CSV  Export JSON  │  │
│               │   │  ┌──────┬──────────┬────────────────────────┐  │  │
│               │   │  │  id  │  name    │  email                 │  │  │
│               │   │  ├──────┼──────────┼────────────────────────┤  │  │
│               │   │  │   1  │  Alice   │  alice@example.com     │  │  │
│               │   └─────────────────────────────────────────────────┘  │
├───────────────┴─────────────────────────────────────────────────────────┤
│  STATUS BAR:  Connected to mydb on localhost:5432                       │
└─────────────────────────────────────────────────────────────────────────┘
```

| Area | Purpose |
|---|---|
| **Toolbar** | All primary actions: connect, execute, open/save files, theme |
| **Schema Browser** (left dock, top) | Browse database objects |
| **Query History** (left dock, bottom) | Recent queries |
| **Editor Tabs** (centre, top) | Write and edit SQL |
| **Result Tabs** (centre, bottom) | View query output |
| **Status Bar** (bottom) | Connection info and execution messages |

---

## 4. Connecting to PostgreSQL

### 4.1 Opening the Connection Dialog

Click **Connect** in the toolbar. The connection dialog opens.

### 4.2 Filling in Connection Details

| Field | What to enter | Default |
|---|---|---|
| **Host** | Hostname or IP address of your PostgreSQL server | `localhost` |
| **Port** | Port PostgreSQL is listening on | `5432` |
| **Database** | Name of the database to connect to | *(required)* |
| **Username** | Your PostgreSQL role/user name | *(required)* |
| **Password** | Your password | *(required)* |
| **SSL mode** | Encryption level (see [Section 4.3](#43-ssl-mode)) | `prefer` |

Click **OK** to connect. The status bar and the connection indicator (● top-right of the toolbar) will turn green when connected.

### 4.3 SSL Mode

| Mode | When to use |
|---|---|
| `disable` | Local or trusted networks where SSL is not needed |
| `allow` | Let the server decide whether to use SSL |
| `prefer` | Use SSL if the server supports it, safe for most situations *(default)* |
| `require` | Always use SSL, but do not verify the certificate |
| `verify-ca` | Use SSL and verify the server's certificate against a Certificate Authority |
| `verify-full` | Strongest option: verify certificate and that the hostname matches |

For production databases over the internet, use `verify-full`.

### 4.4 Testing a Connection

Before clicking **OK**, click **Test Connection**. Coruscant opens a short-lived test connection and reports whether it succeeded. This does not change your current session.

### 4.5 Recent Connections

The top of the connection dialog shows a drop-down of up to 5 previously used connections. Select one to auto-fill all fields. Passwords are stored in an encoded form (not plaintext) in your operating system's settings store.

### 4.6 Disconnecting

Click **Disconnect** in the toolbar. Any open manual transaction will be abandoned by the server automatically.

---

## 5. Writing SQL

### 5.1 The SQL Editor

The main editing area supports:

- **Syntax highlighting:** keywords (blue), functions (yellow), strings (orange), numbers (green), comments (grey).
- **Multiple statements:** separate them with semicolons (`;`). Each statement runs independently and produces its own result tab.
- **Tab key:** inserts spaces for indentation.

### 5.2 Multiple Editor Tabs

You can have as many editor tabs open as you need. Each tab is independent.

| Action | Method |
|---|---|
| Open a new tab | Click **+ Tab** in the toolbar, or press **Ctrl+T** |
| Switch to next tab | **Ctrl+Tab** |
| Switch to previous tab | **Ctrl+Shift+Tab** |
| Close the current tab | Click the **×** on the tab, or press **Ctrl+W** |
| Reorder tabs | Drag a tab to a new position |

> If you close the last remaining tab, the editor is cleared rather than the tab being removed; there is always at least one editor tab open.

### 5.3 Opening a SQL Script from File

To load an existing `.sql` file from your computer:

1. Click **Open SQL…** in the toolbar.
2. A file browser opens. Navigate to your file.
3. Select a `.sql` or `.txt` file and click **Open**.
4. The file contents are loaded into the **current editor tab**, replacing any existing content.

> **Tip:** To load a script into a new tab without losing your current work, first press **Ctrl+T** to open a new tab, then click **Open SQL…**.

Supported file types in the picker: `.sql`, `.txt`, and all files (`*`).

### 5.4 Saving Your SQL to a File

To save the current editor content to disk:

1. Click **Save SQL…** in the toolbar.
2. Choose a folder and enter a filename.
3. Click **Save**.

The full editor content (not just a selection) is always saved.

### 5.5 Formatting SQL

Click **Format SQL** to auto-format the SQL in the current editor:

- SQL keywords are uppercased (`select` → `SELECT`).
- Identifiers are lowercased.
- Indentation is normalised.

If you have text **selected**, only the selected portion is formatted. The rest of the editor is untouched.

> Requires the `sqlparse` package (`pip install sqlparse`). If not installed, a prompt will appear.

### 5.6 Clearing the Editor

Click **Clear** to:
- Empty the current editor tab.
- Remove all unpinned result tabs.

Pinned result tabs are preserved.

---

## 6. Running Queries

### 6.1 Executing the Full Script

Press **F5** or click **▶ Execute**.

All statements in the editor are run in order. Each statement produces its own result tab:

```sql
SELECT * FROM users;          -- → result tab "Query 1"
SELECT count(*) FROM orders;  -- → result tab "Query 2"
UPDATE products SET active = true WHERE id = 5;  -- → "Query 3"
```

The status bar shows total execution time when done.

### 6.2 Running a Selection Only

Highlight any portion of SQL in the editor before pressing **F5**. Only the selected text is sent to the server. This is useful for testing a single statement within a larger script.

### 6.3 Setting a Row Limit

The **Row limit** spinner in the toolbar controls how many rows are fetched per `SELECT` statement.

| Setting | Behaviour |
|---|---|
| `1000` (default) | Fetch at most 1 000 rows |
| `0` (Unlimited) | Fetch all rows. Use with caution on large tables. |

When results are truncated, a yellow warning banner appears at the top of the result tab.

> Increasing the row limit on very large tables can make the application slow or use significant memory.

### 6.4 Cancelling a Running Query

If a query is taking too long:

- Click **⏹ Cancel** in the toolbar, or
- Press **Escape**.

PostgreSQL is sent a cancellation signal. The status bar shows *"Query cancelled."* No error dialog appears. You can immediately run another query.

> Cancel is also available during EXPLAIN and EXPLAIN+ operations.

---

## 7. Working with Results

### 7.1 Result Tab Types

After execution, each statement gets its own tab:

| What ran | Tab shows |
|---|---|
| `SELECT` or `RETURNING` | A sortable, filterable table of rows |
| `INSERT`, `UPDATE`, `DELETE`, DDL | A success message with the number of rows affected |
| `EXPLAIN` / `EXPLAIN+` | The query plan as monospace text |
| A failed statement | An error tab with the full error message (no popup dialog) |

### 7.2 Filtering Rows

Each result table has a **Filter** box in the top-right corner.

1. Click the Filter box and start typing.
2. Rows that do not contain your text (in any column) are hidden instantly.
3. The match count updates live next to the filter box.
4. Clear the filter box to show all rows again.

Filtering is case-insensitive and searches all columns simultaneously.
Type `null` to find rows with NULL values.

### 7.3 Sorting Columns

Click any column header to sort by that column ascending. Click again to sort descending. Click a third time to remove the sort.

### 7.4 Copying Rows to the Clipboard

1. Click a row to select it (hold **Ctrl** or **Shift** to select multiple rows).
2. Press **Ctrl+C**.

The selected rows are copied as tab-separated values (TSV) with a header row. Paste directly into Excel, Google Sheets, or a text editor.

### 7.5 Pinning and Renaming Result Tabs

By default, result tabs are cleared each time you run a new query. To keep a tab:

**Pinning:**
1. Right-click the result tab.
2. Select **Pin**.
3. The tab title gains a 📌 prefix.
4. Pinned tabs survive subsequent query runs.
5. Right-click and select **Unpin** to restore normal behaviour.

**Renaming:**
1. Right-click the result tab and select **Rename…**, or
2. Double-click the tab title.
3. Type a new name and press **Enter**.

### 7.6 NULL Values

Database `NULL` values are displayed as grey italic *NULL* in result tables, visually distinct from the string value `"NULL"`.

When exporting to CSV, `NULL` is written as an empty cell.

### 7.7 Exporting Results

Each result table has two export buttons:

**Export CSV**
1. Click **Export CSV**.
2. Choose a save location.
3. A UTF-8 CSV file is created with a header row. `NULL` values become empty strings.

**Export JSON**
1. Click **Export JSON**.
2. Choose a save location.
3. A JSON array of objects is created. Special types are handled:
   - Dates and timestamps → ISO 8601 strings (e.g. `"2024-03-15T10:30:00"`)
   - Decimal numbers → floating-point numbers
   - Binary data → hex strings

> Exports always use the **full unfiltered result set**, regardless of what the filter box shows.

---

## 8. Transaction Mode

### 8.1 Auto-commit (Default)

When **Auto-commit** is checked (the default), every statement that runs is immediately and permanently committed to the database. This is the simplest mode and is suitable for most day-to-day querying.

### 8.2 Manual Transaction Mode

Uncheck **Auto-commit** in the toolbar to switch to manual mode. In this mode:

- Statements run inside an open transaction.
- Changes are **not visible** to other database connections until you commit.
- You can roll everything back if you make a mistake.

**When to use manual mode:**
- Testing a complex migration before committing it.
- Making a series of related changes that must all succeed or all be reverted.
- Previewing the effect of a `DELETE` or `UPDATE` before making it permanent.

**Example workflow:**
```sql
-- 1. Switch to manual mode (uncheck Auto-commit)

-- 2. Run a destructive operation
DELETE FROM orders WHERE created_at < '2020-01-01';

-- 3. Check the result
SELECT count(*) FROM orders;

-- 4a. If correct → click Commit
-- 4b. If wrong   → click Rollback
```

### 8.3 Committing

Click **Commit** in the toolbar. All changes made since the last commit (or since you switched to manual mode) are permanently saved.

### 8.4 Rolling Back

Click **Rollback** in the toolbar. All changes made since the last commit are discarded. The database returns to its previous state.

> **Note:** Disconnecting while a transaction is open causes the server to roll it back automatically. Always commit or rollback before disconnecting if you want to keep your changes.

> **DDL and transactions:** In PostgreSQL, DDL statements like `CREATE TABLE` and `ALTER TABLE` are transactional. In manual mode, you can roll back a `CREATE TABLE` just like a `DELETE`.

---

## 9. Schema Browser

The **Database Explorer** panel on the left side of the window shows a live tree of your database objects.

### 9.1 Navigating the Tree

```
public                          ← schema (bold)
  ├── users  [T]                ← table [T] or view [V]
  │     ├── Columns (3)
  │     │     id         integer
  │     │     name       text
  │     │     created_at timestamp with time zone
  │     ├── Indexes (2)
  │     │     users_pkey          ← hover to see: CREATE UNIQUE INDEX...
  │     │     users_email_idx
  │     └── Foreign Keys (1)
  │           fk_users_role_id   ← hover to see: FOREIGN KEY (role_id)...
  └── Functions / Procedures (1)
        get_active_users   integer
```

- Click the **▶** arrow next to any node to expand it.
- **Hover** over an index or foreign key name to see its full SQL definition in a tooltip.
- Column data types are shown in the second column of the tree.

### 9.2 Inserting a SELECT Statement

**Double-click a table or view** to insert a ready-to-run SELECT statement at the cursor position in the active editor:

```sql
SELECT * FROM "public"."users" LIMIT 100;
```

**Double-click a function** to insert a SELECT call template:

```sql
SELECT "public"."get_active_users"();
```

You can then edit the inserted SQL before running it.

### 9.3 Refreshing the Schema

The schema tree is loaded automatically when you connect. If you make schema changes (e.g. `CREATE TABLE`, `ALTER TABLE`) click the **Refresh** button at the top of the Schema Browser to reload the tree.

---

## 10. Query History

The **Query History** panel is at the bottom of the left dock, below the Schema Browser.

It stores the last **100** queries you have successfully executed, along with:
- The first 80 characters of the SQL (as a preview).
- The date and time it was run.
- How long it took to execute.

**Using history:**
- **Double-click** any entry to load the full SQL into the active editor tab.
- **Hover** over an entry to see a tooltip with the complete SQL.

**Managing history:**
- Click **Clear History** to delete all entries.
- History is saved between sessions and persists when you close and reopen Coruscant.

> Consecutive identical queries are deduplicated. Re-running the same SQL updates the timestamp rather than adding a new entry.

---

## 11. Parameterized Queries

Parameterized queries let you write SQL with named placeholders and supply the values separately. This is safer than string-concatenating values into SQL, and makes it easy to re-run the same query with different inputs.

### Syntax

Use `%(name)s` placeholders in your SQL:

```sql
SELECT * FROM orders
WHERE customer_id = %(customer_id)s
  AND status      = %(status)s
  AND total       > %(min_total)s;
```

### Opening the Parameters Panel

Click **Parameters ▸** in the top-right corner of the editor tab. The panel expands below the editor.

### Adding Parameters

1. Click **Add Row** in the Parameters panel.
2. Type the parameter name (without `%` or `()`) in the **Parameter** column.
3. Type the value in the **Value** column.

| Parameter | Value |
|---|---|
| `customer_id` | `1042` |
| `status` | `shipped` |
| `min_total` | `50.00` |

### Running

Press **F5** as normal. Values are substituted safely before the query is sent to PostgreSQL; there is no risk of SQL injection.

> The same parameter dictionary is applied to **all statements** in the editor. If you have multiple statements, they all share the same parameters.

### Removing Parameters

Select a row in the Parameters panel and click **Remove Row**.

---

## 12. EXPLAIN and Query Plans

EXPLAIN shows how PostgreSQL plans to execute a query without actually running it (for `EXPLAIN`) or by running it and reporting real statistics (for `EXPLAIN+`).

### Explain

Click **Explain** in the toolbar. Coruscant prepends `EXPLAIN` to the first statement in the editor and runs it. The query plan appears in an **ExplainResult** tab as formatted text.

```
Seq Scan on users  (cost=0.00..1.05 rows=5 width=36)
  Filter: (active = true)
```

### Explain+ (EXPLAIN ANALYZE)

Click **Explain+** in the toolbar. This runs `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)`, so the query actually executes and PostgreSQL reports real timing and buffer statistics.

```
Seq Scan on users  (cost=0.00..1.05 rows=5 width=36)
                   (actual time=0.012..0.018 rows=5 loops=1)
  Filter: (active = true)
Planning Time: 0.1 ms
Execution Time: 0.3 ms
```

> **EXPLAIN+** actually modifies the database if the statement is an INSERT, UPDATE, or DELETE. Use with caution, or with **Auto-commit** off so you can roll back.

> Only the **first statement** in the editor is explained, even if multiple statements are present.

---

## 13. Themes

Click the **🌙** (dark) or **☀** (light) button on the right side of the toolbar to switch themes.

| Theme | Best for |
|---|---|
| Dark (default) | Low-light environments, reduced eye strain |
| Light | Printing, presentations, bright environments |

Your preference is saved automatically and restored the next time you launch Coruscant.

---

## 14. Keyboard Shortcuts Reference

| Shortcut | Action |
|---|---|
| **F5** | Execute the full SQL script (or selection if text is selected) |
| **Escape** | Cancel the currently running query |
| **Ctrl+T** | Open a new editor tab |
| **Ctrl+W** | Close the current editor tab |
| **Ctrl+Tab** | Switch to the next editor tab |
| **Ctrl+Shift+Tab** | Switch to the previous editor tab |
| **Ctrl+C** *(in a result table)* | Copy selected rows to clipboard as TSV |

---

## 15. Troubleshooting

### "Could not connect" error

- Check that the PostgreSQL server is running.
- Verify the host, port, database name, and credentials.
- Check your firewall; port 5432 must be reachable from your machine.
- Use **Test Connection** in the dialog to get a detailed error message.
- If connecting to a remote server, try changing **SSL mode** to `require`.

### Query runs but returns no results

- Ensure you are connected to the correct database.
- Check the **Schema Browser** to confirm the table exists in the expected schema.
- If you used a row limit, try setting it to `0` (Unlimited).

### Query seems to hang / never finishes

- Click **⏹ Cancel** or press **Escape** to stop it.
- Check whether the table is very large, or whether another session holds a lock.
- Use **Explain+** to inspect the query plan and look for sequential scans on large tables.

### "Auto-commit" toggle is greyed out

- The toggle is disabled while a query is running. Wait for it to finish (or cancel it) before changing transaction mode.

### Schema Browser is empty after connecting

- Click **Refresh** in the Schema Browser header.
- Confirm that your PostgreSQL user has `SELECT` privileges on `information_schema`.

### Formatting does nothing / shows a warning

- Install `sqlparse`: `pip install sqlparse>=0.4`

### The app window is very small / cut off

- Drag the splitter bar between the editor and results panels to resize them.
- Drag the left dock border to widen the Schema Browser.
- The window can be resized and maximised normally.

### Error tab appears instead of results

- Click the **⚠ Error** tab to read the full error message.
- Common causes: syntax errors in SQL, missing tables, permission errors, type mismatches.
- Fix the SQL in the editor and press **F5** again.

---

## 16. Security Guidance

### Saved Passwords

Connection passwords are encoded (base64) before being saved to your operating system's settings store:

- **Windows:** Registry (`HKEY_CURRENT_USER\Software\Coruscant`)
- **macOS:** `~/Library/Preferences/Coruscant.plist`
- **Linux:** `~/.config/Coruscant/Coruscant.conf`

This encoding **is not encryption**. Anyone with access to the settings store can decode the passwords. On a shared or corporate machine:

- Use the most restrictive account permissions possible.
- Clear recent connections when finished: open the connection dialog and note that saved entries can only be removed by clearing the settings store manually.
- Consider using PostgreSQL's `~/.pgpass` file instead of saving passwords in Coruscant; enter the password manually each time and do not click OK until you have checked the connection details.

### SSL Recommendations

| Environment | Recommended SSL mode |
|---|---|
| Local development (`localhost`) | `disable` or `prefer` |
| Internal network, trusted | `prefer` |
| Internet / cloud database | `require` or `verify-full` |
| Regulated / sensitive data | `verify-full` |

### Least-Privilege Database Users

Connect with a PostgreSQL role that has only the permissions your work requires:

- Read-only analysis → `SELECT` privileges only.
- Schema changes → include `CREATE`, `ALTER` as needed.
- Avoid connecting as `postgres` (superuser) for routine work.

### SQL Injection

Coruscant uses `cursor.mogrify()` for parameterized queries, which safely escapes all values. However, if you manually concatenate user-supplied strings into your SQL, those queries are not protected. Always use the Parameters panel for variable values.

---

*End of User Manual, Coruscant v0.9.0*
*Author: Marwa Trust Mutemasango*
