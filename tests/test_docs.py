"""
Documentation integrity tests.

These exist because a batch of real defects shipped in the docs and nothing
caught them:

  * The User Manual's table of contents omitted section 12 (ERD) entirely and
    then ran one number ahead of the body from 13 to 21, leaving 11 broken
    anchor links.  The body itself skipped 21.
  * A TOC entry's title had drifted from its heading ("Generating Scripts from
    a Table" vs "... from a Table or Schema"), breaking that anchor too.
  * The Readme lost an emoji in a bullet, rendering it as "? Guide".

All checks are plain text analysis — no network, no Markdown dependency.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MANUAL = _ROOT / "docs" / "USER_MANUAL.md"
_README = _ROOT / "Readme.md"
_DOCS = [_MANUAL, _README]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _slug(text: str) -> str:
    """
    GitHub's heading-anchor algorithm: lowercase, drop everything that is not
    word/space/hyphen, then replace EACH space with one hyphen.

    Note it does *not* collapse runs of spaces, so "EXPLAIN / EXPLAIN ANALYZE"
    becomes "explain--explain-analyze" with two hyphens.  A checker that
    collapses whitespace reports false positives on headings like that.
    """
    t = re.sub(r"[^\w\s-]", "", text.strip().lower())
    return t.replace(" ", "-")


def _headings(md: str) -> list[tuple[int, str]]:
    out = []
    for line in md.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            out.append((len(m.group(1)), m.group(2).strip()))
    return out


@pytest.mark.parametrize("path", _DOCS, ids=lambda p: p.name)
class TestInternalLinks:
    def test_every_anchor_link_resolves(self, path):
        md = _read(path)
        anchors = {_slug(text) for _lvl, text in _headings(md)}
        links = re.findall(r"\]\(#([^)]+)\)", md)
        broken = sorted({l for l in links if l not in anchors})
        assert not broken, (
            f"{path.name}: {len(broken)} internal link(s) point at no heading: {broken}"
        )

    def test_no_duplicate_heading_anchors(self, path):
        """Duplicate slugs make links ambiguous — the first wins silently."""
        slugs = [_slug(t) for _lvl, t in _headings(_read(path))]
        dupes = sorted({s for s in slugs if slugs.count(s) > 1})
        assert not dupes, f"{path.name}: duplicate heading anchors: {dupes}"


class TestManualNumbering:
    """The manual's TOC and its body must agree, and neither may skip a number."""

    @staticmethod
    def _toc_top(md: str) -> dict[int, str]:
        return {int(m.group(1)): m.group(2).strip()
                for line in md.splitlines()
                if (m := re.match(r"^(\d+)\.\s+\[([^\]]+)\]", line))}

    @staticmethod
    def _body_top(md: str) -> dict[int, str]:
        return {int(m.group(1)): m.group(2).strip()
                for line in md.splitlines()
                if (m := re.match(r"^##\s+(\d+)\.\s+(.*)", line))}

    @staticmethod
    def _toc_sub(md: str) -> dict[str, str]:
        return {m.group(1): m.group(2).strip()
                for line in md.splitlines()
                if (m := re.match(r"^\s+-\s+(\d+\.\d+)\s+\[([^\]]+)\]", line))}

    @staticmethod
    def _body_sub(md: str) -> dict[str, str]:
        return {m.group(1): m.group(2).strip()
                for line in md.splitlines()
                if (m := re.match(r"^###\s+(\d+\.\d+)\s+(.*)", line))}

    def test_toc_and_body_list_the_same_sections(self):
        md = _read(_MANUAL)
        toc, body = self._toc_top(md), self._body_top(md)
        only_toc = sorted(set(toc) - set(body))
        only_body = sorted(set(body) - set(toc))
        assert not only_toc, f"in the contents but not the body: {only_toc}"
        assert not only_body, (
            f"sections present in the body but missing from the contents: {only_body} "
            "— section 12 (ERD) was omitted this way"
        )

    def test_top_level_titles_match(self):
        md = _read(_MANUAL)
        toc, body = self._toc_top(md), self._body_top(md)
        bad = {n: (toc[n], body[n]) for n in set(toc) & set(body)
               if toc[n].lower() != body[n].lower()}
        assert not bad, f"contents/body title mismatch: {bad}"

    def test_subsection_titles_match(self):
        md = _read(_MANUAL)
        toc, body = self._toc_sub(md), self._body_sub(md)
        orphan = sorted(set(toc) - set(body))
        bad = {k: (toc[k], body[k]) for k in set(toc) & set(body)
               if toc[k].lower() != body[k].lower()}
        assert not orphan, f"contents lists subsections with no heading: {orphan}"
        assert not bad, f"subsection title mismatch: {bad}"

    def test_no_gaps_in_section_numbering(self):
        body = self._body_top(_read(_MANUAL))
        gaps = [n for n in range(1, max(body) + 1) if n not in body]
        assert not gaps, f"body skips section number(s): {gaps}"

    def test_subsections_are_sequential(self):
        """e.g. 7.1, 7.2, 7.4 means a subsection was renumbered but not its sibling."""
        subs: dict[int, list[int]] = {}
        for key in self._body_sub(_read(_MANUAL)):
            major, minor = (int(x) for x in key.split("."))
            subs.setdefault(major, []).append(minor)
        bad = {maj: sorted(mins) for maj, mins in subs.items()
               if sorted(mins) != list(range(1, len(mins) + 1))}
        assert not bad, f"non-sequential subsection numbering: {bad}"


@pytest.mark.parametrize("path", _DOCS, ids=lambda p: p.name)
def test_no_lost_emoji_placeholders(path):
    """
    A '?' immediately before a capitalised word usually means an emoji was
    dropped by an encoding round-trip.  The Readme shipped '**? Guide**' where
    it should have read '**📖 Guide**'.
    """
    md = _read(path)
    hits = []
    for m in re.finditer(r"(?<![\w?])\?(?=\s+[A-Z])", md):
        line = md[:m.start()].count("\n") + 1
        hits.append(f"line {line}: …{md[max(0, m.start() - 28):m.start() + 26]}…")
    assert not hits, (
        f"{path.name}: '?' where an emoji was probably lost:\n  " + "\n  ".join(hits)
    )


def test_manual_and_readme_report_the_current_version():
    import coruscant
    for path in _DOCS:
        m = re.search(r"\*\*Version:\*\*\s*([\d.]+)", _read(path))
        assert m, f"{path.name}: no '**Version:** X.Y.Z' line"
        assert m.group(1) == coruscant.__version__, (
            f"{path.name} documents v{m.group(1)} but the package is "
            f"v{coruscant.__version__}"
        )


def test_test_suite_reads_files_with_explicit_encoding():
    """
    Ten tests failed on Windows because a helper called Path.read_text() with no
    encoding: cp1252 cannot decode the 👁 glyph in connection.py.  Any file read
    in the suite must name its encoding.
    """
    import ast

    def kwarg(call: ast.Call, name: str) -> bool:
        return any(k.arg == name for k in call.keywords)

    def binary_mode(call: ast.Call) -> bool:
        modes = [a for a in call.args[1:2] if isinstance(a, ast.Constant)]
        modes += [k.value for k in call.keywords
                  if k.arg == "mode" and isinstance(k.value, ast.Constant)]
        return any("b" in m.value for m in modes if isinstance(m.value, str))

    offenders = []
    for py in sorted((_ROOT / "tests").glob("*.py")):
        # AST, not regex: a regex would match its own pattern literal.
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name in {"read_text", "write_text"} and not kwarg(node, "encoding"):
                offenders.append(f"{py.name}:{node.lineno}: {name}() without encoding=")
            elif name == "open" and not kwarg(node, "encoding") and not binary_mode(node):
                offenders.append(f"{py.name}:{node.lineno}: open() without encoding=")
    assert not offenders, "text read without an explicit encoding:\n  " + "\n  ".join(offenders)
