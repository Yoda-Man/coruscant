"""
coruscant.core.diagram_files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Writes a generated diagram page to the temp directory for the browser to open.

The schema name is part of the file name, so the files are easy to tell apart
— but it comes from the database, and PostgreSQL allows almost any character
in a quoted name, including path separators. Built straight into
``NamedTemporaryFile(prefix=...)``, a schema called ``..\\..\\x`` put the file
outside the temp directory, and one containing ``:`` made Windows fail or write
an alternate data stream. The name is reduced to a safe token first.

No GUI imports.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def file_safe(name: str, limit: int = 40) -> str:
    """
    *name* reduced to letters, digits, ``_`` and ``-`` — nothing a file system
    reads as a separator, a drive, a stream or a parent directory.
    """
    return _UNSAFE.sub("_", name).strip("_")[:limit] or "schema"


def write_temp_html(page: str, kind: str, schema: str) -> Path:
    """
    Write *page* to a new file in the temp directory and return its path.

    *kind* is a fixed tag naming the diagram (``"mm"`` or ``"erd"``); *schema*
    is untrusted and is made safe before it touches the file name.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8",
        prefix=f"coruscant_{kind}_{file_safe(schema)}_",
    ) as fh:
        fh.write(page)
        return Path(fh.name)
