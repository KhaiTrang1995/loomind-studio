/**
 * Graph — Three-tab view of the multi-agent network
 *
 * Tab 1 — Agent Graph   : SVG canvas + message compose panel
 * Tab 2 — Task Matrix   : Goals × task-type grid with per-cell metrics
 * Tab 3 — Fleet Stats   : Aggregate KPIs — tokens, files, lines, CLI breakdown
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useGraph, GraphNode, GraphEdge, AgentMessage } from '../hooks/useGraph.ts';
import { useStream } from '../hooks/useStream.ts';
import { GoalRecord, TaskRecord } from '../hooks/useGoals.ts';

const ENGINE = 'http://127.0.0.1:8082';

const ROLE_COLORS: Record<string, string> = {
  orchestrator: '#8b5cf6',
  research:     '#3b82f6',
  coding:       '#10b981',
  testing:      '#f59e0b',
  evaluation:   '#06b6d4',
  general:      '#64748b',
  cli_claude:   '#f97316',
  cli_grok:     '#a855f7',
  cli_codex:    '#3b82f6',
  cli_agy:      '#10b981',
};

const TASK_COLORS: Record<string, string> = {
  research: '#3b82f6',
  code:     '#10b981',
  test:     '#f59e0b',
  evaluate: '#06b6d4',
};

const TASK_STAGES = ['research', 'code', 'test', 'evaluate'];

function getRoleColor(role: string) { return ROLE_COLORS[role] ?? ROLE_COLORS.general; }
function getTaskColor(type: string) { return TASK_COLORS[type] ?? '#64748b'; }

// ── useAllGoals (fetches all session goals with tasks) ────────────────────────

function useAllGoals(intervalMs = 8000) {
  const [goals, setGoals] = useState<GoalRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const fetch_ = useCallback(async () => {
    try {
      const r = await fetch(`${ENGINE}/api/goals?limit=50`);
      if (!r.ok) return;
      const list: GoalRecord[] = await r.json();
      // hydrate tasks for each goal
      const hydrated = await Promise.all(list.map(async g => {
        try {
          const tr = await fetch(`${ENGINE}/api/goals/${g.goal_id}/tasks`);
          if (tr.ok) g.tasks = await tr.json();
        } catch { /**/ }
        return g;
      }));
      setGoals(hydrated);
    } catch { /**/ } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch_();
    const id = setInterval(fetch_, intervalMs);
    return () => clearInterval(id);
  }, [fetch_, intervalMs]);

  return { goals, loading, refresh: fetch_ };
}

// ── Aggregate stats from all goals + tasks ────────────────────────────────────

interface AggStats {
  totalGoals: number;
  completedGoals: number;
  totalTasks: number;
  completedTasks: number;
  failedTasks: number;
  tokensEstimated: number;
  linesGenerated: number;
  filesUnique: Set<string>;
  avgConfidence: number;
  totalSP: number;
  perCli: Record<string, { tasks: number; tokens: number; lines: number; conf: number[] }>;
  perType: Record<string, { done: number; tokens: number; avgConf: number[] }>;
  taskConnections: Array<{ from: string; to: string; count: number }>;
}

function computeStats(goals: GoalRecord[]): AggStats {
  const s: AggStats = {
    totalGoals: goals.length,
    completedGoals: goals.filter(g => g.status === 'completed').length,
    totalTasks: 0,
    completedTasks: 0,
    failedTasks: 0,
    tokensEstimated: 0,
    linesGenerated: 0,
    filesUnique: new Set(),
    avgConfidence: 0,
    totalSP: 0,
    perCli: {},
    perType: {},
    taskConnections: [],
  };

  const allConf: number[] = [];
  const connCounts: Record<string, Record<string, number>> = {};

  for (const g of goals) {
    const completedByType: string[] = [];
    for (const t of g.tasks) {
      s.totalTasks++;
      s.totalSP += t.story_points ?? 0;
      if (t.status === 'completed') {
        s.completedTasks++;
        completedByType.push(t.task_type);
      }
      if (t.status === 'failed') s.failedTasks++;

      const art = t.artifacts as Record<string, unknown>;
      const tok = Number(art?.tokens_estimated ?? 0);
      const lines = Number(art?.lines_generated ?? 0);
      const conf = Number(art?.confidence ?? 0);
      const cli = String(art?.cli ?? '');
      const files = (art?.files_mentioned as string[] | undefined) ?? [];

      s.tokensEstimated += tok;
      s.linesGenerated += lines;
      files.forEach(f => s.filesUnique.add(f));
      if (conf > 0) allConf.push(conf);

      // Per-CLI
      if (cli && t.status === 'completed') {
        if (!s.perCli[cli]) s.perCli[cli] = { tasks: 0, tokens: 0, lines: 0, conf: [] };
        s.perCli[cli].tasks++;
        s.perCli[cli].tokens += tok;
        s.perCli[cli].lines += lines;
        if (conf > 0) s.perCli[cli].conf.push(conf);
      }

      // Per task type
      const tt = t.task_type;
      if (!s.perType[tt]) s.perType[tt] = { done: 0, tokens: 0, avgConf: [] };
      if (t.status === 'completed') {
        s.perType[tt].done++;
        s.perType[tt].tokens += tok;
        if (conf > 0) s.perType[tt].avgConf.push(conf);
      }
    }

    // Task connections (research→code, code→test, etc.)
    for (let i = 0; i < completedByType.length - 1; i++) {
      const from = completedByType[i];
      const to = completedByType[i + 1];
      if (!connCounts[from]) connCounts[from] = {};
      connCounts[from][to] = (connCounts[from][to] ?? 0) + 1;
    }
  }

  s.avgConfidence = allConf.length > 0
    ? allConf.reduce((a, b) => a + b, 0) / allConf.length : 0;

  // Flatten connections
  for (const [from, tos] of Object.entries(connCounts)) {
    for (const [to, count] of Object.entries(tos)) {
      s.taskConnections.push({ from, to, count });
    }
  }

  return s;
}

// ── Agent Graph Canvas (unchanged) ───────────────────────────────────────────

interface NodePos { id: string; x: number; y: number; role: string; caps: string[]; unread: number }

function buildLayout(nodes: GraphNode[], w: number, h: number): NodePos[] {
  if (nodes.length === 0) return [];
  const cx = w / 2; const cy = h / 2;
  const r = Math.min(w, h) * 0.34;
  return nodes.map((n, i) => {
    const a = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
    return { id: n.id, x: cx + r * Math.cos(a), y: cy + r * Math.sin(a), role: n.role, caps: n.capabilities, unread: n.unread_count };
  });
}

function GraphCanvas({ nodes, edges, selected, onSelect }: {
  nodes: GraphNode[]; edges: GraphEdge[]; selected: string | null; onSelect: (id: string | null) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [dims, setDims] = useState({ w: 600, h: 400 });
  const [hovered, setHovered] = useState<string | null>(null);

  useEffect(() => {
    if (!svgRef.current?.parentElement) return;
    const ro = new ResizeObserver(e => setDims({ w: e[0].contentRect.width, h: e[0].contentRect.height }));
    ro.observe(svgRef.current.parentElement);
    return () => ro.disconnect();
  }, []);

  const positions = useMemo(() => buildLayout(nodes, dims.w, dims.h), [nodes, dims.w, dims.h]);
  const posMap = useMemo(() => Object.fromEntries(positions.map(p => [p.id, p])), [positions]);
  const cx = dims.w / 2; const cy = dims.h / 2;

  return (
    <svg ref={svgRef} width="100%" height="100%" viewBox={`0 0 ${dims.w} ${dims.h}`}
      style={{ display: 'block' }} onClick={() => onSelect(null)}>
      {/* Engine hub */}
      <circle cx={cx} cy={cy} r={28} fill="rgba(59,130,246,0.12)" stroke="#3b82f6" strokeWidth={1.5} />
      <text x={cx} y={cy - 4} textAnchor="middle" fontSize={10} fontWeight={700} fill="#60a5fa" fontFamily="Inter,sans-serif">ENGINE</text>
      <text x={cx} y={cy + 10} textAnchor="middle" fontSize={8} fill="#64748b" fontFamily="Inter,sans-serif">:8082</text>
      {/* Spokes */}
      {positions.map(p => (
        <line key={`spoke-${p.id}`} x1={cx} y1={cy} x2={p.x} y2={p.y}
          stroke="rgba(255,255,255,0.05)" strokeWidth={1} strokeDasharray="3 4" />
      ))}
      {/* Edges */}
      {edges.map((e, i) => {
        const src = posMap[e.source]; const tgt = posMap[e.target];
        if (!src || !tgt) return null;
        const isMsg = e.type === 'message';
        return (
          <g key={`edge-${i}`}>
            <line x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
              stroke={isMsg ? '#3b82f6' : '#64748b'} strokeWidth={isMsg ? 2 : 1}
              strokeDasharray={isMsg ? undefined : '4 3'} opacity={0.6} />
            {isMsg && e.label && (
              <text x={(src.x + tgt.x) / 2} y={(src.y + tgt.y) / 2 - 5}
                textAnchor="middle" fontSize={9} fill="#60a5fa" fontFamily="Inter,sans-serif" opacity={0.8}>
                {e.label}
              </text>
            )}
          </g>
        );
      })}
      {/* Nodes */}
      {positions.map(p => {
        const isSel = selected === p.id; const isHov = hovered === p.id;
        const color = getRoleColor(p.role);
        const nr = isSel ? 26 : isHov ? 24 : 22;
        return (
          <g key={p.id} style={{ cursor: 'pointer' }}
            onClick={ev => { ev.stopPropagation(); onSelect(p.id); }}
            onMouseEnter={() => setHovered(p.id)} onMouseLeave={() => setHovered(null)}>
            {isSel && <circle cx={p.x} cy={p.y} r={nr + 8} fill="none" stroke={color} strokeWidth={1.5} opacity={0.3} />}
            <circle cx={p.x} cy={p.y} r={nr} fill={`${color}22`} stroke={color} strokeWidth={isSel ? 2 : 1.5}
              filter={isSel ? `drop-shadow(0 0 8px ${color})` : undefined} />
            <text x={p.x} y={p.y + 1} textAnchor="middle" dominantBaseline="middle"
              fontSize={11} fontWeight={700} fill={color} fontFamily="Inter,sans-serif">
              {p.role[0].toUpperCase()}
            </text>
            <text x={p.x} y={p.y + nr + 14} textAnchor="middle" fontSize={10} fill="#94a3b8" fontFamily="Inter,sans-serif">
              {p.id.length > 14 ? p.id.slice(0, 13) + '…' : p.id}
            </text>
            {p.unread > 0 && (
              <g>
                <circle cx={p.x + nr - 4} cy={p.y - nr + 4} r={8} fill="#ef4444" />
                <text x={p.x + nr - 4} y={p.y - nr + 5} textAnchor="middle" dominantBaseline="middle"
                  fontSize={8} fontWeight={700} fill="white" fontFamily="Inter,sans-serif">
                  {p.unread > 9 ? '9+' : p.unread}
                </text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ── Message Panel ─────────────────────────────────────────────────────────────

function MessagePanel({ targetId, selfId, onSend, getMessages }: {
  targetId: string | null; selfId: string;
  onSend: (to: string, from: string, content: string) => Promise<void>;
  getMessages: (id: string, unreadOnly: boolean) => Promise<AgentMessage[]>;
}) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [content, setContent] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (!targetId) return;
    const [mine, theirs] = await Promise.all([getMessages(selfId, false), getMessages(targetId, false)]);
    const seen = new Set<string>();
    const thread = [...theirs, ...mine]
      .filter(m => {
        if (seen.has(m.msg_id)) return false;
        seen.add(m.msg_id);
        return m.from_agent === targetId || m.to_agent === targetId;
      })
      .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    setMessages(thread);
  }, [targetId, selfId, getMessages]);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!targetId || !content.trim()) return;
    setSending(true);
    try { await onSend(targetId, selfId, content.trim()); setContent(''); await load(); }
    catch { setError('Send failed'); } finally { setSending(false); }
  }

  if (!targetId) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)', gap: 8 }}>
      <span style={{ fontSize: 13 }}>Select an agent to view messages</span>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)', fontSize: 13, fontWeight: 600 }}>
        {targetId}
        <span style={{ fontWeight: 400, color: 'var(--text-muted)', fontSize: 11, marginLeft: 8 }}>messages</span>
        <button type="button" className="btn btn-ghost" style={{ float: 'right', padding: '2px 8px', fontSize: 11 }} onClick={load}>↻</button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {messages.length === 0
          ? <div style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', marginTop: 16 }}>No messages yet</div>
          : messages.map(m => {
              const mine = m.from_agent === selfId;
              return (
                <div key={m.msg_id} style={{ alignSelf: mine ? 'flex-end' : 'flex-start', maxWidth: '80%',
                  background: mine ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.04)',
                  border: `1px solid ${mine ? 'rgba(59,130,246,0.3)' : 'var(--border)'}`, borderRadius: 10, padding: '8px 12px' }}>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
                    {m.from_agent === selfId ? 'You' : m.from_agent} · {new Date(m.created_at).toLocaleTimeString()}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.5 }}>{m.content}</div>
                </div>
              );
            })}
        <div ref={endRef} />
      </div>
      <form onSubmit={handleSend} style={{ borderTop: '1px solid var(--border)', padding: '12px 16px', display: 'flex', gap: 8 }}>
        <input value={content} onChange={e => setContent(e.target.value)} placeholder={`Message ${targetId}…`}
          style={{ flex: 1, padding: '8px 12px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontFamily: 'var(--font)', fontSize: 13 }} />
        <button type="submit" className="btn btn-primary" style={{ padding: '8px 16px', fontSize: 13 }} disabled={sending || !content.trim()}>
          {sending ? '…' : 'Send'}
        </button>
      </form>
      {error && <div style={{ padding: '4px 16px 8px', fontSize: 12, color: 'var(--accent-red)' }}>{error}</div>}
    </div>
  );
}

// ── Task Matrix ───────────────────────────────────────────────────────────────

const STATUS_ICON: Record<string, string> = {
  completed: '✓', failed: '✗', claimed: '⟳', in_progress: '⟳',
  hitl_pending: '⏸', pending: '·', interrupted: '⚡',
};

const CELL_BG: Record<string, string> = {
  completed:    'rgba(16,185,129,0.10)',
  failed:       'rgba(239,68,68,0.10)',
  claimed:      'rgba(59,130,246,0.09)',
  in_progress:  'rgba(59,130,246,0.09)',
  hitl_pending: 'rgba(245,158,11,0.10)',
  pending:      'transparent',
  interrupted:  'rgba(139,92,246,0.09)',
};

const CELL_BORDER: Record<string, string> = {
  completed:    'rgba(16,185,129,0.3)',
  failed:       'rgba(239,68,68,0.3)',
  claimed:      'rgba(59,130,246,0.3)',
  in_progress:  'rgba(59,130,246,0.3)',
  hitl_pending: 'rgba(245,158,11,0.35)',
  pending:      'var(--border)',
  interrupted:  'rgba(139,92,246,0.3)',
};

function TaskCell({ task }: { task?: TaskRecord }) {
  if (!task) return (
    <td style={{ padding: '8px 10px', border: '1px solid var(--border)', background: 'transparent', textAlign: 'center' }}>
      <span style={{ color: 'var(--text-muted)', fontSize: 18 }}>·</span>
    </td>
  );

  const art = task.artifacts as Record<string, unknown>;
  const conf = art?.confidence ? Math.round(Number(art.confidence) * 100) : null;
  const tokens = art?.tokens_estimated ? Number(art.tokens_estimated) : null;
  const lines = art?.lines_generated ? Number(art.lines_generated) : null;
  const files = (art?.files_mentioned as string[] | undefined) ?? [];
  const cli = art?.cli ? String(art.cli) : task.assigned_to?.replace('cli-', '') ?? null;
  const icon = STATUS_ICON[task.status] ?? '?';
  const taskColor = getTaskColor(task.task_type);
  const bg = CELL_BG[task.status] ?? 'transparent';
  const border = CELL_BORDER[task.status] ?? 'var(--border)';

  return (
    <td style={{ padding: '8px 10px', border: `1px solid ${border}`, background: bg, verticalAlign: 'top', minWidth: 130 }}>
      {/* Status + CLI */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: task.status === 'completed' ? '#10b981' : task.status === 'failed' ? '#ef4444' : '#f59e0b' }}>
          {icon}
        </span>
        {cli && (
          <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: `${taskColor}22`, color: taskColor, fontWeight: 600 }}>
            {cli}
          </span>
        )}
      </div>
      {/* Metrics row */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {conf !== null && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ flex: 1, height: 3, background: 'rgba(255,255,255,0.07)', borderRadius: 2, overflow: 'hidden' }}>
              <div style={{ width: `${conf}%`, height: '100%', background: conf >= 80 ? '#10b981' : conf >= 60 ? '#f59e0b' : '#ef4444', transition: 'width 0.3s' }} />
            </div>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', minWidth: 28, textAlign: 'right' }}>{conf}%</span>
          </div>
        )}
        {tokens !== null && tokens > 0 && (
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>~{tokens > 999 ? (tokens / 1000).toFixed(1) + 'k' : tokens} tok</div>
        )}
        {lines !== null && lines > 0 && (
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{lines} lines</div>
        )}
        {files.length > 0 && (
          <div style={{ fontSize: 10, color: 'var(--accent-blue)', marginTop: 1 }} title={files.join('\n')}>
            {files.length} file{files.length > 1 ? 's' : ''}
          </div>
        )}
        {task.story_points > 0 && (
          <div style={{ fontSize: 10, color: 'var(--accent-purple)' }}>{task.story_points} SP</div>
        )}
      </div>
    </td>
  );
}

function TaskMatrix({ goals, loading }: { goals: GoalRecord[]; loading: boolean }) {
  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}><div className="spinner" /></div>;
  if (goals.length === 0) return (
    <div className="empty-state">
      <h3>No goals yet</h3>
      <p>Submit a goal on the Goals page to see the task matrix here.</p>
    </div>
  );

  // Collect all task_types across all goals to build dynamic columns
  const allTypes = new Set<string>();
  goals.forEach(g => g.tasks.forEach(t => allTypes.add(t.task_type)));
  const columns = TASK_STAGES.filter(s => allTypes.has(s));
  // Append any non-standard types
  allTypes.forEach(t => { if (!TASK_STAGES.includes(t)) columns.push(t); });

  return (
    <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 'calc(100vh - 280px)' }}>
      {/* Connection arrows */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        {columns.map((col, idx) => (
          <div key={col} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ padding: '3px 10px', borderRadius: 6, fontSize: 11, fontWeight: 700,
              background: `${getTaskColor(col)}18`, border: `1px solid ${getTaskColor(col)}40`,
              color: getTaskColor(col) }}>
              {col}
            </div>
            {idx < columns.length - 1 && (
              <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>→</span>
            )}
          </div>
        ))}
        <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {goals.length} goal{goals.length > 1 ? 's' : ''} · {goals.flatMap(g => g.tasks).filter(t => t.status === 'completed').length} tasks done
        </span>
      </div>

      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
        <thead>
          <tr style={{ background: 'var(--bg-secondary)' }}>
            <th style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 700,
              color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em',
              border: '1px solid var(--border)', minWidth: 200 }}>
              Goal
            </th>
            {columns.map(col => (
              <th key={col} style={{ padding: '8px 10px', textAlign: 'center', fontSize: 11,
                fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                border: '1px solid var(--border)', color: getTaskColor(col) }}>
                {col}
              </th>
            ))}
            <th style={{ padding: '8px 10px', textAlign: 'center', fontSize: 11, fontWeight: 700,
              color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em',
              border: '1px solid var(--border)' }}>
              Progress
            </th>
          </tr>
        </thead>
        <tbody>
          {goals.map(g => {
            const byType = Object.fromEntries(g.tasks.map(t => [t.task_type, t]));
            const done = g.tasks.filter(t => t.status === 'completed').length;
            const pct = g.tasks.length > 0 ? Math.round((done / g.tasks.length) * 100) : 0;
            const totalTok = g.tasks.reduce((s, t) => s + Number((t.artifacts as Record<string, unknown>)?.tokens_estimated ?? 0), 0);
            const totalLines = g.tasks.reduce((s, t) => s + Number((t.artifacts as Record<string, unknown>)?.lines_generated ?? 0), 0);
            return (
              <tr key={g.goal_id} style={{ borderBottom: '1px solid var(--border)' }}>
                {/* Goal name */}
                <td style={{ padding: '10px 12px', border: '1px solid var(--border)', verticalAlign: 'middle' }}>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', flexDirection: 'column' }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)',
                      maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={g.goal}>
                      {g.goal}
                    </div>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3,
                        background: g.status === 'completed' ? 'rgba(16,185,129,0.12)' : g.status === 'failed' ? 'rgba(239,68,68,0.10)' : 'rgba(59,130,246,0.10)',
                        color: g.status === 'completed' ? '#10b981' : g.status === 'failed' ? '#ef4444' : '#60a5fa',
                        fontWeight: 700 }}>
                        {g.status}
                      </span>
                      {totalTok > 0 && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>~{totalTok > 999 ? (totalTok / 1000).toFixed(1) + 'k' : totalTok} tok</span>}
                      {totalLines > 0 && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{totalLines} ln</span>}
                    </div>
                  </div>
                </td>
                {/* Task cells */}
                {columns.map(col => <TaskCell key={col} task={byType[col]} />)}
                {/* Progress cell */}
                <td style={{ padding: '8px 12px', border: '1px solid var(--border)', verticalAlign: 'middle', textAlign: 'center', minWidth: 80 }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: pct === 100 ? '#10b981' : 'var(--text-primary)' }}>{pct}%</div>
                  <div style={{ width: '100%', height: 4, background: 'rgba(255,255,255,0.07)', borderRadius: 2, overflow: 'hidden', marginTop: 4 }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: pct === 100 ? '#10b981' : '#3b82f6', transition: 'width 0.4s' }} />
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>{done}/{g.tasks.length}</div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Fleet Stats panel ─────────────────────────────────────────────────────────

function fmt(n: number) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k';
  return String(n);
}

function StatCard({ label, value, sub, color = 'var(--accent-blue)' }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 10, padding: '16px 20px' }}>
      <div style={{ fontSize: 22, fontWeight: 800, color }}>{value}</div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, opacity: 0.7 }}>{sub}</div>}
    </div>
  );
}

function FleetStats({ goals, loading }: { goals: GoalRecord[]; loading: boolean }) {
  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}><div className="spinner" /></div>;

  const s = computeStats(goals);
  const avgConf = s.avgConfidence > 0 ? Math.round(s.avgConfidence * 100) + '%' : '—';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      {/* Top KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12 }}>
        <StatCard label="Goals Total" value={String(s.totalGoals)} sub={`${s.completedGoals} completed`} color="#10b981" />
        <StatCard label="Tasks Completed" value={String(s.completedTasks)} sub={`of ${s.totalTasks} total`} color="#3b82f6" />
        <StatCard label="Tokens Estimated" value={fmt(s.tokensEstimated)} sub="sum of all CLI outputs" color="#8b5cf6" />
        <StatCard label="Lines Generated" value={fmt(s.linesGenerated)} sub="raw output lines" color="#f97316" />
        <StatCard label="Files Mentioned" value={String(s.filesUnique.size)} sub="unique paths in output" color="#06b6d4" />
        <StatCard label="Avg Confidence" value={avgConf} sub="across completed tasks" color="#10b981" />
        <StatCard label="Story Points" value={fmt(s.totalSP)} sub="total across all tasks" color="#a855f7" />
        <StatCard label="Tasks Failed" value={String(s.failedTasks)} color={s.failedTasks > 0 ? '#ef4444' : 'var(--text-muted)'} />
      </div>

      {/* Task connections matrix */}
      {s.taskConnections.length > 0 && (
        <div>
          <h4 style={{ margin: '0 0 12px', fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Task Connection Flow
          </h4>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            {s.taskConnections.map(c => (
              <div key={`${c.from}-${c.to}`} style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '6px 12px', borderRadius: 8,
                background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: getTaskColor(c.from) }}>{c.from}</span>
                <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>→</span>
                <span style={{ fontSize: 11, fontWeight: 700, color: getTaskColor(c.to) }}>{c.to}</span>
                <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 4, background: 'rgba(255,255,255,0.06)',
                  color: 'var(--text-muted)', fontWeight: 600 }}>
                  ×{c.count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Per-CLI breakdown */}
      {Object.keys(s.perCli).length > 0 && (
        <div>
          <h4 style={{ margin: '0 0 12px', fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Per-CLI Breakdown
          </h4>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-secondary)' }}>
                {['CLI', 'Tasks', 'Tokens', 'Lines', 'Avg Conf'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 700,
                    color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em',
                    border: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.perCli)
                .sort((a, b) => b[1].tasks - a[1].tasks)
                .map(([cli, stats]) => {
                  const avgC = stats.conf.length > 0 ? Math.round((stats.conf.reduce((a, b) => a + b, 0) / stats.conf.length) * 100) : null;
                  const cliColor = ROLE_COLORS[`cli_${cli}`] ?? '#64748b';
                  return (
                    <tr key={cli}>
                      <td style={{ padding: '8px 12px', border: '1px solid var(--border)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{ width: 8, height: 8, borderRadius: '50%', background: cliColor }} />
                          <span style={{ fontWeight: 600, color: cliColor }}>{cli}</span>
                        </div>
                      </td>
                      <td style={{ padding: '8px 12px', border: '1px solid var(--border)', color: 'var(--text-primary)', fontWeight: 600 }}>{stats.tasks}</td>
                      <td style={{ padding: '8px 12px', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>{fmt(stats.tokens)}</td>
                      <td style={{ padding: '8px 12px', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>{fmt(stats.lines)}</td>
                      <td style={{ padding: '8px 12px', border: '1px solid var(--border)' }}>
                        {avgC !== null ? (
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <div style={{ flex: 1, height: 4, background: 'rgba(255,255,255,0.07)', borderRadius: 2, overflow: 'hidden', maxWidth: 80 }}>
                              <div style={{ width: `${avgC}%`, height: '100%', background: avgC >= 80 ? '#10b981' : avgC >= 60 ? '#f59e0b' : '#ef4444' }} />
                            </div>
                            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{avgC}%</span>
                          </div>
                        ) : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}

      {/* Per task type */}
      {Object.keys(s.perType).length > 0 && (
        <div>
          <h4 style={{ margin: '0 0 12px', fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Per Task-Type Summary
          </h4>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
            {Object.entries(s.perType).map(([type, stats]) => {
              const avgC = stats.avgConf.length > 0
                ? Math.round((stats.avgConf.reduce((a, b) => a + b, 0) / stats.avgConf.length) * 100) : null;
              const color = getTaskColor(type);
              return (
                <div key={type} style={{ padding: '12px 14px', borderRadius: 8, border: `1px solid ${color}30`, background: `${color}08` }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>{type}</div>
                  <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text-primary)' }}>{stats.done}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>~{fmt(stats.tokens)} tokens</div>
                  {avgC !== null && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>avg conf {avgC}%</div>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Unique files list */}
      {s.filesUnique.size > 0 && (
        <div>
          <h4 style={{ margin: '0 0 10px', fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Files Mentioned in Output ({s.filesUnique.size})
          </h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {[...s.filesUnique].sort().slice(0, 50).map(f => (
              <code key={f} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 4,
                background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)',
                color: '#93c5fd' }}>{f}</code>
            ))}
            {s.filesUnique.size > 50 && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>+{s.filesUnique.size - 50} more</span>}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Graph page ───────────────────────────────────────────────────────────

type Tab = 'graph' | 'matrix' | 'stats';

export function Graph() {
  const { graph, loading, error, refresh, sendMessage, getMessages } = useGraph(5000);
  const { events: streamEvents } = useStream('monitor-ui');
  const { goals, loading: goalsLoading, refresh: refreshGoals } = useAllGoals(10000);
  const [selected, setSelected] = useState<string | null>(null);
  const [selfId, setSelfId] = useState('dashboard-user');
  const [tab, setTab] = useState<Tab>('graph');
  const refreshDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce stream-driven refresh — agent messages fire rapidly, batch them
  useEffect(() => {
    const last = streamEvents[0];
    if (last?.event !== 'agent_message') return;
    if (refreshDebounceRef.current) clearTimeout(refreshDebounceRef.current);
    refreshDebounceRef.current = setTimeout(() => { refresh(); }, 400);
    return () => {
      if (refreshDebounceRef.current) clearTimeout(refreshDebounceRef.current);
    };
  }, [streamEvents, refresh]);

  const totalUnread = useMemo(() => graph.nodes.reduce((s, n) => s + n.unread_count, 0), [graph.nodes]);
  const msgEdges = useMemo(() => graph.edges.filter(e => e.type === 'message'), [graph.edges]);
  const stats = useMemo(() => computeStats(goals), [goals]);

  const TAB_DEF: Array<{ key: Tab; label: string }> = [
    { key: 'graph', label: 'Agent Graph' },
    { key: 'matrix', label: 'Task Matrix' },
    { key: 'stats', label: 'Fleet Stats' },
  ];

  return (
    <div className="fade-in" style={{ height: 'calc(100vh - 40px)', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div className="page-header" style={{ flexShrink: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h2>Agent Graph</h2>
            <p>Real-time agent network, task dependency matrix, and fleet performance metrics</p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {tab === 'graph' && (
              <input id="self-agent-id" value={selfId} onChange={e => setSelfId(e.target.value)}
                placeholder="Your agent ID"
                style={{ padding: '6px 10px', fontSize: 12, background: 'rgba(0,0,0,0.3)',
                  border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
                  fontFamily: 'var(--font)', width: 160 }} />
            )}
            <button type="button" className="btn btn-ghost"
              onClick={() => { refresh(); refreshGoals(); }}>
              ↻ Refresh
            </button>
          </div>
        </div>
      </div>

      {/* KPI strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: 10, marginBottom: 14, flexShrink: 0 }}>
        <div className="kpi-card blue"><div className="kpi-label">Agents Online</div><div className="kpi-value">{graph.nodes.length}</div></div>
        <div className="kpi-card purple"><div className="kpi-label">Msg Links</div><div className="kpi-value">{msgEdges.length}</div></div>
        <div className="kpi-card green"><div className="kpi-label">Goals</div><div className="kpi-value">{stats.totalGoals}</div></div>
        <div className="kpi-card amber"><div className="kpi-label">Tasks Done</div><div className="kpi-value">{stats.completedTasks}</div></div>
        <div className="kpi-card blue" style={{ background: 'rgba(139,92,246,0.08)', borderColor: 'rgba(139,92,246,0.2)' }}>
          <div className="kpi-label">~Tokens</div><div className="kpi-value">{fmt(stats.tokensEstimated)}</div>
        </div>
        <div className="kpi-card amber"><div className="kpi-label">Unread</div><div className="kpi-value">{totalUnread}</div></div>
      </div>

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 12, flexShrink: 0,
        border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden',
        alignSelf: 'flex-start', background: 'var(--bg-secondary)' }}>
        {TAB_DEF.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            style={{ padding: '7px 18px', fontSize: 12, fontFamily: 'var(--font)', cursor: 'pointer',
              border: 'none', fontWeight: tab === t.key ? 700 : 400, transition: 'all 0.15s',
              background: tab === t.key ? 'rgba(59,130,246,0.15)' : 'transparent',
              color: tab === t.key ? 'var(--accent-blue)' : 'var(--text-muted)',
              borderRight: '1px solid var(--border)' }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab: Agent Graph */}
      {tab === 'graph' && (
        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: 'minmax(320px, 2fr) minmax(240px, 1fr)', gap: 16, minHeight: 0 }}>
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden', position: 'relative' }}>
            {loading && <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><div className="spinner" /></div>}
            {error && <div className="empty-state"><h3>Engine Offline</h3><p>{error}</p></div>}
            {!loading && !error && graph.nodes.length === 0 && (
              <div className="empty-state"><h3>No agents online</h3><p>Run <code>python apps/cli-bridge/agent_loop.py</code> or start <code>bash start.sh</code></p></div>
            )}
            {!loading && !error && graph.nodes.length > 0 && (
              <GraphCanvas nodes={graph.nodes} edges={graph.edges} selected={selected} onSelect={setSelected} />
            )}
          </div>
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
            <MessagePanel targetId={selected} selfId={selfId} onSend={sendMessage} getMessages={getMessages} />
          </div>
        </div>
      )}

      {/* Tab: Task Matrix */}
      {tab === 'matrix' && (
        <div style={{ flex: 1, background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '16px 20px', overflow: 'hidden' }}>
          <TaskMatrix goals={goals} loading={goalsLoading} />
        </div>
      )}

      {/* Tab: Fleet Stats */}
      {tab === 'stats' && (
        <div style={{ flex: 1, background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '16px 20px', overflowY: 'auto' }}>
          <FleetStats goals={goals} loading={goalsLoading} />
        </div>
      )}

      {/* Legend (graph tab only) */}
      {tab === 'graph' && (
        <div style={{ marginTop: 10, display: 'flex', gap: 14, flexWrap: 'wrap', flexShrink: 0 }}>
          {Object.entries(ROLE_COLORS).slice(0, 8).map(([role, color]) => (
            <div key={role} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: color }} />
              <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500 }}>{role}</span>
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 18, height: 2, background: '#3b82f6' }} />
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>message</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 18, height: 0, borderTop: '2px dashed #64748b' }} />
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>shared goal</span>
          </div>
        </div>
      )}
    </div>
  );
}
