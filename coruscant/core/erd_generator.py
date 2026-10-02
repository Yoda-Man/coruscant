"""
coruscant.core.erd_generator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Builds a Mermaid entity-relationship diagram and renders it as a
self-contained HTML page.

The Schema Browser queries the catalog; this module turns the rows into
Mermaid ``erDiagram`` source and the source into the page the browser opens.
It needs no network: Mermaid and svg-pan-zoom are inlined from the copies
bundled with Coruscant (see coruscant.core.vendor), so the diagram renders
offline and keeps working after the file is moved or Coruscant has exited.

Names are data, not syntax
--------------------------
Table and column names come from the database, and any role that can create
a table chooses its name. They pass through three languages on the way to the
screen, and each needs its own escaping:

* **Mermaid.** A bare table name is parsed as Mermaid syntax, so a perfectly
  legal PostgreSQL name like ``Order Details`` was drawn as two tables,
  ``Order`` and ``Details``, with no error. Every table now gets a generated
  id (``t0``, ``t1``, ...) and its real name as a quoted label, which Mermaid
  displays verbatim. Column names cannot be quoted in Mermaid's grammar, so
  one it cannot parse is drawn as a safe token with the exact name carried in
  the comment column.
* **HTML.** The source sits inside a ``<div>`` and a ``<pre>``; unescaped, a
  name containing ``</div><img onerror=...>`` ran script before Mermaid ever
  saw it.
* **Mermaid labels** are themselves HTML, and Mermaid reads ``#name;`` as an
  entity code — so ``#``, quotes and angle brackets are encoded with
  Mermaid's own codes (``#35;``, ``#quot;`` ...) to display literally.

Kept apart from the panel, and free of Qt and of any database access, so the
source and page can be built and checked without either.

No GUI imports.
"""

from __future__ import annotations

import html
import re

from coruscant.core.vendor import inline_script

# Characters that mean something inside a quoted Mermaid label, mapped to
# Mermaid's own entity codes. "#" is included because Mermaid turns any
# "#name;" into an HTML entity, so a literal "#" has to be encoded as well.
_MERMAID_CODES = {"#": "#35;", '"': "#quot;", "<": "#lt;", ">": "#gt;", "&": "#amp;"}

# A column name Mermaid's attribute grammar accepts as-is. Deliberately
# conservative: anything else is drawn as a token with the name in the comment.
_ATTRIBUTE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")


def mermaid_text(name: str) -> str:
    """
    *name* encoded to sit inside a quoted Mermaid label and display exactly
    as given. Line breaks and tabs become spaces — a label is one line, and a
    raw newline would end the Mermaid statement.
    """
    flat = re.sub(r"[\r\n\t]+", " ", name)
    return "".join(_MERMAID_CODES.get(ch, ch) for ch in flat)


def _type_token(data_type: str) -> str:
    """Strip / replace characters Mermaid doesn't allow in type names."""
    return (data_type.replace(" ", "_").replace("-", "_")
            .replace("(", "").replace(")", "")
            .replace(",", "").replace('"', "")
            .replace("[", "").replace("]", "")
            .replace(":", "_").replace("/", "_"))


def _attribute(col_name: str, data_type: str, is_pk: str) -> str:
    key = " PK" if is_pk else ""
    if _ATTRIBUTE_NAME.match(col_name):
        return f"{_type_token(data_type)} {col_name}{key}"
    # Mermaid's attribute grammar has no quoting: a space, a leading digit or
    # most punctuation is a parse error. Draw a safe token and carry the exact
    # name in the comment column, where any text is allowed — so the diagram
    # still says precisely what the column is called.
    token = re.sub(r"[^A-Za-z0-9_-]", "_", col_name)
    if not re.match(r"[A-Za-z_]", token):
        token = "_" + token
    return f'{_type_token(data_type)} {token}{key} "{mermaid_text(col_name)}"'


def build_erd_source(col_rows, fk_rows) -> tuple[str, int, int]:
    """
    Mermaid ``erDiagram`` source from catalog rows.

    *col_rows* are ``(table, column, data_type, is_pk)``; *fk_rows* are
    ``(child_table, parent_table)``. Returns ``(source, n_tables, n_rels)``.
    """
    tables: dict[str, list[tuple[str, str, str]]] = {}
    for table_name, col_name, data_type, is_pk in col_rows:
        tables.setdefault(table_name, []).append((col_name, data_type, is_pk))

    # Generated ids, never the name itself, so no name can be read as syntax.
    ids = {name: f"t{i}" for i, name in enumerate(sorted(tables))}

    lines = ["erDiagram"]
    for name in sorted(tables):
        lines.append(f'    {ids[name]}["{mermaid_text(name)}"] {{')
        for col_name, data_type, is_pk in tables[name]:
            lines.append("        " + _attribute(col_name, data_type, is_pk))
        lines.append("    }")

    seen: set[tuple[str, str]] = set()
    for child_table, parent_table in fk_rows:
        pair = (parent_table, child_table)
        if pair not in seen and parent_table in ids and child_table in ids:
            seen.add(pair)
            lines.append(f'    {ids[parent_table]} ||--o{{ {ids[child_table]} : "fk"')

    return "\n".join(lines), len(tables), len(seen)


def render_erd_html(schema: str, mermaid: str, n_tables: int, n_rels: int) -> str:
    """Return the ERD page for *schema*, given its Mermaid ``erDiagram`` source."""
    # The schema name and the Mermaid source both land in HTML. Mermaid reads
    # the diagram from the element's markup and decodes entities itself, so
    # escaping it here is lossless: the diagram, and the source panel, show
    # exactly the text build_erd_source() produced.
    schema_html = html.escape(schema)
    mermaid_html = html.escape(mermaid, quote=False)
    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"<title>ERD — {schema_html}</title>\n"
        f"{inline_script('mermaid')}\n"
        f"{inline_script('svg-pan-zoom')}\n"
        "<style>\n"
        "  * { box-sizing:border-box; margin:0; padding:0; }\n"
        "  body { background:#0d0d1a; color:#cdd6f4; font-family:system-ui,sans-serif;\n"
        "          padding:20px; height:100vh; display:flex; flex-direction:column; gap:10px; }\n"
        "  h2  { color:#89b4fa; font-size:17px; flex-shrink:0; }\n"
        "  .meta { color:#666; font-size:11px; flex-shrink:0; }\n"
        "  .toolbar { display:flex; gap:6px; flex-shrink:0; }\n"
        "  .toolbar button {\n"
        "    background:#1e1e2e; color:#cdd6f4; border:1px solid #313244;\n"
        "    border-radius:4px; padding:4px 14px; cursor:pointer; font-size:12px;\n"
        "  }\n"
        "  .toolbar button:hover { background:#313244; border-color:#89b4fa; }\n"
        "  #erd-wrap {\n"
        "    flex:1; background:#1a1a2e; border-radius:8px; border:1px solid #313244;\n"
        "    overflow:hidden; position:relative; min-height:0;\n"
        "  }\n"
        "  #erd-wrap svg { width:100%; height:100%; display:block; }\n"
        "  .erd-error { padding:24px; color:#f38ba8; font-size:13px; line-height:1.5; }\n"
        "  .erd-error strong { display:block; font-size:15px; margin-bottom:8px; }\n"
        "  .erd-error p { color:#cdd6f4; margin-top:10px; }\n"
        "  .erd-error pre { white-space:pre-wrap; }\n"
        "  details { flex-shrink:0; }\n"
        "  summary { cursor:pointer; color:#89b4fa; font-size:12px; padding:4px 0; }\n"
        "  pre { background:#1e1e2e; color:#cdd6f4; padding:14px; border-radius:6px;\n"
        "         font-size:11px; overflow:auto; border:1px solid #313244; margin-top:6px;\n"
        "         max-height:200px; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"<h2>ERD — {schema_html}</h2>\n"
        f"<p class=\"meta\">{n_tables} table(s) &nbsp;·&nbsp; {n_rels} relationship(s) &nbsp;·&nbsp;\n"
        "  Scroll to zoom &nbsp;·&nbsp; Drag to pan &nbsp;·&nbsp; Generated by Coruscant</p>\n"
        "<div class=\"toolbar\">\n"
        "  <button onclick=\"zoom(0.25)\">＋ Zoom in</button>\n"
        "  <button onclick=\"zoom(-0.25)\">－ Zoom out</button>\n"
        "  <button onclick=\"pz&&(pz.resetZoom(),pz.center())\">⊙ Reset</button>\n"
        "  <button onclick=\"pz&&pz.fit()\">⊞ Fit</button>\n"
        "</div>\n"
        "<div id=\"erd-wrap\">\n"
        "  <div class=\"mermaid\" style=\"width:100%;height:100%;\">\n"
        f"{mermaid_html}\n"
        "  </div>\n"
        "</div>\n"
        "<details>\n"
        "  <summary>▶ Mermaid source</summary>\n"
        f"  <pre>{mermaid_html}</pre>\n"
        "</details>\n"
        "<script>\n"
        "let pz = null;\n"
        "function zoom(delta) { if (!pz) return; pz.zoomBy(1 + delta); }\n"
        "mermaid.initialize({\n"
        "  startOnLoad: false, theme: 'dark',\n"
        # Coruscant reports failures itself, below; Mermaid's own error graphic
        # would otherwise stand in for the diagram with no explanation.
        "  suppressErrorRendering: true,\n"
        "  er: { diagramPadding: 30, layoutDirection: 'TB', minEntityWidth: 100 }\n"
        "});\n"
        # A failure used to be swallowed by `catch(e) {}`, leaving an empty
        # panel that looked like a schema with nothing in it. It now says so.
        "function showError(detail) {\n"
        "  const box = document.createElement('div');\n"
        "  box.className = 'erd-error';\n"
        "  const head = document.createElement('strong');\n"
        "  head.textContent = 'Coruscant could not draw this diagram.';\n"
        "  const why = document.createElement('pre');\n"
        "  why.textContent = detail;\n"
        "  const hint = document.createElement('p');\n"
        "  hint.textContent = 'The Mermaid source below is unchanged. Paste it into a '\n"
        "    + 'Mermaid editor to see exactly which line was rejected.';\n"
        "  box.append(head, why, hint);\n"
        "  document.getElementById('erd-wrap').replaceChildren(box);\n"
        "}\n"
        "async function init() {\n"
        "  try {\n"
        "    await mermaid.run({ querySelector: '.mermaid' });\n"
        "  } catch (e) {\n"
        "    console.error('Coruscant: Mermaid could not render this ERD', e);\n"
        "    showError(String((e && e.message) || e));\n"
        "    return;\n"
        "  }\n"
        "  const svg = document.querySelector('#erd-wrap svg');\n"
        "  if (!svg) {\n"
        "    console.error('Coruscant: Mermaid produced no diagram');\n"
        "    showError('Mermaid finished without producing a diagram.');\n"
        "    return;\n"
        "  }\n"
        "  svg.removeAttribute('width'); svg.removeAttribute('height');\n"
        "  svg.style.width = '100%'; svg.style.height = '100%';\n"
        "  pz = svgPanZoom(svg, {\n"
        "    zoomEnabled: true, controlIconsEnabled: false,\n"
        "    fit: true, center: true, minZoom: 0.05, maxZoom: 50,\n"
        "    zoomScaleSensitivity: 0.3,\n"
        "  });\n"
        "  window.addEventListener('resize', () => { if (pz) { pz.resize(); pz.fit(); pz.center(); } });\n"
        "}\n"
        "document.addEventListener('DOMContentLoaded', init);\n"
        "</script>\n"
        "</body>\n"
        "</html>"
    )
