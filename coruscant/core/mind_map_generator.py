"""
coruscant.core.mind_map_generator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Generates interactive D3.js force-directed mind maps for schema exploration.

Two modes
---------
Full schema view
    All tables as nodes, sized by estimated row count, coloured by FK degree
    (number of foreign-key relationships).

Focused view (focus_table supplied)
    Same graph, but the target table is highlighted in gold and the remaining
    nodes are revealed in BFS waves with a 500 ms stagger animation.

The output is a single self-contained HTML file opened in the system browser.
No external images or fonts are needed; only D3.js is loaded from jsDelivr CDN.

Author: Marwa Trust Mutemasango
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


# ── Public entry point ────────────────────────────────────────────────── #

def generate_mind_map(conn, schema: str, focus_table: str | None = None) -> str:
    """Render a mind map and return the HTML string.

    Parameters
    ----------
    conn:
        Live psycopg2 connection (read-only access).
    schema:
        PostgreSQL schema name.
    focus_table:
        If supplied, this table is highlighted and BFS-reveal animation starts
        from it.  Must be a table in *schema*.
    """
    with conn.cursor() as cur:
        # Estimated row counts from pg_class (instant — no table scan)
        cur.execute(
            """
            SELECT c.relname, GREATEST(c.reltuples, 0)::bigint AS row_est
            FROM   pg_class c
            JOIN   pg_namespace n ON n.oid = c.relnamespace
            WHERE  n.nspname = %s AND c.relkind = 'r'
            ORDER  BY c.relname
            """,
            (schema,),
        )
        row_counts: dict[str, int] = {r[0]: int(r[1]) for r in cur.fetchall()}

        # FK edges (one row per unique table pair)
        cur.execute(
            """
            SELECT
                tc.table_name  AS child_table,
                ccu.table_name AS parent_table
            FROM  information_schema.table_constraints AS tc
            JOIN  information_schema.constraint_column_usage AS ccu
                  ON  ccu.constraint_name = tc.constraint_name
                  AND ccu.table_schema    = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema    = %s
            GROUP BY tc.table_name, ccu.table_name
            """,
            (schema,),
        )
        raw_edges: list[tuple[str, str]] = [(r[0], r[1]) for r in cur.fetchall()]

    tables     = list(row_counts.keys())
    table_set  = set(tables)

    # Filter to valid, non-self edges
    edges = [
        (c, p) for c, p in raw_edges
        if c in table_set and p in table_set and c != p
    ]

    # FK degree (inbound + outbound)
    degree: dict[str, int] = {t: 0 for t in tables}
    for child, parent in edges:
        degree[child] += 1
        degree[parent] += 1

    # BFS waves for reveal animation
    bfs_waves: dict[str, int] = {}
    if focus_table and focus_table in table_set:
        _, bfs_waves = _compute_bfs(focus_table, edges, tables)

    # Serialise to JSON for the JS payload
    nodes_json = json.dumps(
        [
            {
                "id":      t,
                "rows":    row_counts[t],
                "degree":  degree[t],
                "wave":    bfs_waves.get(t, 0),
            }
            for t in tables
        ],
        separators=(",", ":"),
    )
    links_json = json.dumps(
        [{"source": c, "target": p} for c, p in edges],
        separators=(",", ":"),
    )

    title      = (
        f"Mind Map — {focus_table} in {schema}"
        if focus_table
        else f"Mind Map — {schema}"
    )
    n_tables   = len(tables)
    n_edges    = len(edges)
    focus_json = json.dumps(focus_table or "")
    has_focus  = "true" if focus_table else "false"

    html = _HTML_TEMPLATE.format(
        title=title,
        schema=schema,
        focus_table=focus_table or "(all tables)",
        n_tables=n_tables,
        n_edges=n_edges,
        nodes_json=nodes_json,
        links_json=links_json,
        focus_json=focus_json,
        has_focus=has_focus,
    )

    log.info(
        "Mind map generated  schema=%s  focus=%s  tables=%d  edges=%d",
        schema, focus_table or "—", n_tables, n_edges,
    )
    return html


# ── BFS helper ─────────────────────────────────────────────────────────── #

def _compute_bfs(
    start:      str,
    edges:      list[tuple[str, str]],
    all_tables: list[str],
) -> tuple[list[str], dict[str, int]]:
    """Return (ordered_nodes, wave_map) from BFS starting at *start*.

    Unreachable tables are assigned the next wave after the last reachable one,
    so they still appear (just last) rather than being hidden forever.
    """
    adj: dict[str, list[str]] = {t: [] for t in all_tables}
    for child, parent in edges:
        if child in adj:
            adj[child].append(parent)
        if parent in adj:
            adj[parent].append(child)

    visited: set[str]    = {start}
    queue:   list[str]   = [start]
    wave_map: dict[str, int] = {start: 0}
    wave      = 0

    while queue:
        next_q: list[str] = []
        for node in queue:
            for nb in sorted(adj.get(node, [])):
                if nb not in visited:
                    visited.add(nb)
                    next_q.append(nb)
                    wave_map[nb] = wave + 1
        queue = next_q
        wave += 1

    # Orphan tables (unreachable from focus) appear in a final wave
    orphan_wave = wave
    for t in all_tables:
        if t not in wave_map:
            wave_map[t] = orphan_wave

    order = sorted(wave_map.keys(), key=lambda t: (wave_map[t], t))
    return order, wave_map


# ── HTML / JS template ─────────────────────────────────────────────────── #

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: #0d0d1a; color: #cdd6f4;
  font-family: system-ui, sans-serif;
  height: 100vh; overflow: hidden;
  display: flex; flex-direction: column;
}}
#header {{
  flex-shrink: 0; padding: 8px 16px;
  background: #1a1a2e; border-bottom: 1px solid #313244;
  display: flex; align-items: center; gap: 16px;
}}
#header h2 {{ color: #89b4fa; font-size: 14px; white-space: nowrap; }}
#header .meta {{ color: #555; font-size: 11px; white-space: nowrap; }}
#toolbar {{ display: flex; gap: 6px; align-items: center; flex-shrink: 0; }}
#toolbar button {{
  background: #12122a; color: #cdd6f4;
  border: 1px solid #313244; border-radius: 4px;
  padding: 3px 12px; cursor: pointer; font-size: 11px;
}}
#toolbar button:hover {{ background: #313244; border-color: #89b4fa; }}
#search {{
  background: #12122a; color: #cdd6f4;
  border: 1px solid #313244; border-radius: 4px;
  padding: 3px 10px; font-size: 11px; width: 200px;
  outline: none;
}}
#search:focus {{ border-color: #89b4fa; }}
#search::placeholder {{ color: #555; }}
#map {{ flex: 1; overflow: hidden; }}
.tooltip {{
  position: absolute; pointer-events: none;
  background: #1e1e3a; color: #cdd6f4;
  border: 1px solid #4361ee; border-radius: 6px;
  padding: 8px 12px; font-size: 12px; line-height: 1.5;
  box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}}
#legend {{
  position: absolute; bottom: 12px; right: 12px;
  background: #1a1a2e; border: 1px solid #313244; border-radius: 6px;
  padding: 10px 14px; font-size: 11px; color: #888;
}}
#legend div {{ display: flex; align-items: center; gap: 8px; margin: 3px 0; }}
.leg-circle {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}
</style>
</head>
<body>
<div id="header">
  <h2>{title}</h2>
  <span class="meta">{n_tables} table(s) &nbsp;·&nbsp; {n_edges} FK relationship(s)</span>
  <div id="toolbar">
    <input id="search" type="text" placeholder="Search table…" autocomplete="off"/>
    <button onclick="zoomIn()">＋ Zoom</button>
    <button onclick="zoomOut()">－ Zoom</button>
    <button onclick="resetView()">⊙ Reset</button>
    <button onclick="fitView()">⊞ Fit</button>
  </div>
</div>
<div id="map"></div>
<div class="tooltip" id="tip" style="opacity:0;"></div>
<div id="legend">
  <div><span class="leg-circle" style="background:#2166ac"></span> Few FK connections</div>
  <div><span class="leg-circle" style="background:#d73027"></span> Many FK connections</div>
  <div style="margin-top:6px;"><span class="leg-circle" style="width:8px;height:8px;background:#888"></span> Small table &nbsp; <span class="leg-circle" style="width:18px;height:18px;background:#888"></span> Large table</div>
</div>
<script>
(function() {{
const NODES = {nodes_json};
const LINKS = {links_json};
const FOCUS = {focus_json};
const HAS_FOCUS = {has_focus};

const container = document.getElementById('map');
const W = () => container.clientWidth;
const H = () => container.clientHeight;

// ── Scales ─────────────────────────────────────────────────────────── //
const maxDeg  = d3.max(NODES, d => d.degree) || 1;
const maxRows = d3.max(NODES, d => d.rows)   || 1;

const colorScale = d3.scaleSequential(d3.interpolateRdYlBu).domain([maxDeg, 0]);
const sizeScale  = d3.scaleSqrt().domain([0, maxRows]).range([10, 38]).clamp(true);

// ── SVG ────────────────────────────────────────────────────────────── //
const svg = d3.select('#map').append('svg')
  .attr('width',  '100%')
  .attr('height', '100%');

// Arrow marker
const defs = svg.append('defs');
defs.append('marker')
  .attr('id', 'arrow').attr('viewBox', '0 -5 10 10')
  .attr('refX', 20).attr('refY', 0)
  .attr('markerWidth', 6).attr('markerHeight', 6)
  .attr('orient', 'auto')
  .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#4361ee');

const g = svg.append('g');

// Zoom behaviour
const zoom = d3.zoom()
  .scaleExtent([0.03, 12])
  .on('zoom', e => g.attr('transform', e.transform));
svg.call(zoom);

// ── Simulation ──────────────────────────────────────────────────────── //
const linkData = LINKS.map(l => Object.assign({{}}, l));
const nodeData = NODES.map(n => Object.assign({{}}, n));

const sim = d3.forceSimulation(nodeData)
  .force('link',      d3.forceLink(linkData).id(d => d.id).distance(130).strength(0.7))
  .force('charge',    d3.forceManyBody().strength(-350))
  .force('center',    d3.forceCenter(W() / 2, H() / 2))
  .force('collision', d3.forceCollide().radius(d => sizeScale(d.rows) + 8));

// ── Links ───────────────────────────────────────────────────────────── //
const link = g.append('g').attr('class', 'links')
  .selectAll('line').data(linkData).join('line')
  .attr('stroke', '#4361ee')
  .attr('stroke-opacity', HAS_FOCUS ? 0 : 0.35)
  .attr('stroke-width', 1.5)
  .attr('marker-end', 'url(#arrow)');

// ── Nodes ───────────────────────────────────────────────────────────── //
const node = g.append('g').attr('class', 'nodes')
  .selectAll('g').data(nodeData).join('g')
  .attr('class', 'node')
  .style('cursor', 'pointer')
  .call(
    d3.drag()
      .on('start', (e, d) => {{ if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
      .on('drag',  (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
      .on('end',   (e, d) => {{ if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }})
  );

const circle = node.append('circle')
  .attr('r',            d => sizeScale(d.rows))
  .attr('fill',         d => colorScale(d.degree))
  .attr('stroke',       d => d.id === FOCUS ? '#ffd700' : '#1a1a2e')
  .attr('stroke-width', d => d.id === FOCUS ? 3.5 : 1.5)
  .style('opacity', HAS_FOCUS ? 0 : 1);

const label = node.append('text')
  .text(d => d.id)
  .attr('text-anchor', 'middle')
  .attr('dy', d => sizeScale(d.rows) + 13)
  .attr('fill', '#cdd6f4')
  .attr('font-size', '10px')
  .attr('pointer-events', 'none')
  .style('opacity', HAS_FOCUS ? 0 : 1);

// ── Tick ────────────────────────────────────────────────────────────── //
sim.on('tick', () => {{
  link
    .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
    .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
  node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
}});

// ── Tooltip ─────────────────────────────────────────────────────────── //
const tip = document.getElementById('tip');
node.on('mouseover', function(event, d) {{
  tip.style.opacity = 1;
  tip.innerHTML =
    `<strong>${{d.id}}</strong><br/>` +
    `Rows (est.): ${{d.rows.toLocaleString()}}<br/>` +
    `FK connections: ${{d.degree}}`;
  tip.style.left = (event.pageX + 14) + 'px';
  tip.style.top  = (event.pageY - 32) + 'px';
}}).on('mousemove', function(event) {{
  tip.style.left = (event.pageX + 14) + 'px';
  tip.style.top  = (event.pageY - 32) + 'px';
}}).on('mouseout', () => {{ tip.style.opacity = 0; }});

// ── Highlight / search ──────────────────────────────────────────────── //
let highlighted = '';

function applyHighlight(name) {{
  highlighted = name;
  const neighbours = new Set();
  if (name) {{
    linkData.forEach(l => {{
      const s = l.source.id || l.source;
      const t = l.target.id || l.target;
      if (s === name) neighbours.add(t);
      if (t === name) neighbours.add(s);
    }});
  }}

  circle.attr('stroke', d => {{
    if (d.id === name)   return '#ffd700';
    if (d.id === FOCUS)  return '#ffd700';
    return '#1a1a2e';
  }}).attr('stroke-width', d => {{
    if (d.id === name)  return 4;
    if (d.id === FOCUS) return 3.5;
    return 1.5;
  }}).style('opacity', d => {{
    if (!name) return 1;
    return (d.id === name || neighbours.has(d.id)) ? 1 : 0.25;
  }});

  label.style('opacity', d => {{
    if (!name) return 1;
    return (d.id === name || neighbours.has(d.id)) ? 1 : 0.2;
  }});

  link.attr('stroke-opacity', l => {{
    if (!name) return 0.35;
    const s = l.source.id || l.source;
    const t = l.target.id || l.target;
    return (s === name || t === name) ? 0.8 : 0.05;
  }});

  // Pan to found node
  if (name) {{
    const nd = nodeData.find(d => d.id === name);
    if (nd && nd.x != null) {{
      svg.transition().duration(700).call(
        zoom.transform,
        d3.zoomIdentity
          .translate(W() / 2, H() / 2)
          .scale(1.8)
          .translate(-nd.x, -nd.y)
      );
    }}
  }}
}}

document.getElementById('search').addEventListener('input', e => {{
  const val = e.target.value.trim().toLowerCase();
  if (!val) {{ applyHighlight(''); return; }}
  const exact = nodeData.find(d => d.id.toLowerCase() === val);
  const prefix = nodeData.find(d => d.id.toLowerCase().startsWith(val));
  applyHighlight((exact || prefix || {{id:''}}).id);
}});

// ── BFS reveal animation ────────────────────────────────────────────── //
if (HAS_FOCUS) {{
  // Group nodes by BFS wave
  const waves = {{}};
  nodeData.forEach(d => {{
    (waves[d.wave] = waves[d.wave] || []).push(d.id);
  }});
  const maxWave = Math.max(...Object.keys(waves).map(Number));

  function revealWave(w) {{
    const ids = new Set(waves[w] || []);
    // Reveal nodes in this wave
    circle.filter(d => ids.has(d.id))
      .transition().duration(450)
      .style('opacity', 1);
    label.filter(d => ids.has(d.id))
      .transition().duration(450)
      .style('opacity', 1);
    // Reveal links where both endpoints visible
    setTimeout(() => {{
      link.transition().duration(400).attr('stroke-opacity', l => {{
        const sVis = (l.source._visible = true) || nodeData.find(n => n.id === (l.source.id||l.source))?._visible;
        return 0;  // links revealed all at once at the end
      }});
    }}, 200);
    if (w < maxWave) {{
      setTimeout(() => revealWave(w + 1), 520);
    }} else {{
      // Reveal all links after final wave
      setTimeout(() => {{
        link.transition().duration(700).attr('stroke-opacity', 0.35);
      }}, 400);
    }}
  }}

  setTimeout(() => revealWave(0), 400);
}}

// ── Toolbar controls ────────────────────────────────────────────────── //
window.zoomIn    = () => svg.transition().duration(250).call(zoom.scaleBy, 1.35);
window.zoomOut   = () => svg.transition().duration(250).call(zoom.scaleBy, 1 / 1.35);
window.resetView = () => svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
window.fitView   = () => {{
  const bounds = g.node().getBBox();
  if (!bounds.width || !bounds.height) return;
  const scale = Math.min(0.9 * W() / bounds.width, 0.9 * H() / bounds.height, 2);
  const tx = W() / 2 - scale * (bounds.x + bounds.width  / 2);
  const ty = H() / 2 - scale * (bounds.y + bounds.height / 2);
  svg.transition().duration(600).call(
    zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
  );
}};

// Auto-fit after initial layout settles
sim.on('end', () => {{ setTimeout(fitView, 200); }});

// ── Resize ──────────────────────────────────────────────────────────── //
window.addEventListener('resize', () => {{
  sim.force('center', d3.forceCenter(W() / 2, H() / 2)).alpha(0.1).restart();
}});

}})();
</script>
</body>
</html>"""
