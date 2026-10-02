"""
Names are data — never markup, never syntax, never a path.

Table, column and schema names come from the database, and any role that can
create a table chooses its name. In 1.1.8 both diagrams treated those names as
trusted, and every one of these was reproduced in a real browser before being
fixed:

  * Mind Map — a table named "</script><script>…</script>" ended the page's
    own script and ran the injected one (json.dumps leaves "<" alone).
  * Mind Map — hovering a node named <img src=x onerror=…> ran it: the tooltip
    was built with innerHTML.
  * Mind Map and ERD — the schema name was parsed as markup in <title>/<h2>.
  * ERD — a name containing </div><img onerror=…> ran before Mermaid did; the
    source went into a <div> and a <pre> unescaped.
  * ERD — "Order Details", a legal PostgreSQL name, was silently drawn as two
    tables, "Order" and "Details". Nothing failed; the diagram was just wrong.
  * ERD — a Mermaid failure was swallowed by `catch(e) {}`, leaving an empty
    panel indistinguishable from an empty schema.
  * Both — the schema name went raw into the temp file name, so "..\\..\\x"
    escaped the temp directory.

Static and pure: no Qt, no database.
"""
from __future__ import annotations

import ast
import html as htmllib
import json
import re
import tempfile
from pathlib import Path

import pytest

from coruscant.core.diagram_files import file_safe, write_temp_html
from coruscant.core.erd_generator import build_erd_source, mermaid_text, render_erd_html
from coruscant.core.mind_map_generator import _script_json, generate_mind_map

_ROOT = Path(__file__).resolve().parents[1]

#: Names a hostile — or merely unusual — database can contain.
HOSTILE = [
    "</script><script>window.__pwned=1</script>",
    '<img src=x onerror="window.__pwned=1">',
    '</div><img src=x onerror="window.__pwned=1"><div>',
    "Order Details",
    'say "hi"',
    "a#b;c",
    "R&D",
    "line\nbreak",
    "tab\there",
    "\u2028separator",
]


# ---------------------------------------------------------------------------
# Fakes for the Mind Map's two catalog queries
# ---------------------------------------------------------------------------

class _Cur:
    def __init__(self, results):
        self._results = list(results)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return self._results.pop(0)


class _Conn:
    def __init__(self, *results):
        self._results = results

    def cursor(self):
        return _Cur(self._results)


def _mind_map(names, schema="public", focus=None, edges=()):
    rows = [(n, i + 1) for i, n in enumerate(names)]
    return generate_mind_map(_Conn(rows, list(edges)), schema, focus)


def _script_count(page: str) -> tuple[int, int]:
    low = page.lower()
    return low.count("<script"), low.count("</script>")


# ---------------------------------------------------------------------------
# Mermaid: a name is a label, never syntax
# ---------------------------------------------------------------------------

class TestMermaidText:

    @pytest.mark.parametrize("raw,encoded", [
        ("#", "#35;"), ('"', "#quot;"), ("<", "#lt;"), (">", "#gt;"), ("&", "#amp;"),
    ])
    def test_each_special_character_gets_mermaids_own_code(self, raw, encoded):
        assert mermaid_text(f"a{raw}b") == f"a{encoded}b"

    def test_a_plain_name_is_untouched(self):
        assert mermaid_text("order_items") == "order_items"

    def test_spaces_survive(self):
        assert mermaid_text("Order Details") == "Order Details"

    def test_hash_is_encoded_so_hash_name_semicolon_cannot_become_an_entity(self):
        """Mermaid turns any "#name;" into an HTML entity: "a#b;c" rendered as
        "a&b;c" until the "#" itself was encoded."""
        assert mermaid_text("a#b;c") == "a#35;b;c"

    @pytest.mark.parametrize("name", ["line\nbreak", "cr\r\nlf", "tab\there"])
    def test_line_breaks_cannot_end_the_statement(self, name):
        out = mermaid_text(name)
        assert "\n" not in out and "\r" not in out and "\t" not in out

    @pytest.mark.parametrize("name", HOSTILE)
    def test_output_carries_nothing_mermaid_or_html_would_read(self, name):
        out = mermaid_text(name)
        for ch in '<>&"\n\r':
            assert ch not in out, (name, out)


def _entities(source: str) -> list[str]:
    """The quoted labels of every entity block, in order."""
    return re.findall(r'^    t\d+\["([^"]*)"\] \{$', source, re.M)


class TestErdSource:

    def test_order_details_is_one_table_not_two(self):
        """The reported defect: a space split one table into two."""
        source, n_tables, _ = build_erd_source(
            [("Order Details", "id", "integer", "PK")], [])
        assert n_tables == 1
        assert _entities(source) == ["Order Details"]

    @pytest.mark.parametrize("name", HOSTILE)
    def test_every_table_is_exactly_one_entity(self, name):
        rows = [(name, "id", "integer", "PK"), ("plain", "id", "integer", "PK")]
        source, n_tables, _ = build_erd_source(rows, [])
        assert len(_entities(source)) == n_tables == 2
        assert source.count("\n    }") == 2

    @pytest.mark.parametrize("name", HOSTILE)
    def test_labels_decode_to_the_exact_name(self, name):
        """What Mermaid displays — its codes decoded, as it does itself — is the
        name, give or take the line breaks a one-line label cannot hold."""
        source, _, _ = build_erd_source([(name, "id", "integer", "")], [])
        label = _entities(source)[0]
        shown = (label.replace("#35;", "#").replace("#quot;", '"').replace("#lt;", "<")
                      .replace("#gt;", ">").replace("#amp;", "&"))
        assert shown == re.sub(r"[\r\n\t]+", " ", name)

    def test_entities_are_addressed_by_generated_id(self):
        source, _, _ = build_erd_source(
            [("customers", "id", "integer", "PK"), ("orders", "id", "integer", "PK")],
            [("orders", "customers")],
        )
        assert '    t0["customers"] {' in source
        assert '    t1["orders"] {' in source
        assert '    t0 ||--o{ t1 : "fk"' in source

    def test_relationships_never_name_a_table(self):
        source, _, n_rels = build_erd_source(
            [("Order Details", "id", "integer", ""), ("a b", "id", "integer", "")],
            [("Order Details", "a b")],
        )
        assert n_rels == 1
        rel = [l for l in source.splitlines() if "||--o{" in l]
        assert rel == ['    t1 ||--o{ t0 : "fk"']

    def test_duplicate_and_dangling_relationships(self):
        rows = [("p", "id", "integer", "PK"), ("c", "id", "integer", "PK")]
        fks = [("c", "p"), ("c", "p"), ("c", "missing"), ("missing", "p")]
        _, n_tables, n_rels = build_erd_source(rows, fks)
        assert (n_tables, n_rels) == (2, 1)

    def test_no_tables(self):
        assert build_erd_source([], []) == ("erDiagram", 0, 0)

    # ── columns: Mermaid cannot quote them ──────────────────────────────

    def test_an_ordinary_column_is_drawn_as_is(self):
        source, _, _ = build_erd_source([("t", "customer_id", "integer", "PK")], [])
        assert "        integer customer_id PK" in source.splitlines()

    @pytest.mark.parametrize("col,token", [
        ("first name", "first_name"),
        ("2fa_code", "_2fa_code"),
        ("données", "donn_es"),
        ('say "hi"', "say__hi_"),
        ("a.b", "a_b"),
    ])
    def test_an_unparseable_column_keeps_its_exact_name_in_the_comment(self, col, token):
        """
        A space or leading digit is a Mermaid parse error, and its attribute
        grammar has no quoting. The drawn token is safe; the comment column,
        which accepts any text, says precisely what the column is called.
        """
        source, _, _ = build_erd_source([("t", col, "text", "")], [])
        line = next(l.strip() for l in source.splitlines() if l.startswith("        "))
        assert line == f'text {token} "{mermaid_text(col)}"'

    def test_pk_marker_precedes_the_comment(self):
        source, _, _ = build_erd_source([("t", "my id", "integer", "PK")], [])
        assert "        integer my_id PK \"my id\"" in source.splitlines()

    def test_data_types_still_reduced_to_tokens(self):
        source, _, _ = build_erd_source(
            [("t", "at", "timestamp with time zone", "")], [])
        assert "        timestamp_with_time_zone at" in source.splitlines()


# ---------------------------------------------------------------------------
# ERD page: the HTML layer
# ---------------------------------------------------------------------------

def _between(page: str, start: str, end: str) -> str:
    i = page.index(start) + len(start)
    return page[i:page.index(end, i)]


class TestErdPage:

    @pytest.mark.parametrize("schema", HOSTILE)
    def test_schema_name_is_text_in_title_and_heading(self, schema):
        page = render_erd_html(schema, "erDiagram", 0, 0)
        assert f"<title>ERD — {htmllib.escape(schema)}</title>" in page
        assert f"<h2>ERD — {htmllib.escape(schema)}</h2>" in page

    @pytest.mark.parametrize("name", HOSTILE)
    def test_hostile_names_add_no_script_element(self, name):
        source, n, r = build_erd_source([(name, "id", "integer", "")], [])
        assert _script_count(render_erd_html(name, source, n, r)) == (3, 3)

    def test_html_layer_is_safe_even_given_raw_markup(self):
        """Defence in depth: render_erd_html escapes whatever it is handed,
        not only what build_erd_source produced."""
        raw = 'erDiagram\n    x { }\n</div><script>window.__pwned=1</script>'
        page = render_erd_html("s", raw, 1, 0)
        assert _script_count(page) == (3, 3)
        assert "</div><script>" not in page

    @pytest.mark.parametrize("name", HOSTILE)
    def test_escaping_is_lossless(self, name):
        """Mermaid decodes entities in the element it reads, so the diagram —
        and the source panel — show exactly what build_erd_source produced."""
        source, n, r = build_erd_source([(name, "id", "integer", "")], [])
        page = render_erd_html("s", source, n, r)
        div = _between(page, 'style="width:100%;height:100%;">\n', "\n  </div>")
        pre = _between(page, "  <pre>", "</pre>")
        assert htmllib.unescape(div) == source
        assert htmllib.unescape(pre) == source


class TestErdFailureIsVisible:
    """A failure used to be swallowed, leaving an empty panel."""

    def _script(self):
        page = render_erd_html("s", "erDiagram", 0, 0)
        return page[page.lower().rindex("<script>"):]

    def test_no_empty_catch(self):
        assert not re.search(r"catch\s*\(\s*\w*\s*\)\s*\{\s*\}", self._script())

    def test_failure_is_logged(self):
        assert "console.error(" in self._script()

    def test_failure_is_shown_to_the_user(self):
        script = self._script()
        assert "function showError(" in script
        assert script.count("showError(") >= 3      # definition + both failure paths

    def test_a_render_that_produces_nothing_is_a_failure(self):
        assert "Mermaid finished without producing a diagram" in self._script()

    def test_mermaids_own_error_graphic_is_suppressed(self):
        assert "suppressErrorRendering: true" in self._script()

    def test_the_error_message_is_text_not_markup(self):
        """Mermaid's message can quote the offending source line, names and
        all — so it is set with textContent, never innerHTML."""
        script = self._script()
        assert "why.textContent = detail" in script
        assert ".innerHTML" not in script


# ---------------------------------------------------------------------------
# Mind Map
# ---------------------------------------------------------------------------

def _nodes(page: str) -> list[dict]:
    return json.loads(re.search(r"^const NODES = (\[.*\]);$", page, re.M).group(1))


class TestMindMapPage:

    @pytest.mark.parametrize("name", HOSTILE)
    def test_hostile_table_names_add_no_script_element(self, name):
        assert _script_count(_mind_map([name, "plain"])) == (2, 2)

    def test_json_breakout_is_inert(self):
        page = _mind_map(["</script><script>window.__pwned=1</script>"])
        assert "</script><script>window.__pwned" not in page

    @pytest.mark.parametrize("name", HOSTILE)
    def test_names_reach_the_graph_exactly(self, name):
        """Escaping is for the HTML parser only; JavaScript sees the name."""
        assert [n["id"] for n in _nodes(_mind_map([name]))] == [name]

    @pytest.mark.parametrize("schema", HOSTILE)
    def test_schema_name_is_text_in_title_and_heading(self, schema):
        page = _mind_map(["t"], schema=schema)
        expected = htmllib.escape(f"Mind Map — {schema}")
        assert f"<title>{expected}</title>" in page
        assert f"<h2>{expected}</h2>" in page

    def test_focus_table_is_text_in_the_title(self):
        page = _mind_map(["<b>x</b>", "y"], focus="<b>x</b>", edges=[("y", "<b>x</b>")])
        assert "<title>Mind Map — &lt;b&gt;x&lt;/b&gt; in public</title>" in page

    def test_tooltip_is_never_built_from_markup(self):
        """d.id is a table name; hovering a node named <img onerror=…> ran it."""
        page = _mind_map(["t"])
        script = page[page.lower().rindex("<script>"):]
        assert not re.search(r"\.innerHTML\s*=", script)
        assert "name.textContent = d.id" in script


class TestScriptJson:

    @pytest.mark.parametrize("value", HOSTILE + [["a", {"b": "</script>"}]])
    def test_round_trips_exactly(self, value):
        assert json.loads(_script_json(value)) == value

    @pytest.mark.parametrize("value", HOSTILE)
    def test_gives_the_html_parser_nothing(self, value):
        out = _script_json(value)
        assert "<" not in out and ">" not in out and "&" not in out

    def test_line_and_paragraph_separators_are_escaped(self):
        """U+2028/U+2029 end a string literal in older JavaScript engines."""
        out = _script_json("a\u2028b\u2029c")
        assert "\u2028" not in out and "\u2029" not in out


# ---------------------------------------------------------------------------
# Temp files: the schema name is not a path
# ---------------------------------------------------------------------------

class TestFileSafe:

    @pytest.mark.parametrize("name,safe", [
        ("public", "public"),
        ("sales-2026", "sales-2026"),
        ("..\\..\\Windows\\x", "Windows_x"),
        ("../../etc/passwd", "etc_passwd"),
        ("C:evil", "C_evil"),
        ("a b:c|d", "a_b_c_d"),
        ("données", "donn_es"),
        ("", "schema"),
        ("....", "schema"),
    ])
    def test_reduces_to_a_safe_token(self, name, safe):
        assert file_safe(name) == safe

    def test_long_names_are_cut(self):
        assert len(file_safe("x" * 500)) == 40


class TestWriteTempHtml:

    @pytest.mark.parametrize("schema", [
        "..\\..\\..\\escaped", "../../../escaped", "C:\\evil", "a:stream", "public",
    ])
    def test_file_lands_in_the_temp_directory(self, schema):
        path = write_temp_html("<p>x</p>", "erd", schema)
        try:
            assert path.parent.resolve() == Path(tempfile.gettempdir()).resolve()
            assert path.name.startswith("coruscant_erd_")
            assert path.suffix == ".html"
            assert path.read_text(encoding="utf-8") == "<p>x</p>"
        finally:
            path.unlink(missing_ok=True)

    def test_page_is_written_as_utf8(self):
        path = write_temp_html("Mind Map — données", "mm", "s")
        try:
            assert path.read_bytes().decode("utf-8") == "Mind Map — données"
        finally:
            path.unlink(missing_ok=True)


def test_the_panel_writes_both_diagrams_through_the_safe_writer():
    """No second, unsanitised copy of the temp-file code may come back."""
    tree = ast.parse((_ROOT / "coruscant/ui/panels/schema.py").read_text(encoding="utf-8"))
    calls = [n.func for n in ast.walk(tree) if isinstance(n, ast.Call)]
    names = [f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "") for f in calls]
    assert "NamedTemporaryFile" not in names
    assert names.count("write_temp_html") == 2
