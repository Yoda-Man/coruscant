"""
coruscant.core.vendor
~~~~~~~~~~~~~~~~~~~~~
Third-party JavaScript shipped with the application, for inlining into the HTML
diagrams Coruscant generates (Mind Map and ERD).

Why inlined rather than loaded
------------------------------
The README promises no external network calls. Both diagrams are HTML files
written to the temp directory and opened in the user's browser, and they used
to load D3, Mermaid and svg-pan-zoom from a CDN — which made that promise false.
Mermaid's URL also carried no version at all, so an ERD's behaviour changed
whenever Mermaid published, with no Coruscant release involved.

Inlining makes each file self-contained: it renders offline, still works when
moved, shared or archived, and keeps working after Coruscant exits. A reference
into the bundled files would not — a frozen onefile build unpacks them into a
temporary ``_MEI`` directory that is deleted on exit.

There is deliberately no CDN fallback. A missing bundle is a packaging defect
and raises; falling back would quietly break the offline promise instead.

The libraries, their pinned versions, sources, sha256 hashes and licences are
recorded in ``coruscant/vendor/VENDOR.json``; ``tests/test_offline.py`` checks
the files against it.

No GUI imports.
"""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

_BASE = (
    Path(sys._MEIPASS)                      # type: ignore[attr-defined]
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[2]
)

VENDOR_DIR = _BASE / "coruscant" / "vendor"
MANIFEST_PATH = VENDOR_DIR / "VENDOR.json"


class VendorAssetMissing(RuntimeError):
    """A bundled library is absent: a packaging defect, never a user error."""


@lru_cache(maxsize=1)
def manifest() -> dict[str, dict]:
    """The vendored libraries, keyed by name."""
    try:
        entries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VendorAssetMissing(f"vendor manifest not found: {MANIFEST_PATH}") from exc
    return {entry["name"]: entry for entry in entries}


@lru_cache(maxsize=None)
def inline_script(name: str) -> str:
    """
    A ``<script>`` element carrying the full source of vendored library *name*.

    Raises KeyError for a name the manifest does not list, VendorAssetMissing
    if its file is absent, and ValueError if the source could not be inlined
    safely.
    """
    entry = manifest().get(name)
    if entry is None:
        raise KeyError(f"no vendored library named {name!r}")

    path = VENDOR_DIR / entry["file"]
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise VendorAssetMissing(
            f"vendored {name} {entry['version']} not found at {path} — "
            f"the build did not include coruscant/vendor"
        ) from exc

    # Inside an inline <script>, the HTML parser ends the element at the first
    # "</script", and "<!--" followed by "<script" puts it in a state where the
    # real closing tag is swallowed. A bundle containing neither "<script" nor
    # "</script" is immune to both. None of the pinned bundles does; this stops
    # a future one from silently truncating a diagram.
    lowered = source.lower()
    if "<script" in lowered or "</script" in lowered:
        raise ValueError(f"vendored {name} contains a <script> tag and cannot be inlined as-is")

    return (
        f"<script>/* {name} {entry['version']} ({entry['licence']}), bundled with "
        f"Coruscant so this file needs no network; licence texts ship in "
        f"coruscant/vendor/licences */\n{source}\n</script>"
    )
