"""
The offline promise, enforced.

README.md promises "No telemetry, no analytics, no external network calls from
any part of the application." For a long time that was not true: the Mind Map
loaded D3 from jsDelivr, and the ERD loaded Mermaid and svg-pan-zoom from it —
Mermaid with no version pinned at all, so an ERD's behaviour changed whenever
Mermaid published, with no Coruscant release involved.

Every other headline claim in this project is checked by a test
(tests/test_architecture.py for the layering, tests/test_docs.py for the
manual). The offline claim had none, which is how it drifted. These tests are
the rule now:

  * no source under coruscant/ loads a resource from the network;
  * the libraries the diagrams need are bundled, pinned, licensed and
    byte-for-byte what the manifest says;
  * the generated pages themselves load nothing external;
  * the frozen build actually ships the bundles.

Static and pure: no Qt, no database.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PKG = _ROOT / "coruscant"
_VENDOR = _PKG / "vendor"
_MANIFEST = _VENDOR / "VENDOR.json"

#: The libraries the diagrams depend on, at the versions verified to work.
_EXPECTED = {"d3": "7.9.0", "mermaid": "11.17.2", "svg-pan-zoom": "3.6.1"}

# A resource *load* — something a browser fetches on its own when the page
# opens — as opposed to a hyperlink a user may choose to click. <a href> is
# deliberately absent: linking to the GitHub releases page sends nothing.
# The optional backslash allows for quotes escaped inside Python strings.
_RESOURCE_LOAD = re.compile(
    r"""
      <(?:script|link|img|iframe|source|video|audio|embed|object|track)\b[^>]*?
          \b(?:src|href|data|srcset)\s*=\s*\\?["']?\s*(?:https?:)?//
    | \burl\(\s*\\?["']?\s*(?:https?:)?//
    | @import\s+(?:url\()?\s*\\?["']?\s*(?:https?:)?//
    | \b(?:fetch|import|importScripts)\(\s*\\?["'](?:https?:)?//
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _external_loads(text: str) -> list[str]:
    return [m.group(0) for m in _RESOURCE_LOAD.finditer(text)]


def _manifest() -> dict[str, dict]:
    return {e["name"]: e for e in json.loads(_MANIFEST.read_text(encoding="utf-8"))}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# The detector itself
# ---------------------------------------------------------------------------

class TestTheDetectorDetects:
    """Guards the guard: a pattern that matched nothing would make every
    test below pass vacuously."""

    @pytest.mark.parametrize("snippet", [
        # The three loads this project actually shipped, as they appeared in
        # source — the last two with the quotes escaped inside a Python string.
        '<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>',
        '"<script src=\\"https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js\\"></script>\\n"',
        '"<script src=\\"https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js\\"></script>\\n"',
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Inter">',
        '<img src="http://example.com/x.png">',
        "<script src='//cdn.example.com/lib.js'></script>",
        "body { background: url(https://example.com/bg.png); }",
        '@import url("https://fonts.example.com/a.css");',
        "fetch('https://api.example.com/telemetry')",
        "import('https://esm.sh/lib')",
    ])
    def test_matches_a_network_load(self, snippet):
        assert _external_loads(snippet), snippet

    @pytest.mark.parametrize("snippet", [
        # Hyperlinks are not loads — following one is the user's choice.
        '<a href="https://github.com/Yoda-Man/coruscant/releases">Releases</a>',
        # Inlined, local and namespace references fetch nothing.
        "<script>/* d3 7.9.0 */ var d3 = {};</script>",
        '<img src="data:image/png;base64,iVBORw0KGgo=">',
        "document.createElementNS('http://www.w3.org/2000/svg', 'g')",
        '<link rel="stylesheet" href="style.css">',
    ])
    def test_ignores_what_fetches_nothing(self, snippet):
        assert not _external_loads(snippet), snippet


# ---------------------------------------------------------------------------
# No source loads anything from the network
# ---------------------------------------------------------------------------

def _source_files() -> list[Path]:
    return sorted(p for p in _PKG.rglob("*.py") if "__pycache__" not in p.parts)


def test_there_is_source_to_scan():
    """Guards the guard: an empty scan proves nothing."""
    names = {p.name for p in _source_files()}
    assert {"mind_map_generator.py", "erd_generator.py", "schema.py"} <= names


def test_no_source_loads_a_resource_from_the_network():
    """
    The README's promise, as a rule. A diagram that needs a library must
    inline the bundled copy through coruscant.core.vendor.inline_script().
    """
    offenders = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        for hit in _external_loads(text):
            offenders.append(f"  {path.relative_to(_ROOT)}: {hit[:100]}")
    assert not offenders, (
        "external resource load in application source — bundle the library in "
        "coruscant/vendor and inline it instead:\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# The bundles: present, pinned, licensed, unmodified
# ---------------------------------------------------------------------------

class TestVendoredLibraries:

    def test_manifest_lists_exactly_the_libraries_the_diagrams_need(self):
        assert {n: e["version"] for n, e in _manifest().items()} == _EXPECTED

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_bundle_matches_its_recorded_hash(self, name):
        """
        Byte-for-byte what was fetched and verified. Catches a hand edit, a
        corrupted copy, and line-ending conversion (see .gitattributes).
        """
        entry = _manifest()[name]
        path = _VENDOR / entry["file"]
        assert path.is_file(), f"{name}: {path} missing"
        assert _sha256(path) == entry["file_sha256"], f"{name}: bundle differs from VENDOR.json"

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_licence_ships_with_the_bundle(self, name):
        entry = _manifest()[name]
        path = _VENDOR / entry["licence_file"]
        assert path.is_file(), f"{name}: licence file {path} missing"
        assert path.stat().st_size > 0
        assert _sha256(path) == entry["licence_file_sha256"]
        assert entry["licence"], f"{name}: no licence recorded"

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_version_is_pinned_exactly(self, name):
        """No ranges, no floating majors — 'mermaid' with no version is how
        the ERD came to run on a release nobody had tested."""
        entry = _manifest()[name]
        assert re.fullmatch(r"\d+\.\d+\.\d+", entry["version"]), entry["version"]
        assert f"{name}@{entry['version']}/" in entry["file_source"]
        assert f"{name}@{entry['version']}/" in entry["licence_file_source"]

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_bundle_is_safe_to_inline(self, name):
        """
        Inside an inline <script>, the parser ends the element at the first
        "</script", and "<!--" followed by "<script" makes it swallow the real
        closing tag. A bundle with neither "<script" nor "</script" is immune.
        """
        text = (_VENDOR / _manifest()[name]["file"]).read_text(encoding="utf-8").lower()
        assert "<script" not in text
        assert "</script" not in text

    def test_nothing_unlisted_is_bundled(self):
        """Every file in coruscant/vendor is accounted for by the manifest."""
        listed = {"VENDOR.json"}
        for entry in _manifest().values():
            listed |= {entry["file"], entry["licence_file"]}
        present = {p.relative_to(_VENDOR).as_posix()
                   for p in _VENDOR.rglob("*") if p.is_file()}
        assert present == listed, f"unlisted: {present - listed}; missing: {listed - present}"

    def test_git_does_not_rewrite_the_bundles(self):
        """With core.autocrlf, a Windows checkout would convert line endings,
        change the bytes and break every hash above."""
        attrs = (_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert re.search(r"^coruscant/vendor/\*\*\s+binary\s*$", attrs, re.M)


# ---------------------------------------------------------------------------
# The loader
# ---------------------------------------------------------------------------

@pytest.fixture
def vendor_module():
    from coruscant.core import vendor
    vendor.manifest.cache_clear()
    vendor.inline_script.cache_clear()
    yield vendor
    vendor.manifest.cache_clear()
    vendor.inline_script.cache_clear()


class TestInlineScript:

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_wraps_the_full_bundle_in_one_script_element(self, vendor_module, name):
        source = (_VENDOR / _manifest()[name]["file"]).read_text(encoding="utf-8")
        tag = vendor_module.inline_script(name)
        assert tag.startswith("<script>")
        assert tag.endswith("</script>")
        assert source in tag
        assert tag.lower().count("</script") == 1

    def test_names_the_version_it_inlines(self, vendor_module):
        assert "mermaid 11.17.2" in vendor_module.inline_script("mermaid")

    def test_unknown_library_is_a_key_error(self, vendor_module):
        with pytest.raises(KeyError):
            vendor_module.inline_script("jquery")

    def test_missing_bundle_fails_loudly(self, vendor_module, tmp_path, monkeypatch):
        """
        No CDN fallback. A missing bundle is a packaging defect, and quietly
        loading from the network instead would break the promise unseen.
        """
        (tmp_path / "VENDOR.json").write_text(_MANIFEST.read_text(encoding="utf-8"),
                                              encoding="utf-8")
        monkeypatch.setattr(vendor_module, "VENDOR_DIR", tmp_path)
        monkeypatch.setattr(vendor_module, "MANIFEST_PATH", tmp_path / "VENDOR.json")
        with pytest.raises(vendor_module.VendorAssetMissing):
            vendor_module.inline_script("d3")

    def test_missing_manifest_fails_loudly(self, vendor_module, tmp_path, monkeypatch):
        monkeypatch.setattr(vendor_module, "MANIFEST_PATH", tmp_path / "VENDOR.json")
        with pytest.raises(vendor_module.VendorAssetMissing):
            vendor_module.inline_script("d3")

    def test_refuses_a_bundle_containing_a_script_tag(self, vendor_module, tmp_path, monkeypatch):
        entry = {**_manifest()["d3"], "file": "d3.min.js"}
        (tmp_path / "VENDOR.json").write_text(json.dumps([entry]), encoding="utf-8")
        (tmp_path / "d3.min.js").write_text("var s = '</script><script>alert(1)';",
                                            encoding="utf-8")
        monkeypatch.setattr(vendor_module, "VENDOR_DIR", tmp_path)
        monkeypatch.setattr(vendor_module, "MANIFEST_PATH", tmp_path / "VENDOR.json")
        with pytest.raises(ValueError):
            vendor_module.inline_script("d3")


# ---------------------------------------------------------------------------
# The pages themselves load nothing
# ---------------------------------------------------------------------------

class _FakeCursor:
    """Answers generate_mind_map's two queries: row counts, then FK edges."""

    def __init__(self, results):
        self._results = list(results)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        pass

    def fetchall(self):
        return self._results.pop(0)


class _FakeConn:
    def __init__(self, *results):
        self._results = results

    def cursor(self):
        return _FakeCursor(self._results)


def _mind_map(focus=None):
    from coruscant.core.mind_map_generator import generate_mind_map
    conn = _FakeConn([("users", 120), ("orders", 40)], [("orders", "users")])
    return generate_mind_map(conn, "public", focus)


def _erd():
    from coruscant.core.erd_generator import render_erd_html
    mermaid = ('erDiagram\n    users {\n        integer id PK\n    }\n'
               '    orders {\n        integer id PK\n    }\n'
               '    users ||--o{ orders : "fk"')
    return render_erd_html("public", mermaid, 2, 1)


class TestGeneratedPagesAreSelfContained:

    @pytest.mark.parametrize("build", [_mind_map, lambda: _mind_map("orders"), _erd],
                             ids=["mind-map", "mind-map-focused", "erd"])
    def test_page_loads_nothing_from_the_network(self, build):
        assert _external_loads(build()) == []

    def test_mind_map_carries_d3(self):
        html = _mind_map()
        assert "d3 7.9.0" in html
        assert (_VENDOR / "d3.min.js").read_text(encoding="utf-8") in html

    def test_erd_carries_mermaid_and_svg_pan_zoom(self):
        html = _erd()
        for name in ("mermaid", "svg-pan-zoom"):
            assert (_VENDOR / _manifest()[name]["file"]).read_text(encoding="utf-8") in html

    @pytest.mark.parametrize("build,scripts", [(_mind_map, 2), (_erd, 3)],
                             ids=["mind-map", "erd"])
    def test_every_script_element_is_closed_exactly_once(self, build, scripts):
        """Each inlined library plus the page's own script — no element is cut
        short or swallowed by its neighbour."""
        html = build().lower()
        assert html.count("<script") == scripts
        assert html.count("</script>") == scripts

    def test_mind_map_data_still_reaches_the_page(self):
        """Splitting the template around D3 must not drop the formatted half."""
        html = _mind_map("orders")
        assert "Mind Map — orders in public" in html
        assert '"users"' in html and '"orders"' in html

    def test_a_table_name_that_looks_like_the_marker_cannot_redirect_d3(self):
        """The template is split before formatting, so data can't collide
        with the marker that places D3."""
        from coruscant.core.mind_map_generator import _D3_SENTINEL, generate_mind_map
        marker = _D3_SENTINEL.strip()
        conn = _FakeConn([(marker, 1)], [])
        html = generate_mind_map(conn, "public")
        assert html.lower().count("</script>") == 2
        assert html.index("d3 7.9.0") < html.index("<style>")


# ---------------------------------------------------------------------------
# The frozen build ships the bundles
# ---------------------------------------------------------------------------

class TestFrozenBuild:

    def test_spec_bundles_the_vendor_directory(self):
        """Without this the exe raises VendorAssetMissing on the first diagram."""
        spec = (_ROOT / "distribution" / "coruscant.spec").read_text(encoding="utf-8")
        assert "os.path.join(project_root, 'coruscant', 'vendor')" in spec
        assert "os.path.join('coruscant', 'vendor')" in spec

    def test_frozen_lookup_points_where_the_spec_puts_them(self, monkeypatch, tmp_path):
        """The spec's destination and the loader's frozen path must agree."""
        from coruscant.core import vendor
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        try:
            reloaded = importlib.reload(vendor)
            assert reloaded.VENDOR_DIR == tmp_path / "coruscant" / "vendor"
        finally:
            monkeypatch.undo()
            importlib.reload(vendor)
