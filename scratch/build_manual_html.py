"""
scratch/build_manual_html.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Render docs/USER_MANUAL.md -> docs/USER_MANUAL.html.

The HTML manual used to be maintained by hand and had drifted several versions
behind the Markdown.  This script makes the Markdown the single source of truth:
re-run it whenever USER_MANUAL.md changes.

    pip install markdown
    python scratch/build_manual_html.py

Screenshots are injected by section anchor (see SHOTS below) and are read from
docs/img/, captured by scratch/shoot_docs.py.
"""
from __future__ import annotations

import base64
import html
import re
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "USER_MANUAL.md"
OUT = ROOT / "docs" / "USER_MANUAL.html"
IMG = ROOT / "docs" / "img"

sys.path.insert(0, str(ROOT))
from coruscant import __version__  # noqa: E402

# Figures, keyed by the heading anchor they are inserted *after*.
#   anchor: (image file, caption)
SHOTS: dict[str, tuple[str, str]] = {
    "3-the-interface-at-a-glance": (
        "ui-overview.png",
        "The main window: schema browser and query history on the left, "
        "editor tabs top-right, results below.",
    ),
    "45-recent-connections": (
        "connection-manager.png",
        "The connection manager. Saved profiles are listed on the left; the "
        "selected profile's details are editable on the right.",
    ),
    "48-connecting-to-hosted-postgresql": (
        "supabase-preset.png",
        "The Supabase preset — paste the project reference and pick a region; "
        "host, port, database, username, and SSL mode are filled in for you.",
    ),
    "71-result-tab-types": (
        "results-tabs.png",
        "Two SELECT statements produce two independent result tabs, each with "
        "its own filter, sort, and export controls.",
    ),
    "77-viewing-a-single-cell": (
        "cell-viewer.png",
        "The Cell Content Viewer showing a JSON value, with Word Wrap enabled.",
    ),
    "95-the-schema-browser-toolbar": (
        "guide.png",
        "The built-in quick-reference guide, opened with the 📖 Guide button.",
    ),
    "96-visual-query-builder": (
        "query-builder.png",
        "Query Builder with a base table and an INNER JOIN. The foreign key was "
        "detected automatically, so the ON clause pre-filled and is flagged "
        "⚡ auto-linked.",
    ),
    "10-qa-engine": (
        "qa-engine.png",
        "A QA run scoring 88, listing missing foreign-key indexes and nullable "
        "foreign keys. Selecting a finding shows its generated fix script.",
    ),
    "21-recovery-mode": (
        "recovery-primary.png",
        "The Recovery dialog connected to a healthy primary server.",
    ),
    "22-database-doctor": (
        "database-doctor.png",
        "All four health checks reporting green on an idle database.",
    ),
    "23-live-database-monitor": (
        "live-monitor.png",
        "The Live Database Monitor under load: KPI gauges, four sparklines, and "
        "the Tables drill-down.",
    ),
}

# Blockquotes carrying an explicit danger marker get the amber treatment;
# everything else is a neutral tip.  Matching is done on the *text* of the
# quote, not its markup, because Markdown wraps the label in <p><strong>.
WARN_WORDS = ("⚠", "warning", "important", "caution",
              "irreversible", "cannot be undone")


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build() -> None:
    md_text = SRC.read_text(encoding="utf-8")

    # The Markdown carries its own hand-written contents list; the HTML gets a
    # generated sidebar instead, so drop it to avoid showing two.
    md_text = re.sub(r"^## Table of Contents\n.*?(?=^---\s*$)", "", md_text,
                     flags=re.S | re.M, count=1)

    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"],
        extension_configs={"toc": {"permalink": False}},
    )
    body = md.convert(md_text)

    # ---- inject figures -------------------------------------------------- #
    missing: list[str] = []
    for anchor, (fname, caption) in SHOTS.items():
        src = IMG / fname
        if not src.exists():
            missing.append(fname)
            continue
        fig = (
            f'<figure class="shot">'
            f'<img src="{data_uri(src)}" alt="{html.escape(caption, quote=True)}" loading="lazy">'
            f'<figcaption>{html.escape(caption)}</figcaption>'
            f"</figure>"
        )
        # Insert immediately after the closing tag of that heading.
        pat = re.compile(rf'(<h[23] id="{re.escape(anchor)}">.*?</h[23]>)', re.S)
        body, n = pat.subn(lambda m: m.group(1) + fig, body, count=1)
        if not n:
            missing.append(f"{fname} (anchor #{anchor} not found)")

    # ---- classify blockquotes -------------------------------------------- #
    def mark_quote(m: re.Match) -> str:
        inner = m.group(1)
        lead = re.sub(r"<[^>]+>", "", inner).strip()[:90].lower()
        cls = "warn" if any(w in lead for w in WARN_WORDS) else "tip"
        return f'<blockquote class="{cls}">{inner}</blockquote>'

    body = re.sub(r"<blockquote>(.*?)</blockquote>", mark_quote, body, flags=re.S)

    # ---- sidebar from the heading tree ----------------------------------- #
    nav: list[str] = []
    for m in re.finditer(r'<h([23]) id="([^"]+)">(.*?)</h\1>', body, re.S):
        lvl, anchor, text = m.group(1), m.group(2), re.sub(r"<[^>]+>", "", m.group(3))
        nav.append(f'<a class="lvl{lvl}" href="#{anchor}">{html.escape(text)}</a>')
    nav_html = "\n".join(nav)

    page = TEMPLATE.format(
        version=html.escape(__version__),
        nav=nav_html,
        body=body,
    )
    OUT.write_text(page, encoding="utf-8")

    kb = len(page.encode("utf-8")) / 1024
    print(f"wrote {OUT.relative_to(ROOT)}  ({kb:,.0f} KB, {len(nav)} nav entries, "
          f"{len(SHOTS) - len(missing)}/{len(SHOTS)} figures)")
    if missing:
        print("  MISSING:", ", ".join(missing))


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Coruscant v{version} &mdash; User Manual</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:#12121e; --surface:#181828; --surface2:#1e1e30; --card:#1b1b2b;
    --border:#2b2b40; --border2:#3a3a55;
    --text:#d7dcec; --text-dim:#8b93ad; --head:#e8ecf8;
    --accent:#4361ee; --accent-soft:#6d84f5; --gold:#c9a84c;
    --green:#81c784; --amber:#ffcb6b; --red:#e57373; --code-bg:#0d0d16;
    --sidebar-w:300px;
  }}
  html {{ scroll-behavior:smooth; }}
  body {{
    background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
    font-size:15px; line-height:1.75; display:flex;
    -webkit-font-smoothing:antialiased;
  }}

  /* ---------- sidebar ---------- */
  #sidebar {{
    width:var(--sidebar-w); min-width:var(--sidebar-w); height:100vh;
    position:sticky; top:0; background:var(--surface);
    border-right:1px solid var(--border); overflow-y:auto; flex-shrink:0;
  }}
  #sidebar::-webkit-scrollbar {{ width:9px; }}
  #sidebar::-webkit-scrollbar-thumb {{ background:#33334d; border-radius:5px; }}
  #brand {{
    padding:22px 18px 16px; border-bottom:1px solid var(--border);
    background:linear-gradient(160deg,#1d1d33,#15151f);
  }}
  #brand .name {{
    font-size:15px; font-weight:800; letter-spacing:2.5px;
    text-transform:uppercase; color:var(--gold);
  }}
  #brand .sub {{ font-size:11px; color:var(--text-dim); margin-top:3px; letter-spacing:.5px; }}
  #brand .ver {{
    display:inline-block; margin-top:9px; padding:2px 9px; border-radius:11px;
    background:rgba(67,97,238,.16); border:1px solid rgba(109,132,245,.45);
    color:var(--accent-soft); font-size:11px; font-weight:700;
  }}
  #filter {{ padding:12px 14px 6px; }}
  #filter input {{
    width:100%; padding:8px 11px; border-radius:7px; font-size:12.5px;
    background:var(--surface2); border:1px solid var(--border2); color:var(--text);
  }}
  #filter input:focus {{ outline:none; border-color:var(--accent); }}
  nav {{ padding:6px 10px 40px; }}
  nav a {{
    display:block; padding:5px 12px; border-radius:6px; color:var(--text-dim);
    text-decoration:none; font-size:13px; line-height:1.5;
    border-left:2px solid transparent;
  }}
  nav a:hover {{ background:var(--surface2); color:var(--text); }}
  nav a.lvl2 {{ font-weight:650; color:#b9c2da; margin-top:7px; }}
  nav a.lvl3 {{ padding-left:26px; font-size:12.5px; }}
  nav a.active {{
    background:rgba(67,97,238,.15); color:#fff;
    border-left-color:var(--accent);
  }}

  /* ---------- content ---------- */
  main {{ flex:1; min-width:0; padding:52px 60px 120px; max-width:1080px; }}
  h1,h2,h3,h4 {{ color:var(--head); line-height:1.3; }}
  h1 {{ font-size:34px; font-weight:800; letter-spacing:-.4px; }}
  h2 {{
    font-size:25px; font-weight:750; margin:52px 0 18px; padding-bottom:9px;
    border-bottom:1px solid var(--border2); scroll-margin-top:20px;
  }}
  h3 {{ font-size:18.5px; font-weight:700; margin:34px 0 12px; color:#cdd6f4;
        scroll-margin-top:20px; }}
  h4 {{ font-size:15.5px; margin:22px 0 8px; }}
  p {{ margin:12px 0; }}
  ul,ol {{ margin:12px 0 12px 26px; }}
  li {{ margin:5px 0; }}
  a {{ color:var(--accent-soft); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  hr {{ border:0; border-top:1px solid var(--border); margin:40px 0; }}
  strong {{ color:#eef1fa; font-weight:670; }}

  code {{
    background:var(--code-bg); border:1px solid #24243a; border-radius:4px;
    padding:1.5px 6px; font-size:13px; color:#a8d8ff;
    font-family:"Cascadia Code",Consolas,"SF Mono",Menlo,monospace;
  }}
  pre {{
    background:var(--code-bg); border:1px solid #24243a; border-left:3px solid var(--accent);
    border-radius:8px; padding:16px 18px; overflow-x:auto; margin:16px 0;
  }}
  pre code {{ background:none; border:0; padding:0; color:#cfe3ff; font-size:13px; line-height:1.6; }}

  table {{
    border-collapse:collapse; width:100%; margin:18px 0; font-size:13.5px;
    background:var(--card); border-radius:8px; overflow:hidden;
    border:1px solid var(--border2);
  }}
  th {{
    background:#25253c; color:#dbe2f5; text-align:left; font-weight:700;
    padding:10px 13px; font-size:12.5px; letter-spacing:.3px;
    border-bottom:1px solid var(--border2);
  }}
  td {{ padding:9px 13px; border-bottom:1px solid #24243a; vertical-align:top; }}
  tr:last-child td {{ border-bottom:0; }}
  tbody tr:nth-child(even) {{ background:rgba(255,255,255,.014); }}
  tbody tr:hover {{ background:rgba(67,97,238,.07); }}

  blockquote {{
    margin:18px 0; padding:13px 17px; border-radius:8px; font-size:14px;
    background:rgba(67,97,238,.08); border-left:3px solid var(--accent);
  }}
  blockquote.warn {{
    background:rgba(255,203,107,.09); border-left-color:var(--amber);
  }}
  blockquote p {{ margin:6px 0; }}
  blockquote p:first-child {{ margin-top:0; }}
  blockquote p:last-child {{ margin-bottom:0; }}

  /* ---------- figures ---------- */
  figure.shot {{ margin:26px 0 30px; }}
  figure.shot img {{
    width:100%; height:auto; display:block; border-radius:10px;
    border:1px solid var(--border2); background:#0d0d16;
    box-shadow:0 10px 34px rgba(0,0,0,.5);
    cursor:zoom-in; transition:border-color .15s;
  }}
  figure.shot img:hover {{ border-color:var(--accent); }}
  figure.shot figcaption {{
    margin-top:10px; font-size:12.5px; color:var(--text-dim);
    text-align:center; font-style:italic; line-height:1.6;
  }}

  /* lightbox */
  #lb {{
    display:none; position:fixed; inset:0; z-index:100; cursor:zoom-out;
    background:rgba(6,6,12,.93); padding:34px; text-align:center;
  }}
  #lb.on {{ display:block; }}
  #lb img {{
    max-width:100%; max-height:100%; border-radius:8px;
    border:1px solid var(--border2); box-shadow:0 18px 60px rgba(0,0,0,.75);
  }}

  #top {{
    position:fixed; right:26px; bottom:26px; width:42px; height:42px;
    border-radius:50%; background:var(--accent); color:#fff; border:0;
    font-size:19px; cursor:pointer; display:none; z-index:60;
    box-shadow:0 5px 18px rgba(0,0,0,.45);
  }}
  #top.on {{ display:block; }}

  @media print {{
    #sidebar,#top,#filter {{ display:none; }}
    body {{ background:#fff; color:#111; display:block; }}
    main {{ max-width:none; padding:0; }}
    figure.shot img {{ box-shadow:none; }}
  }}
  @media (max-width:980px) {{
    body {{ display:block; }}
    #sidebar {{ display:none; }}
    main {{ padding:28px 20px 80px; }}
  }}
</style>
</head>
<body>

<aside id="sidebar">
  <div id="brand">
    <div class="name">Coruscant</div>
    <div class="sub">PostgreSQL Multi-Query Tool</div>
    <span class="ver">v{version} &middot; User Manual</span>
  </div>
  <div id="filter"><input id="q" type="search" placeholder="Filter sections…" autocomplete="off"></div>
  <nav id="nav">
{nav}
  </nav>
</aside>

<main id="content">
{body}
</main>

<div id="lb"><img alt=""></div>
<button id="top" title="Back to top">&uarr;</button>

<script>
(function () {{
  var nav   = document.getElementById('nav');
  var links = Array.prototype.slice.call(nav.querySelectorAll('a'));

  // sidebar filter
  document.getElementById('q').addEventListener('input', function (e) {{
    var t = e.target.value.toLowerCase();
    links.forEach(function (a) {{
      a.style.display = a.textContent.toLowerCase().indexOf(t) > -1 ? '' : 'none';
    }});
  }});

  // scroll spy
  var heads = Array.prototype.slice.call(
    document.querySelectorAll('main h2[id], main h3[id]'));
  var map = {{}};
  links.forEach(function (a) {{ map[a.getAttribute('href').slice(1)] = a; }});

  function spy() {{
    var y = window.scrollY + 130, cur = null;
    for (var i = 0; i < heads.length; i++) {{
      if (heads[i].offsetTop <= y) cur = heads[i]; else break;
    }}
    links.forEach(function (a) {{ a.classList.remove('active'); }});
    if (cur && map[cur.id]) {{
      map[cur.id].classList.add('active');
      var a = map[cur.id], r = a.getBoundingClientRect();
      if (r.top < 60 || r.bottom > window.innerHeight - 40) {{
        a.scrollIntoView({{ block: 'center' }});
      }}
    }}
    document.getElementById('top').classList.toggle('on', window.scrollY > 700);
  }}
  window.addEventListener('scroll', spy, {{ passive: true }});
  spy();

  document.getElementById('top').addEventListener('click', function () {{
    window.scrollTo({{ top: 0, behavior: 'smooth' }});
  }});

  // lightbox
  var lb = document.getElementById('lb'), lbImg = lb.querySelector('img');
  document.querySelectorAll('figure.shot img').forEach(function (img) {{
    img.addEventListener('click', function () {{
      lbImg.src = img.src; lb.classList.add('on');
    }});
  }});
  lb.addEventListener('click', function () {{ lb.classList.remove('on'); }});
  document.addEventListener('keydown', function (e) {{
    if (e.key === 'Escape') lb.classList.remove('on');
  }});
}})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
