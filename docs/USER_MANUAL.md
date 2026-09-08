# Coruscant User Manual

**Version:** 1.1.3
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
   - 4.7 [Auto-reconnect](#47-auto-reconnect)
   - 4.8 [Connecting to Hosted PostgreSQL](#48-connecting-to-hosted-postgresql)
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
   - 7.7 [Viewing a Single Cell](#77-viewing-a-single-cell)
   - 7.8 [Exporting Results](#78-exporting-results)
8. [Transaction Mode](#8-transaction-mode)
   - 8.1 [Auto-commit (Default)](#81-auto-commit-default)
   - 8.2 [Manual Transaction Mode](#82-manual-transaction-mode)
   - 8.3 [Committing](#83-committing)
   - 8.4 [Rolling Back](#84-rolling-back)
9. [Schema Browser](#9-schema-browser)
   - 9.1 [Navigating the Tree](#91-navigating-the-tree)
   - 9.2 [Generating Scripts from a Table or Schema](#92-generating-scripts-from-a-table-or-schema)
   - 9.3 [Inserting a SELECT Statement](#93-inserting-a-select-statement)
   - 9.4 [Refreshing the Schema](#94-refreshing-the-schema)
   - 9.5 [The Schema Browser Toolbar](#95-the-schema-browser-toolbar)
   - 9.6 [Visual Query Builder](#96-visual-query-builder)
10. [QA Engine](#10-qa-engine)
    - 10.1 [Running the QA Engine](#101-running-the-qa-engine)
    - 10.2 [Understanding the Results](#102-understanding-the-results)
    - 10.3 [Suppressing Findings](#103-suppressing-findings)
    - 10.4 [Finding Scripts for a Finding](#104-finding-scripts-for-a-finding)
    - 10.5 [Exporting Findings to CSV](#105-exporting-findings-to-csv)
    - 10.6 [Auto-QA on Connect](#106-auto-qa-on-connect)
11. [Mind Map](#11-mind-map)
    - 11.1 [Schema Mind Map](#111-schema-mind-map)
    - 11.2 [Mind Map from a Table](#112-mind-map-from-a-table)
    - 11.3 [Navigating the Map](#113-navigating-the-map)
12. [ERD](#12-erd)
    - 12.1 [Generating an ERD](#121-generating-an-erd)
    - 12.2 [What the Diagram Shows](#122-what-the-diagram-shows)
    - 12.3 [Navigating the ERD](#123-navigating-the-erd)
    - 12.4 [Saving the ERD](#124-saving-the-erd)
13. [Query History](#13-query-history)
14. [Parameterized Queries](#14-parameterized-queries)
15. [EXPLAIN and Query Plans](#15-explain-and-query-plans)
16. [Themes](#16-themes)
17. [Logging](#17-logging)
18. [Support Script Manager](#18-support-script-manager)
19. [Keyboard Shortcuts Reference](#19-keyboard-shortcuts-reference)
20. [Troubleshooting](#20-troubleshooting)
21. [Recovery Mode](#21-recovery-mode)
    - 21.1 [What Recovery Mode Means](#211-what-recovery-mode-means)
    - 21.2 [Automatic Detection on Connect](#212-automatic-detection-on-connect)
    - 21.3 [The Recovery Dialog](#213-the-recovery-dialog)
    - 21.4 [Promoting to Primary — One Click](#214-promoting-to-primary--one-click)
    - 21.5 [Safety Considerations](#215-safety-considerations)
22. [Database Doctor](#22-database-doctor)
23. [Live Database Monitor](#23-live-database-monitor)
24. [Security Guidance](#24-security-guidance)

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
- **Cancel queries cleanly:** sends a cancel request to the server so it stops work on its side; the UI never freezes.
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
| Python | 3.10+ *(only required when running from source)* |
| networkx | 2.6+ *(required for Support Script Manager)* |
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
| **Password** | Your password — any characters, including `$`, `@`, `%`, `&`, `/`, and spaces | *(required)* |
| **SSL mode** | Encryption level (see [Section 4.3](#43-ssl-mode)) | `prefer` |

**Passwords with special characters** work correctly. Coruscant passes the password directly to the PostgreSQL driver as a raw string via keyword argument — it never constructs a URI or DSN string. Auto-generated passwords from cloud providers (AWS RDS, Azure, HashiCorp Vault) and corporate password managers routinely include `$`, `@`, and `%`; all of these work as-is.

Click the **👁** button to the right of the Password field to reveal what you typed and confirm it is correct before connecting. This is particularly useful for long or complex passwords where a typo is hard to spot. Click **👁** again to hide it.

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

> **Tip:** If the test fails with an authentication error and you are certain the credentials are correct, click **👁** to reveal the password and verify that no character was silently dropped or changed (some input methods or clipboard managers can alter special characters). Once confirmed, click **Test Connection** again.

### 4.5 Recent Connections

The top of the connection dialog shows a drop-down of up to 5 previously used connections. Select one to auto-fill all fields. Passwords are stored in an encoded form (not plaintext) in your operating system's settings store.

**Removing a connection:**
To delete a connection from your history, select it in the drop-down and click the **🗑** (trash) button. You will be asked to confirm the removal.

### 4.6 Disconnecting

Click **Disconnect** in the toolbar. Any open manual transaction will be abandoned by the server automatically.

### 4.7 Auto-reconnect

Coruscant includes an automatic reconnection feature to handle idle timeouts or transient network drops. 

When your database connection is closed by the server (often after being idle for several minutes), Coruscant will:

1. Update the connection indicator in the toolbar to **Ready (Auto-reconnect)** (orange color).
2. Automatically attempt to re-establish the connection the next time you click **Execute**, **Refresh**, or perform any action that requires a database connection.
3. If the reconnection is successful, your query or action will proceed immediately.

This ensures you don't have to manually re-enter credentials or reopen the connection dialog if you step away from your desk and the connection times out.

### 4.8 Connecting to Hosted PostgreSQL

Hosted PostgreSQL services Supabase, Neon, Amazon RDS, Azure Database for PostgreSQL are ordinary PostgreSQL servers. Coruscant connects to them through the same connection dialog described above; there is no separate mode or plugin to install.

**Supabase shortcut.** For Supabase you can skip most of the typing. In the connection manager click **Supabase…**, paste the project reference, choose the region, and leave the endpoint on **Session pooler — recommended**. Coruscant fills in the host, port `5432`, database `postgres`, the `postgres.<project-ref>` username, and SSL mode `require`. Enter the database password in the form afterwards and click **Test Connection**.

**Step by step (any provider):**

1. Open your provider's connection details panel. On Supabase this is **Project → Connect**; other providers use similar wording.
2. Choose the **session pooler** or the **direct connection**, not the transaction pooler. See the warning below.
3. Copy the host, port, database name, and username exactly as the provider shows them. Do not assume the username is `postgres` several providers qualify it with the project identifier, for example `postgres.abcdefghijklm`.
4. Enter the database password. This is the database password from the provider, which is not the same as your account login for their web console.
5. Set **SSL Mode** to `require`. Most hosted providers refuse unencrypted connections, so `prefer` may appear to work while silently falling back. Use `verify-full` if your provider documents a CA certificate.
6. Click **Test Connection** to confirm before saving.

> **Warning: avoid transaction poolers.** Many hosted providers offer a transaction pooler alongside the session pooler, usually on a different port on Supabase the transaction pooler is port `6543`. A transaction pooler can hand each statement to a different backend, which breaks three Coruscant features that need a stable session:
>
> - **Cancelling a running query** (section 6.4), which is keyed to the backend assigned when the connection opened
> - **Transaction Mode** with Auto-commit switched off (section 8)
> - **Explicit COMMIT and ROLLBACK**
>
> Ordinary queries still run, so the problem is easy to miss until a cancel or a rollback quietly fails to do what you expect. Use the session pooler or direct connection instead.

**Features that do not apply to hosted databases.** Managed providers do not grant superuser rights to the account you connect with, and they manage replication and failover themselves. As a result:

| Feature | On hosted PostgreSQL |
|---|---|
| Recovery Mode detection | Works reports the server state correctly |
| Recovery Mode **Promote to Primary** | Unavailable `pg_promote()` is not permitted |
| Doctor health checks | Work all four checks are read-only |
| Doctor **VACUUM FREEZE** | Usually fails needs ownership of every table |
| Doctor **Kill Selected Blocker** / **Terminate Idle** | Usually fails terminating another role's backend needs superuser rights |
| Live Database Monitor | Works though connection counts reflect the pooler, not your session alone |
| Everything else | Works normally |

---

## 5. Writing SQL

### 5.1 The SQL Editor

The main editing area supports:

- **Syntax highlighting:** keywords (blue), functions (yellow), strings (orange), numbers (green), comments (grey).
- **Multiple statements:** separate them with semicolons (`;`). Each statement runs independently and produces its own result tab.
- **Tab key:** inserts spaces for indentation.

**Line numbers** are shown in a gutter to the left of the editor. The active line
is highlighted in blue; the current-line band provides a subtle highlight across
the full width. Toggle both in the **⚙ Settings** panel of the Schema Browser.

**Current-line highlight** follows the cursor automatically.

### 5.2 Multiple Editor Tabs

You can have as many editor tabs open as you need. Each tab is independent.

| Action | Method |
|---|---|
| Open a new tab | Click **+ Tab** in the toolbar, or press **Ctrl+T** |
| Switch to next tab | **Ctrl+Tab** |
| Switch to previous tab | **Ctrl+Shift+Tab** |
| Close the current tab | Click the **×** on the tab, or press **Ctrl+W** |
| Reorder tabs | Drag a tab to a new position |

**Independent Results:**
Each editor tab maintains its own private collection of result tabs. When you switch between editor tabs, the result area at the bottom of the window automatically switches to show the results belonging to that specific tab. This allows you to work on multiple queries in parallel without them interfering with each other's results.

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

### 7.7 Viewing a Single Cell

Wide columns are awkward to read in a grid. **Double-click any cell** to open the Cell Content Viewer, a read-only monospaced window sized for long values — JSON documents, XML fragments, stack traces, or any text that the column is too narrow to show.

The viewer provides:

| Control | Purpose |
|---|---|
| Character count | Shown top-left, so you can see the true length of the value |
| **Word Wrap** | On by default. Untick it to keep long lines unwrapped and scroll horizontally instead — useful for reading aligned or single-line JSON |
| **Copy to Clipboard** | Copies the entire cell value, not the visible portion. The button briefly confirms with *Copied!* |
| **Close** | Dismisses the viewer |

By default the viewer closes itself about a second and a half after you copy, on the assumption that copying was what you came to do. To keep it open instead, untick **Auto-close cell viewer after copy** in the Schema Browser's **⚙ Settings** panel.

### 7.8 Exporting Results

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

### 9.2 Generating Scripts from a Table or Schema

**Right-click any schema** in the tree to open a schema-level menu.

| Menu option | What it does |
|---|---|
| **⚡ Query Builder** | Opens the visual Query Builder — compose a SELECT with joins and field selection (see [§9.6](#96-visual-query-builder)) |
| **Generate ERD** | Opens an entity-relationship diagram for the schema in your browser |
| **🗺 Mind Map** | Opens a D3.js force-directed graph of all tables and FK relationships (see [§11.1](#111-schema-mind-map)) |
| **🔍 QA Engine** | Runs an automated health check on the schema (see [§10](#10-qa-engine)) |

**Right-click any table or view** in the tree to open a script generator menu.

| Menu option | What is inserted / done |
|---|---|
| **SELECT script** | `SELECT` with every column listed explicitly, a `WHERE` placeholder, and `LIMIT 100` |
| **UPDATE script** | `UPDATE … SET` with a `col = ` placeholder for every column and a `WHERE` placeholder |
| **DELETE script** | `DELETE FROM … WHERE` seeded with the table's first column |
| **🗺 Mind Map from here** | Opens a focused mind map with BFS wave-reveal starting from this table (see [§11.2](#112-mind-map-from-a-table)) |

The script is inserted at the cursor position in the active editor tab but **not executed**. Fill in the placeholder values and press **F5** when ready.

**Example — right-clicking a `users` table with columns `id`, `name`, `email`:**

SELECT script:
```sql
SELECT
    "id",
    "name",
    "email"
FROM "public"."users"
WHERE
LIMIT 100;
```

UPDATE script:
```sql
UPDATE "public"."users"
SET
    "id" = ,
    "name" = ,
    "email" = 
WHERE ;
```

DELETE script:
```sql
DELETE FROM "public"."users"
WHERE "id" = ;
```

### 9.3 Inserting a SELECT Statement

**Double-click a table or view** to insert a quick `SELECT *` at the cursor:

```sql
SELECT * FROM "public"."users" LIMIT 100;
```

**Double-click a function** to insert a SELECT call template:

```sql
SELECT "public"."get_active_users"();
```

### 9.4 Refreshing the Schema

The schema tree is loaded automatically when you connect. If you make schema changes (e.g. `CREATE TABLE`, `ALTER TABLE`) click the **Refresh** button at the top of the Schema Browser to reload the tree.

> **Tip:** If the Schema Browser shows nothing after connecting, verify that you connected to the correct database. The `postgres` system database contains almost no user objects. Check the connection dialog's **Database** field.

### 9.5 The Schema Browser Toolbar

Five buttons sit at the top of the Schema Browser:

| Button | Action |
|---|---|
| **↻ Refresh** | Reload the schema tree (see [§9.4](#94-refreshing-the-schema)) |
| **📜 Scripts** | Open the Support Script Manager (see [§18](#18-support-script-manager)) |
| **⚙ Settings** | Show or hide the settings panel described below |
| **📖 Guide** | Open the built-in quick-reference guide — a single window listing every keyboard shortcut and the main workflows, available offline with no connection required |
| **ℹ About** | Version, licence, and credits |

**The ⚙ Settings panel.** Click **⚙ Settings** to expand it. Four options are available, and each is remembered across restarts:

| Option | Default | Effect |
|---|---|---|
| **Auto-complete** | On | Suggest table, column, and keyword names as you type in the editor. Also available on demand with **Ctrl+Space** |
| **Line numbers in editor** | On | Show the line-number gutter, with the active line highlighted (see [§5.1](#51-the-sql-editor)) |
| **Auto-close cell viewer after copy** | On | Dismiss the Cell Content Viewer shortly after you copy a value (see [§7.7](#77-viewing-a-single-cell)) |
| **Run QA Engine on connect** | Off | Run the QA Engine automatically after connecting (see [§10.6](#106-auto-qa-on-connect)) |

### 9.6 Visual Query Builder

**Right-click any schema** and choose **⚡ Query Builder** to compose a SELECT statement visually — no SQL typing required.

The dialog is split into four areas:

**FROM — base table.** Pick the table the query starts from.

**Joins.** Click **＋ Add Join** to stack as many joins as you need. Each join row lets you choose:

| Control | Purpose |
|---|---|
| Join type | **INNER JOIN**, **LEFT JOIN**, or **RIGHT JOIN** |
| Table | The table being joined in |
| ON … = … | Left side: any column from the tables already in the query; right side: a column of the joined table |
| ✕ | Remove the join |

When you pick a join table, Coruscant checks the schema's foreign-key definitions. If a FK links the new table to any table already in the query, the `ON` condition is filled in automatically and the row shows an **⚡ auto-linked** badge — hover it to see the detected relationship. You can still override either side manually.

**Select fields.** Every table in the query appears with its columns and data types. Tick the columns you want in the output, or use **All** / **None**. If nothing is ticked the query falls back to `SELECT *`.

**Options and preview.** An optional **WHERE** expression, an **ORDER BY** column with ASC/DESC, and a **LIMIT** spinner (on by default, 100). Below them, a **live syntax-highlighted SQL preview** regenerates on every change.

**Example** — `applicant_relationship` joined to `applicant`:

```sql
SELECT
    "applicant_relationship"."related_applicant_id",
    "applicant_relationship"."status",
    "applicant_relationship"."valid_from",
    "applicant_relationship"."valid_to"
FROM "epass_application"."applicant_relationship"
INNER JOIN "epass_application"."applicant"
    ON "applicant_relationship"."related_applicant_id" = "applicant"."applicant_id"
LIMIT 100;
```

When you are happy with the statement:

- **⧉ Copy SQL** — copies the preview to the clipboard.
- **▶ Insert into Editor** — inserts the statement at the cursor in the active editor tab and closes the dialog. Like the script generators, the SQL is **never executed automatically** — press **F5** or **Ctrl+Enter** when ready.

---

## 10. QA Engine

The **QA Engine** performs an automated health check on your PostgreSQL schema. It runs six checks in a background thread and presents the results in a colour-coded dialog with a 0–100 health score.

### 10.1 Running the QA Engine

Right-click any **schema** in the Schema Browser tree and choose **🔍 QA Engine**. A status indicator appears at the bottom of the Schema Browser while the checks run. When complete, the QA report dialog opens automatically.

### 10.2 Understanding the Results

The report dialog shows a health score badge at the top and a table of findings below. Each finding has:

| Column | Content |
|---|---|
| **Severity** | `ERROR` (red), `WARNING` (amber), or `INFO` (blue) |
| **Check** | Which of the six checks flagged this finding |
| **Table** | The affected table (or `—` for schema-wide checks) |
| **Column** | The affected column where applicable |
| **Message** | Human-readable description of the problem |
| **Fix SQL** | A ready-to-use SQL statement to resolve the issue (where available) |

**Health score** is calculated as `100 − (ERROR × 10 + WARNING × 5 + INFO × 1)`, clamped to 0–100. Green ≥ 80, amber ≥ 50, red below 50.

**The six checks:**

**Orphaned tables** — tables with no FK relationships. These are completely isolated in the schema graph. A high count often indicates dead code, staging tables, or schema drift.

**Missing FK indexes** — every FK column should have a covering index; without one, JOIN and DELETE operations on the referenced table require a full sequential scan of the child table. The Fix SQL column contains a `CREATE INDEX CONCURRENTLY` statement you can run without locking the table.

**Circular FK cycles** — tables that form a closed FK dependency loop. These make `TRUNCATE … CASCADE` and ordered inserts difficult. The message lists the full cycle.

**Nullable FKs** — FK columns that allow `NULL`. A NULL FK means the row references no parent, which is sometimes intentional (optional relationship) but often accidental. The engine flags these at `WARNING` level for manual review.

**Naming violations** — tables or columns whose names do not follow `snake_case` (e.g. `CamelCase`, `mixedCase`, names with spaces). PostgreSQL folds unquoted identifiers to lowercase, so non-`snake_case` names require quoting everywhere they appear.

**Type inconsistencies** — the same column name (e.g. `customer_id`) appears in multiple tables with different data types. This often indicates a schema design error or a migration that was partially applied.

### 10.3 Suppressing Findings

Select one or more findings in the table, then click **🔕 Suppress**. A dialog asks whether to suppress:

- **This table only** (`check:table` rule) — the finding will be hidden for this specific table in future runs.
- **All tables** (`check:*` rule) — the finding will be hidden for every table in future runs of this check.

Suppressed findings are excluded from the results table and do not count toward the health score. Rules are saved in QSettings and persist across sessions and restarts.

To review or remove suppression rules, click **🔕 Manage Suppressions**. A dialog lists all active rules; select any rule and click **Remove** to restore the finding.

### 10.4 Finding Scripts for a Finding

Select a finding in the table and click **🔎 Find Scripts**. The Script Manager opens with a pre-populated search query combining the check name, table name, and column name. If you have a script collection indexed, relevant maintenance scripts appear immediately.

> Requires a script index to be loaded first. See [§18](#18-support-script-manager) for setup instructions.

### 10.5 Exporting Findings to CSV

Click **📄 Export CSV** to save all findings (including suppressed ones) to a CSV file. The file contains columns: `schema`, `check`, `severity`, `table`, `column`, `message`, `fix_sql`.

### 10.6 Auto-QA on Connect

To run the QA Engine automatically every time you connect to a database:

1. Open the **⚙ Settings** panel in the Schema Browser.
2. Check **Run QA Engine on connect**.

When enabled, Coruscant runs the QA Engine on the first schema immediately after the schema tree finishes loading.

---

## 11. Mind Map

The **Mind Map** feature generates an interactive graph of your schema's tables and FK relationships and opens it in your default web browser as a self-contained HTML file. No internet connection is required.

### 11.1 Schema Mind Map

Right-click any **schema** in the Schema Browser and choose **🗺 Mind Map**. Coruscant queries the database for table row counts and FK edges in a background thread (a status label appears at the bottom of the Schema Browser panel). When ready, the map opens in your browser.

**What you see:**
- Every table in the schema is a circular node.
- FK relationships are edges (arrows) between nodes.
- **Node size** is proportional to the table's row count — larger nodes hold more data.
- **Node colour** transitions from blue (few FK connections) to red (many FK connections), giving you an immediate visual of the most-connected tables.
- Hovering over a node shows a tooltip with the table name, row count, and FK count.

### 11.2 Mind Map from a Table

Right-click any **table** in the Schema Browser and choose **🗺 Mind Map from here**. The same schema graph opens, but with a **BFS wave-reveal animation** that starts from the selected table:

1. The selected table appears first (wave 0), highlighted.
2. Its immediate FK neighbours appear next (wave 1).
3. Their neighbours appear after that (wave 2), and so on.

This makes the table's neighbourhood immediately visible and reduces the initial visual noise of a large schema.

### 11.3 Navigating the Map

| Action | Result |
|---|---|
| **Click and drag** (background) | Pan the graph |
| **Scroll wheel** | Zoom in / out |
| **Click and drag** (node) | Pin the node in place; drag it to rearrange |
| **Search box** (top-left) | Type a table name to highlight matching nodes |
| **Double-click** (node) | Re-centres the view on that node |

The map is generated as a single `.html` file. You can save it from your browser (File → Save Page As) to share with colleagues or keep as a schema snapshot.

---

## 12. ERD

The **ERD** (Entity-Relationship Diagram) feature generates a Mermaid ER diagram for every table in a schema and opens it as a self-contained HTML page in your default web browser.

### 12.1 Generating an ERD

Right-click any **schema** in the Schema Browser tree and choose **📐 Generate ERD**. Coruscant queries the database for column definitions, primary-key markers, and foreign-key relationships, then renders the diagram immediately. A status message at the bottom of the Schema Browser confirms how many tables and relationships were found.

### 12.2 What the Diagram Shows

Each table becomes an entity box containing:

- Every column name and its PostgreSQL data type.
- A `PK` marker next to primary-key columns.

Foreign-key relationships are drawn as one-to-many connector lines between the parent and child tables (Mermaid `||--o{` notation). Each unique table-pair produces one edge regardless of how many FK columns link them.

### 12.3 Navigating the ERD

| Control | Action |
|---|---|
| **Scroll wheel** | Zoom in / out |
| **Click and drag** (background) | Pan the diagram |
| **＋ Zoom in** button | Increases zoom by 25 % |
| **－ Zoom out** button | Decreases zoom by 25 % |
| **⊙ Reset** button | Restores the original zoom level and centres the diagram |
| **⊞ Fit** button | Scales the diagram to fill the browser window |

A collapsible **▶ Mermaid source** panel at the bottom of the page shows the raw `erDiagram` definition. You can copy it into any Mermaid-compatible editor (e.g. mermaid.live) for further customisation.

### 12.4 Saving the ERD

The ERD is written to a temporary `.html` file (named `coruscant_erd_<schema>_<random>.html`) and opened in your browser. Use **File → Save Page As** in the browser to keep a permanent copy — useful as a schema snapshot or for sharing with colleagues who don't have Coruscant installed.

> **Note:** The diagram uses Mermaid.js and svg-pan-zoom loaded from a CDN (`cdn.jsdelivr.net`). An internet connection is required the first time the file is opened.

---

## 13. Query History

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

## 14. Parameterized Queries

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

## 15. EXPLAIN and Query Plans

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

## 16. Themes  

Click the **🌙** (dark) or **☀** (light) button on the right side of the toolbar to switch themes.

| Theme | Best for |
|---|---|
| Dark (default) | Low-light environments, reduced eye strain |
| Light | Printing, presentations, bright environments |

Your preference is saved automatically and restored the next time you launch Coruscant.

---

## 17. Logging

Coruscant writes a diagnostic log on every run. This is useful when
troubleshooting connection problems or unexpected behaviour.

### Log file location

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\Coruscant\logs\coruscant.log` |
| macOS | `~/Library/Logs/Coruscant/coruscant.log` |
| Linux | `~/.local/share/Coruscant/logs/coruscant.log` |

The file rotates automatically at 5 MB and up to 3 backups are kept, so
the logs never consume more than 15 MB on disk.

### What is recorded

| Level | Examples |
|---|---|
| `INFO` | App start (version, Python, Qt, OS), connect/disconnect, schema loaded, query completed, theme changed, clean shutdown |
| `WARNING` | Result set truncated by row limit, query cancelled by user |
| `ERROR` | Connection failures, query errors, schema errors |
| `DEBUG` | Full SQL text, per-statement row counts and timing, Qt internal messages |

By default only `INFO` and above are recorded. To capture everything
including full SQL text, start Coruscant with the `DEBUG` level:

**Windows:**
```bat
set CORUSCANT_LOG_LEVEL=DEBUG
python main.py
```

**macOS / Linux:**
```bash
CORUSCANT_LOG_LEVEL=DEBUG python main.py
```

### Crash reports

If Coruscant encounters an unexpected error that it cannot handle, it will:

1. Write a `CRITICAL` log entry with the full error traceback.
2. Show a branded error dialog containing the error type, message, a detailed stack traceback for immediate inspection, and the path to the full log file.

The log file is the first place to look when something goes wrong.

### Reading the log

Each line has the format:
```
2026-04-02 10:11:09.381 | INFO     | coruscant.core.database  | Connected  host=...
```

To monitor the log live while the app runs (Windows PowerShell):
```powershell
Get-Content "$env:APPDATA\Coruscant\logs\coruscant.log" -Wait -Tail 50
```

To filter for errors only:
```powershell
Select-String -Path "$env:APPDATA\Coruscant\logs\coruscant.log" -Pattern "ERROR|WARNING|CRITICAL"
```

---

## 18. Support Script Manager

See [docs/SCRIPT_MANAGER.md](SCRIPT_MANAGER.md) for full documentation.

**Opening the Script Manager:** click **📜 Scripts** in the Schema Browser panel.

**Uploading a script collection:** click **⬆ Upload Scripts ZIP** and select a  file
containing your  maintenance scripts. The engine builds a knowledge graph in
under 5 seconds for a typical collection of 100 scripts.

**Searching:** type natural language into the search box. Results update as you type.

| Query example | What it finds |
|---|---|
| `fix deadlock` | Scripts that resolve lock contention |
| `vacuum freeze` | Scripts for transaction wraparound prevention |
| `40P01` | Scripts mentioning the deadlock SQLSTATE code |
| `pg_stat_activity` | Scripts that query the activity view |
| `kill idle connections` | Scripts that terminate idle backends |

**Loading a script:** double-click any result row to load the full script content
into the active SQL editor tab.

**Formatting scripts for best results:**



The engine weights `@desc` and `@fixes` tags at 5×, filename tokens at 3×,
and SQL body text at 1×.

---

## 19. Keyboard Shortcuts Reference

| Shortcut | Action |
|---|---|
| **F5** | Execute all editor tabs sequentially |
| **Ctrl+Enter** | Execute current tab (selection or full content) |
| **Ctrl+F5** | Execute only the statement the cursor is inside |
| **Escape** | Cancel a running query |
| **Ctrl+T** | New editor tab |
| **Ctrl+W** | Close current editor tab |
| **Ctrl+Tab** | Switch to next editor tab |
| **Ctrl+Shift+Tab** | Switch to previous editor tab |
| **Ctrl+Space** | Trigger SQL autocomplete |
| **Ctrl+C** *(result grid)* | Copy selected rows as TSV |
| **Ctrl+Shift+C** *(result grid)* | Copy selected rows with column headers |


## 20. Troubleshooting

> **Before troubleshooting any issue:** check the log file first — it records
> every connection attempt, query, and error with timestamps. See [§17](#17-logging)
> for the file location and how to filter it.

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

- Check that you connected to your **application database**, not the `postgres` system database. Open Connect and verify the **Database** field.
- Click **Refresh** in the Schema Browser header.
- Confirm that your PostgreSQL user has `SELECT` privileges on `information_schema`.
- Check the log file — a successful load logs `Schema loaded  schemas=N  tables=N`. If `N=0` after connecting to the right database, a permissions issue is likely.

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

### "Password authentication failed" despite correct credentials

This can happen if the password contains special characters and was entered incorrectly:

1. Open the connection dialog and click **👁** beside the Password field to reveal what is stored.
2. Verify that the password matches what your credential manager or administrator provided — check for truncated `$` or `%` characters, extra spaces, or autocorrected characters.
3. Clear the field, retype (or paste) the password, then click **👁** to confirm it looks right before clicking **Test Connection**.

Coruscant itself does not modify passwords — characters like `$`, `@`, `%`, and spaces are passed verbatim to PostgreSQL.

---

## 21. Recovery Mode

### 21.1 What Recovery Mode Means

PostgreSQL enters **recovery mode** in two situations:

- **Crash recovery** — after an unclean shutdown the server replays WAL (Write-Ahead Log) records to bring the data files back to a consistent state. The database is unavailable for writes until replay completes.
- **Standby / hot standby** — a replica server continuously applies WAL received from a primary. The database is readable but not writable. `pg_is_in_recovery()` returns `true` in both cases.

If your production application is pointing at a server in recovery mode, write operations will fail with errors like `cannot execute INSERT in a read-only transaction` or `recovery is in progress`. Coruscant gives you the information and the controls to resolve this directly from the UI.

### 21.2 Automatic Detection on Connect

Every time you successfully connect to a database, Coruscant silently runs `pg_is_in_recovery()` in the background. If the result is `true`:

- The **status bar** immediately shows:
  > ⚠  Database is in RECOVERY MODE — click 🔴 Recovery to investigate.
- The **🔴 Recovery** toolbar button label changes to **🔴 Recovery ⚠** to draw your attention even if you are looking elsewhere in the interface.

No manual queries or extra steps are needed. Detection happens within milliseconds of the connection being established.

If the server is a normal primary (`pg_is_in_recovery()` = `false`), nothing changes — the toolbar button remains available but unobtrusive.

### 21.3 The Recovery Dialog

Click **🔴 Recovery** in the toolbar to open the Recovery Mode dialog. The dialog is available whenever you are connected, whether or not the server is in recovery mode.

The status card inside the dialog shows:

| Field | What it tells you |
|---|---|
| **In Recovery** | `YES — standby / recovery` (red) or `NO — primary` (green) |
| **WAL Replay Paused** | Whether WAL replay has been paused with `pg_wal_replay_pause()` |
| **Replication Delay** | How far behind this server is relative to the primary, measured in seconds since the last replayed transaction. Colour-coded: green (< 60 s), amber (< 5 min), red (≥ 5 min) |
| **Last WAL Received** | Log Sequence Number (LSN) of the most recently received WAL segment |
| **Last WAL Replayed** | LSN of the most recently applied WAL segment. If this lags behind "Last WAL Received", replay is behind receipt |
| **Last Txn Replayed** | Timestamp of the last transaction applied from WAL |
| **Server Started** | When the PostgreSQL postmaster process started |
| **PG Version** | Full PostgreSQL version string |

**Auto-refresh:** the status card updates automatically every 10 seconds while the dialog is open, so you can watch replication delay decrease as WAL catches up. Click **⟳ Refresh** for an immediate update at any time.

**Colour-coded header:**

- Red strip — server is in recovery mode. The **⚡ Promote to Primary** button is active.
- Green strip — server is operating as a primary. The promote button is disabled and a confirmation message is shown.

### 21.4 Promoting to Primary — One Click

Promotion converts a standby server into a writable primary. Use this when:

- The original primary has failed and you need to make the standby the new primary.
- You are performing a planned switchover.
- The server is in paused recovery mode and you want to finalise it.

**Steps:**

1. Open the Recovery dialog (**🔴 Recovery** button in the toolbar).
2. Confirm that **In Recovery** shows `YES` and that the replication delay is acceptable.
3. Click **⚡ Promote to Primary**.
4. Read the confirmation prompt carefully. It reminds you that this action is irreversible.
5. Click **Yes** to proceed.

Coruscant runs the promotion call in a background thread (the UI stays responsive). When promotion succeeds:

- A confirmation dialog appears with the result message.
- The status card refreshes automatically and the header strip changes to green, confirming the server is now a primary.

**What happens under the hood:**

Coruscant tries `SELECT pg_promote()` first. This is available on PostgreSQL 12 and later and is the recommended approach. On older versions, `pg_promote()` is not defined and Coruscant automatically falls back to `SELECT pg_wal_replay_resume()`, which resumes WAL replay if paused and also triggers promotion on older standby configurations.

### 21.5 Safety Considerations

> **Promotion is irreversible.** Once a standby is promoted it cannot be automatically re-attached to the original primary. The original primary must be rebuilt as a new standby from the promoted server.

Before clicking **⚡ Promote to Primary**, verify:

- The original primary server is **offline or fenced** (e.g. shut down, removed from the load balancer, or network-isolated). If both servers are writable simultaneously ("split brain"), data on one will be lost when you reconcile.
- Replication delay is acceptable. Any WAL not yet replayed when promotion occurs represents transactions that occurred on the primary *after* the last replayed LSN — those transactions will be lost.
- Your PostgreSQL user has the required privilege. On PostgreSQL 14+, the role must have `pg_promote` granted, or be a superuser. On older versions, superuser access is required.

If promotion fails, Coruscant shows the full error message from PostgreSQL. Common causes:

| Error | Likely cause |
|---|---|
| `permission denied to promote server` | The current user lacks the `pg_promote` privilege or superuser status |
| `server is not in standby mode` | The server is already a primary — no action needed |
| `pg_promote(): server not in recovery` | Same as above |

---

## 22. Database Doctor

The **Database Doctor** is a built-in diagnostic and repair panel that checks your PostgreSQL server for four of the most common operational problems and lets you fix them with a single click.

### 22.1 Opening the Doctor

Click the **🩺** button in the status bar footer (visible whenever a database connection is active). The dialog opens and waits for you to run a diagnosis.

Click **🔄 Run Diagnosis** to execute all four checks simultaneously in a background thread. Results appear on colour-coded severity cards:

| Colour | Severity | Meaning |
|--------|----------|---------|
| 🟢 Green border | OK | No problem detected |
| 🟡 Amber border | Warning | Issue present — monitor or address soon |
| 🔴 Red border | Critical | Immediate action recommended |

### 22.2 Health Check — Lock Contention

**What it detects:** queries that are blocked waiting for a lock held by another session, using `pg_blocking_pids()`.

**Severity rules:**
- **Warning** — one or more blocked queries detected.
- **Critical** — any blocked query has been waiting more than 60 seconds.

**Repair actions:**

| Button | Action |
|--------|--------|
| **Kill Selected Blocker** | Select a row in the lock table then click this button to call `pg_terminate_backend(pid)` on the blocking session. Requires confirmation. |

> **Tip:** killing a blocker ends its transaction and rolls it back. All queries waiting on that lock are immediately unblocked.

### 22.3 Health Check — Table Bloat

**What it detects:** tables with significant numbers of dead tuples (rows left over from `UPDATE` and `DELETE` operations that `autovacuum` has not yet reclaimed). Data is read from `pg_stat_user_tables`.

**Threshold for inclusion:** a table appears in the list if it has > 500 dead tuples or a dead-tuple ratio > 5 %.

**Severity rules:**
- **Warning** — one or more bloated tables detected.
- **Critical** — the worst table has > 30 % dead tuples, or 10 or more tables are bloated.

**Repair actions:**

| Button | Action |
|--------|--------|
| **VACUUM Selected** | Select a table row then click to run `VACUUM ANALYZE` on that table. |
| **VACUUM All** | Runs `VACUUM ANALYZE` on every table shown in the bloat list. |
| **VACUUM FULL…** | Runs `VACUUM FULL` on the selected tables only. See the warning below before using it. |

> **Warning — VACUUM FULL is not the same as VACUUM.** It takes an `ACCESS
> EXCLUSIVE` lock and rewrites each table from scratch. While it runs, every
> query against that table blocks — including `SELECT` — so the application
> will appear to hang rather than merely slow down. It also needs roughly twice
> the table's size free on disk, and cancelling it rolls the whole rewrite back.
>
> Plain `VACUUM` reclaims the same dead rows for re-use without any of that.
> Use `VACUUM FULL` only when you need to return disk space to the operating
> system, and not against a live system outside a maintenance window. It is
> selection-only by design — there is no "FULL All" button.

**Locking.** Plain `VACUUM`, `VACUUM ANALYZE` and `VACUUM FREEZE` take a
`SHARE UPDATE EXCLUSIVE` lock: they do **not** block `SELECT`, `INSERT`,
`UPDATE` or `DELETE`, but they do contend with DDL such as `ALTER TABLE`,
`CREATE INDEX` and `REINDEX` on the same table. Only `VACUUM FULL` blocks reads.

**If you do not own the table.** Only a table's owner (or a superuser) may
vacuum it. PostgreSQL does not treat this as an error — it emits a warning and
reports success — so Coruscant checks ownership against the catalog *before*
issuing the statement and tells you exactly which tables it could not touch,
rather than reporting work that did not happen. On managed PostgreSQL
(Supabase, Neon, RDS, Azure) this is the normal outcome: ask the owning role or
a superuser to vacuum those tables, or leave them to autovacuum.

### 22.4 Health Check — Connection Exhaustion

**What it detects:** how many backends are connected relative to `max_connections`, and how many are in the `idle in transaction` state (which hold locks and prevent autovacuum from running).

**Severity rules:**
- **Warning** — connections at 70 % of `max_connections`, or 2+ idle-in-transaction backends, or 1+ long-running queries (> 5 min).
- **Critical** — connections at 85 % of `max_connections`, or 5+ idle-in-transaction backends.

**Repair actions:**

| Button | Action |
|--------|--------|
| **Terminate Idle** | Terminates all backends in the `idle` state. The current session is never touched. |
| **Terminate Idle-in-Txn** | Terminates all `idle in transaction` backends — the most dangerous for connection exhaustion. |

Both buttons require a confirmation prompt.

### 22.5 Health Check — XID Wraparound

**What it detects:** the age of each database's oldest unfrozen transaction ID (`datfrozenxid`) as a percentage of the 2-billion XID limit. Approaching this limit causes PostgreSQL to shut down to protect data integrity.

**Severity rules:**
- **Warning** — any database has consumed 40 % or more of the XID space.
- **Critical** — any database has consumed 70 % or more of the XID space.

**Repair action:**

| Button | Action |
|--------|--------|
| **VACUUM FREEZE** | Runs `VACUUM FREEZE` on the currently connected database, resetting the XID age of all tables in it. |

> **Important:** `VACUUM FREEZE` operates on the currently connected database only. If the most critical database in the list is a different database, close this dialog, reconnect to that database, then reopen Database Doctor.

### 22.6 How Repairs Work

- All repairs run in a background thread — the UI remains responsive.
- Every destructive action (kill, terminate, VACUUM) shows a confirmation dialog before executing.
- After each repair completes, the diagnosis re-runs automatically so the cards reflect the updated state immediately.
- VACUUM operations temporarily switch the connection to autocommit mode (required by PostgreSQL) and restore the original setting afterward.

---

## 23. Live Database Monitor

The **Live Database Monitor** is a real-time dashboard that samples your PostgreSQL server on a timer and presents its health, throughput, and activity at a glance. Where the Database Doctor is diagnose-and-repair, the Monitor is observe-and-understand.

### 23.1 Opening the Monitor

Click the **📊 Dashboard** button in the status bar footer (visible whenever a database connection is active). The window opens and takes its first sample immediately, then refreshes automatically.

The Monitor is **non-modal** — you can leave it open and keep writing and running queries in the main window while it updates. Re-clicking the button brings the existing window to the front rather than opening a second copy.

### 23.2 Auto-refresh

By default the dashboard refreshes every **5 seconds**. Use the controls on the top bar to:

- **Pause / resume** auto-refresh with the *Auto-refresh* checkbox (the green ● live indicator dims when paused).
- **Change the interval** — choose 2s, 5s, 10s, 30s, or 60s.
- **Refresh manually** at any time with the **🔄 Refresh** button.

All sampling runs in a background thread, so refreshes never freeze the UI.

### 23.3 KPI Gauges

A strip of ten live gauges summarises the server at a glance. Several are colour-coded (green / amber / red) so problems stand out immediately:

| Gauge | Shows |
|-------|-------|
| **Database Size** | Total size of the connected database |
| **Connections** | Active backends vs `max_connections`, with idle / in-transaction counts (amber ≥ 70 %, red ≥ 85 %) |
| **Cache Hit** | Buffer-cache hit ratio (amber < 99 %, red < 90 %) |
| **Transactions/s** | Commit + rollback rate, computed between refreshes |
| **Active Queries** | Currently executing statements and the longest running duration |
| **Uptime** | Time since the server last started |
| **Row Writes/s** | Insert + update + delete tuple rate |
| **Rows Read/s** | Tuples returned per second |
| **Blocked / Locks** | Sessions blocked on a lock (red when any are blocked) |
| **Commit Ratio** | Committed vs rolled-back transactions, with the deadlock count |

### 23.4 Live Sparklines

Below the gauges, four rolling trend charts plot the recent history of **transactions/sec**, **connection count**, **cache-hit %**, and **rows-returned/sec**. Each shows the current value plus the window minimum and maximum, making spikes and trends obvious.

### 23.5 Detail Tabs

The lower area breaks the server down across ten drill-down tabs:

| Tab | Contents |
|-----|----------|
| **⚡ Activity** | Every non-idle backend right now — user, application, client, state, wait event, duration, and query text |
| **🔌 Connections** | Connection counts by state, and a breakdown by user / application / client host |
| **📊 Tables** | Largest tables with size, dead-tuple %, sequential vs index scans, and last vacuum / analyze |
| **🔍 Indexes** | Index usage counts — surfaces unused indexes that only cost write throughput |
| **💾 Cache** | Per-table buffer-cache hit ratio |
| **🗄 Databases** | Every database on the cluster with size and activity |
| **🔒 Locks** | Blocked and blocking sessions |
| **🔁 Replication** | Streaming standby status and lag (empty when there are no standbys) |
| **🐢 Top Queries** | Slowest statements by total execution time (requires the `pg_stat_statements` extension) |
| **⚙ Settings** | Key performance-related server settings (`shared_buffers`, `work_mem`, `effective_cache_size`, and more) |

Each tab degrades gracefully: if a query returns nothing, or an optional extension such as `pg_stat_statements` is not installed, the tab shows a friendly note instead of blanking.

### 23.6 How Rates Are Calculated

Per-second rates (transactions, tuple activity, interval cache-hit) are computed as the **difference between two consecutive samples** divided by the elapsed time. The very first sample after opening therefore shows "collecting…" for rate gauges until a second sample arrives. If PostgreSQL statistics are reset while the Monitor is open, that data point is skipped so the charts never show a false spike.

---

## 24. Security Guidance

### Passwords with Special Characters

Coruscant is designed to accept any password your security policy or credential manager produces — including those with `$`, `@`, `%`, `&`, `/`, spaces, and Unicode characters. This is not a minor feature; it is a correctness requirement for any tool used in professional environments.

**How it works:** when Coruscant connects to PostgreSQL, it calls the psycopg2 library using named keyword arguments:

```python
psycopg2.connect(host=..., port=..., dbname=..., user=..., password=...)
```

The password is passed as a plain Python string and reaches the PostgreSQL wire protocol without any parsing, URI construction, or shell expansion. This means there is no encoding step between what you type and what PostgreSQL receives — no URL-percent-encoding, no environment variable expansion, no shell interpretation of special characters.

**Verifying what you typed:** click the **👁** button beside the Password field at any time to reveal the password in plain text. Click it again to hide it. Use this before clicking Test Connection if you are not certain the field contains what you intended — particularly when pasting from a password manager or typing a complex password on an unfamiliar keyboard.

**IME and autocorrect protection:** the password field disables predictive text, autocorrect, and automatic capitalisation at the platform level. What you type is what gets stored and sent.

### Saved Passwords

Connection passwords are encoded (base64) before being saved to your operating system's settings store:

- **Windows:** Registry (`HKEY_CURRENT_USER\Software\Coruscant`)
- **macOS:** `~/Library/Preferences/Coruscant.plist`
- **Linux:** `~/.config/Coruscant/Coruscant.conf`

This encoding **is not encryption**. Anyone with access to the settings store can decode the passwords. On a shared or corporate machine:

- Use the most restrictive account permissions possible.
- Clear saved connections when finished: select the profile in the connection manager and click **Delete** (see [§4.5](#45-recent-connections)).
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

*Author: Marwa Trust Mutemasango*

---

## Release Notes

Release notes for this and every previous version are kept in
[`change.md`](../change.md) in the project root.
