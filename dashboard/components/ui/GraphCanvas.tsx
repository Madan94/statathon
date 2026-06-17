'use client';

import { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import { domainColor, domainLegendLabel } from '@/lib/domainColors';

// ── Edge colours ──────────────────────────────────────────────────────────────
const EDGE_COLORS: Record<string, string> = {
  'owl:equivalentproperty': '#6366f1',
  'owl:objectproperty': '#14b8a6',
  'rdfs:subpropertyof': '#8b5cf6',
  'rdfs:seealso': '#94a3b8',
  intra_domain_association: '#6366f1',
  co_cluster_semantic: '#14b8a6',
  cross_domain_linkage: '#f59e0b',
  strong: '#22c55e',
  weak: '#94a3b8',
};

function edgeColor(rel?: string): string {
  if (!rel) return EDGE_COLORS.weak;
  const lower = rel.toLowerCase();
  for (const key of Object.keys(EDGE_COLORS)) {
    if (lower.includes(key)) return EDGE_COLORS[key];
  }
  return EDGE_COLORS.weak;
}

// ── Types ─────────────────────────────────────────────────────────────────────
export interface GraphNode {
  id: string;
  domain?: string;
  label?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight?: number;
  relationship_type?: string;
  semantic_reason?: string;
}

interface SimNode extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  height?: number;
}

// ── Force simulation (Fruchterman-Reingold) ───────────────────────────────────
function initPositions(nodes: GraphNode[], width: number, height: number): SimNode[] {
  return nodes.map((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length;
    const r = Math.min(width, height) * 0.35;
    return { ...n, x: width / 2 + r * Math.cos(angle), y: height / 2 + r * Math.sin(angle), vx: 0, vy: 0 };
  });
}

function runSimulation(
  simNodes: SimNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
  iterations: number
): SimNode[] {
  const nodes = simNodes.map((n) => ({ ...n }));
  const idx = new Map(nodes.map((n, i) => [n.id, i]));
  const k2 = (width * height) / Math.max(nodes.length, 1);
  const k = Math.sqrt(k2);

  for (let iter = 0; iter < iterations; iter++) {
    const temperature = k * (1 - iter / iterations) * 0.9 + k * 0.1;

    // Repulsion
    for (let i = 0; i < nodes.length; i++) {
      let fx = 0, fy = 0;
      for (let j = 0; j < nodes.length; j++) {
        if (i === j) continue;
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const rep = (k2 * 1.5) / d;
        fx += (dx / d) * rep;
        fy += (dy / d) * rep;
      }
      nodes[i].vx = fx;
      nodes[i].vy = fy;
    }

    // Attraction
    for (const e of edges) {
      const si = idx.get(e.source);
      const ti = idx.get(e.target);
      if (si == null || ti == null) continue;
      const dx = nodes[si].x - nodes[ti].x;
      const dy = nodes[si].y - nodes[ti].y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const w = e.weight ?? 0.5;
      const att = (d * d) / k * w;
      nodes[si].vx -= (dx / d) * att;
      nodes[si].vy -= (dy / d) * att;
      nodes[ti].vx += (dx / d) * att;
      nodes[ti].vy += (dy / d) * att;
    }

    // Apply with clamping
    for (const n of nodes) {
      const len = Math.sqrt(n.vx * n.vx + n.vy * n.vy) || 0.01;
      const disp = Math.min(len, temperature);
      n.x = Math.max(40, Math.min(width - 40, n.x + (n.vx / len) * disp));
      n.y = Math.max(40, Math.min(height - 40, n.y + (n.vy / len) * disp));
    }
  }
  return nodes;
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function GraphCanvas({ nodes: rawNodes, edges, height = 520 }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [dims, setDims] = useState({ w: 800, h: height });
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [hovered, setHovered] = useState<string | null>(null);
  // Pan / zoom
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const dragging = useRef<{ nodeId: string; ox: number; oy: number } | null>(null);
  const panning = useRef<{ ox: number; oy: number; px: number; py: number } | null>(null);

  // Resize observer
  useEffect(() => {
    if (!svgRef.current) return;
    const ro = new ResizeObserver((e) => {
      const { width } = e[0].contentRect;
      setDims({ w: width, h: height });
    });
    ro.observe(svgRef.current.parentElement!);
    return () => ro.disconnect();
  }, [height]);

  // Run simulation whenever nodes/edges change
  useEffect(() => {
    if (!rawNodes.length) return;
    const init = initPositions(rawNodes, dims.w, dims.h);
    const result = runSimulation(init, edges, dims.w, dims.h, 300);
    setSimNodes(result);
    setPan({ x: 0, y: 0 });
    setZoom(1);
  }, [rawNodes, edges, dims.w, dims.h]);

  const nodeMap = useMemo(() => new Map(simNodes.map((n) => [n.id, n])), [simNodes]);

  // Highlight logic
  const connectedIds = new Set<string>();
  if (hovered) {
    connectedIds.add(hovered);
    for (const e of edges) {
      if (e.source === hovered) connectedIds.add(e.target);
      if (e.target === hovered) connectedIds.add(e.source);
    }
  }

  // Mouse handlers for node drag
  const onNodeMouseDown = useCallback(
    (id: string) => (ev: React.MouseEvent) => {
      ev.stopPropagation();
      const svgPt = svgRef.current!.getBoundingClientRect();
      const nx = (ev.clientX - svgPt.left - pan.x) / zoom;
      const ny = (ev.clientY - svgPt.top - pan.y) / zoom;
      const n = nodeMap.get(id);
      if (!n) return;
      dragging.current = { nodeId: id, ox: nx - n.x, oy: ny - n.y };
    },
    [nodeMap, pan, zoom]
  );

  const onSvgMouseMove = useCallback(
    (ev: React.MouseEvent) => {
      const svgPt = svgRef.current!.getBoundingClientRect();
      if (dragging.current) {
        const nx = (ev.clientX - svgPt.left - pan.x) / zoom;
        const ny = (ev.clientY - svgPt.top - pan.y) / zoom;
        const { nodeId, ox, oy } = dragging.current;
        setSimNodes((prev) =>
          prev.map((n) =>
            n.id === nodeId ? { ...n, x: nx - ox, y: ny - oy } : n
          )
        );
      } else if (panning.current) {
        const { ox, oy, px, py } = panning.current;
        setPan({ x: px + ev.clientX - ox, y: py + ev.clientY - oy });
      }
    },
    [pan, zoom]
  );

  const onSvgMouseDown = useCallback(
    (ev: React.MouseEvent) => {
      if (ev.button === 1 || (ev.button === 0 && !dragging.current)) {
        panning.current = { ox: ev.clientX, oy: ev.clientY, px: pan.x, py: pan.y };
      }
    },
    [pan]
  );

  const onSvgMouseUp = useCallback(() => {
    dragging.current = null;
    panning.current = null;
  }, []);

  const onWheel = useCallback((ev: React.WheelEvent) => {
    ev.preventDefault();
    setZoom((z) => Math.max(0.3, Math.min(3, z - ev.deltaY * 0.001)));
  }, []);

  // Unique domains for legend
  const legendDomains = [...new Set(simNodes.map((n) => n.domain ?? 'unknown'))].slice(0, 10);

  if (!simNodes.length) {
    return (
      <div className="flex items-center justify-center text-sm text-text-muted" style={{ height }}>
        No graph data.
      </div>
    );
  }

  return (
    <div className="relative select-none rounded-xl border border-border overflow-hidden bg-[#0d1117]">
      <svg
        ref={svgRef}
        width="100%"
        height={height}
        onMouseMove={onSvgMouseMove}
        onMouseDown={onSvgMouseDown}
        onMouseUp={onSvgMouseUp}
        onMouseLeave={onSvgMouseUp}
        onWheel={onWheel}
        // eslint-disable-next-line react-hooks/refs -- cosmetic drag cursor; re-renders are driven by the drag state updates
        style={{ cursor: dragging.current ? 'grabbing' : 'grab' }}
      >
        <defs>
          <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="#374151" opacity="0.7" />
          </marker>
        </defs>
        <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
          {/* Edges */}
          {edges.map((e, i) => {
            const s = nodeMap.get(e.source);
            const t = nodeMap.get(e.target);
            if (!s || !t) return null;
            const isActive = !hovered || connectedIds.has(e.source) && connectedIds.has(e.target);
            const color = edgeColor(e.relationship_type);
            const w = e.weight ?? 0.5;
            // Curved edge
            const mx = (s.x + t.x) / 2 + (t.y - s.y) * 0.12;
            const my = (s.y + t.y) / 2 - (t.x - s.x) * 0.12;
            return (
              <g key={i} opacity={isActive ? 1 : 0.08}>
                <path
                  d={`M ${s.x} ${s.y} Q ${mx} ${my} ${t.x} ${t.y}`}
                  fill="none"
                  stroke={color}
                  strokeWidth={Math.max(0.5, w * 2.5)}
                  strokeOpacity={isActive ? 0.55 : 0.1}
                  markerEnd="url(#arrowhead)"
                />
              </g>
            );
          })}

          {/* Nodes */}
          {simNodes.map((n) => {
            const color = domainColor(n.domain);
            const isHov = hovered === n.id;
            const dimmed = hovered !== null && !connectedIds.has(n.id);
            const r = isHov ? 14 : 11;
            return (
              <g
                key={n.id}
                transform={`translate(${n.x},${n.y})`}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
                onMouseDown={onNodeMouseDown(n.id)}
                style={{ cursor: 'pointer' }}
                opacity={dimmed ? 0.25 : 1}
              >
                {/* Glow ring */}
                {isHov && (
                  <circle r={r + 5} fill={color} opacity={0.18} />
                )}
                <circle
                  r={r}
                  fill={color}
                  stroke={isHov ? '#fff' : color}
                  strokeWidth={isHov ? 2 : 0.5}
                  opacity={0.9}
                />
                <text
                  y={r + 12}
                  textAnchor="middle"
                  fontSize={isHov ? 11 : 10}
                  fill={isHov ? '#fff' : '#94a3b8'}
                  fontFamily="monospace"
                >
                  {n.id.length > 16 ? n.id.slice(0, 14) + '…' : n.id}
                </text>
              </g>
            );
          })}

          {/* Hover tooltip */}
          {hovered && (() => {
            const n = nodeMap.get(hovered);
            if (!n) return null;
            const edge = edges.filter((e) => e.source === hovered || e.target === hovered);
            return (
              <g transform={`translate(${n.x + 18},${n.y - 20})`} style={{ pointerEvents: 'none' }}>
                <rect
                  x={0} y={0}
                  width={180} height={52 + edge.length * 14}
                  rx={6} fill="#1e293b" stroke="#334155" strokeWidth={1}
                />
                <text x={8} y={17} fontSize={11} fill="#e2e8f0" fontWeight="600" fontFamily="monospace">{hovered}</text>
                <text x={8} y={30} fontSize={10} fill="#64748b" fontFamily="sans-serif">
                  domain: {n.domain ?? 'unknown'}
                </text>
                {edge.slice(0, 3).map((e, i) => (
                  <text key={i} x={8} y={44 + i * 14} fontSize={9} fill="#64748b" fontFamily="monospace">
                    {e.source === hovered ? '→' : '←'} {e.source === hovered ? e.target : e.source}
                    {' '}({(e.weight ?? 0).toFixed(2)})
                  </text>
                ))}
              </g>
            );
          })()}
        </g>
      </svg>

      {/* Legend */}
      <div className="absolute bottom-3 left-3 flex flex-wrap gap-2 max-w-[60%]">
        {legendDomains.map((d) => (
          <div key={d} className="flex items-center gap-1 bg-black/60 rounded-full px-2 py-0.5">
            <div
              className="w-2.5 h-2.5 rounded-full shrink-0"
              style={{ backgroundColor: domainColor(d) }}
            />
            <span className="text-[10px] text-slate-300 font-mono">{domainLegendLabel(d)}</span>
          </div>
        ))}
      </div>

      {/* Controls hint */}
      <div className="absolute top-3 right-3 text-[10px] text-slate-500 bg-black/50 rounded px-2 py-1">
        scroll to zoom · drag to pan · hover for details
      </div>
    </div>
  );
}
