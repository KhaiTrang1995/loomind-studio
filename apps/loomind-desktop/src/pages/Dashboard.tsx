/**
 * Dashboard Page — Agent Factory style pipeline dashboard for Loomind Studio.
 *
 * Layout (top → bottom):
 *   1. Header strip  — title, engine status pill, version, refresh
 *   2. Metrics strip — 5 live KPI chips
 *   3. Pipeline map  — 4 stage cards (Research → Code → Test → Evaluate)
 *   4. Bottom grid   — Active Goals (60%) | Activity Feed (40%)
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import type { CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';
import { useEngine } from '../hooks/useEngine.ts';
import { useFleet, CLI_META } from '../hooks/useFleet.ts';
import type { CLIType, CLIStatus } from '../hooks/useFleet.ts';
import type { GoalRecord, TaskRecord } from '../hooks/useGoals.ts';

// ── Constants ─────────────────────────────────────────────────────────────────

const ENGINE = 'http://127.0.0.1:8082';
const NEXUS_API = 'http://127.0.0.1:8000';
const GOALS_POLL_MS = 8000;

type StageKey = 'research' | 'code' | 'test' | 'evaluate';

const STAGE_ORDER: StageKey[] = ['research', 'code', 'test', 'evaluate'];

const STAGE_META: Record<
  StageKey,
  { label: string; primaryAgent: CLIType }
> = {
  research: { label: 'Research',  primaryAgent: 'grok'   },
  code:     { label: 'Code',      primaryAgent: 'claude' },
  test:     { label: 'Test',      primaryAgent: 'agy'    },
  evaluate: { label: 'Evaluate',  primaryAgent: 'agy'    },
};

const CLI_COLOR: Record<CLIType, string> = {
  claude: '#f97316',
  grok:   '#a855f7',
  agy:    '#10b981',
  codex:  '#3b82f6',
};

// ── Parameterised style functions ─────────────────────────────────────────────
// These must be standalone functions, not entries in a CSSProperties record,
// because TypeScript enforces that Record<string, CSSProperties> values are
// plain objects — not functions.

function statusPillStyle(online: boolean): CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    padding: '3px 10px',
    borderRadius: '999px',
    fontSize: '12px',
    fontWeight: 600,
    background: online ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)',
    color: online ? 'var(--accent-green)' : 'var(--accent-red)',
    border: `1px solid ${online ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
  };
}

function statusDotStyle(online: boolean): CSSProperties {
  return {
    width: '7px',
    height: '7px',
    borderRadius: '50%',
    background: online ? 'var(--accent-green)' : 'var(--accent-red)',
  };
}

function stageCardStyle(ringColor: string): CSSProperties {
  return {
    flex: '1 1 160px',
    minWidth: '140px',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
    padding: '16px',
    background: 'rgba(255,255,255,0.02)',
    border: `2px solid ${ringColor}`,
    borderRadius: '10px',
    position: 'relative',
  };
}

function agentBadgeStyle(cliType: CLIType): CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '5px',
    padding: '2px 8px',
    borderRadius: '999px',
    fontSize: '11px',
    fontWeight: 600,
    background: `${CLI_COLOR[cliType]}22`,
    color: CLI_COLOR[cliType],
    border: `1px solid ${CLI_COLOR[cliType]}44`,
    width: 'fit-content',
  };
}

function agentDotStyle(online: boolean): CSSProperties {
  return {
    width: '6px',
    height: '6px',
    borderRadius: '50%',
    background: online ? 'currentColor' : 'rgba(255,255,255,0.3)',
    flexShrink: 0,
  };
}

function statusLabelStyle(status: CLIStatus | 'unknown'): CSSProperties {
  return {
    fontSize: '10px',
    fontWeight: 700,
    letterSpacing: '0.6px',
    textTransform: 'uppercase',
    color:
      status === 'online'  ? 'var(--accent-green)' :
      status === 'busy'    ? 'var(--accent-blue)'  :
      status === 'idle'    ? 'var(--accent-amber)'  :
                             'var(--accent-red)',
  };
}

function progressBarFillStyle(pct: number, status: string): CSSProperties {
  return {
    width: `${pct}%`,
    height: '100%',
    borderRadius: '999px',
    background:
      status === 'done'   ? 'var(--accent-green)' :
      status === 'failed' ? 'var(--accent-red)'   :
                            'var(--accent-blue)',
    transition: 'width 0.4s ease',
  };
}

function statusBadgeGoalStyle(status: string): CSSProperties {
  return {
    fontSize: '10px',
    fontWeight: 700,
    padding: '2px 7px',
    borderRadius: '999px',
    letterSpacing: '0.4px',
    background:
      status === 'done'         ? 'rgba(16,185,129,0.15)'  :
      status === 'failed'       ? 'rgba(239,68,68,0.15)'   :
      status === 'in_progress'  ? 'rgba(59,130,246,0.15)'  :
                                  'rgba(255,255,255,0.08)',
    color:
      status === 'done'         ? 'var(--accent-green)' :
      status === 'failed'       ? 'var(--accent-red)'   :
      status === 'in_progress'  ? 'var(--accent-blue)'  :
                                  'var(--text-muted)',
    border:
      status === 'done'         ? '1px solid rgba(16,185,129,0.3)'  :
      status === 'failed'       ? '1px solid rgba(239,68,68,0.3)'   :
      status === 'in_progress'  ? '1px solid rgba(59,130,246,0.3)'  :
                                  '1px solid var(--border)',
  };
}

function feedCliStyle(cli: string): CSSProperties {
  const color = CLI_COLOR[cli as CLIType] ?? '#888';
  return {
    fontSize: '10px',
    fontWeight: 700,
    padding: '1px 6px',
    borderRadius: '999px',
    background: `${color}22`,
    color,
    border: `1px solid ${color}44`,
    flexShrink: 0,
    textTransform: 'uppercase',
  };
}

function confFillStyle(pct: number): CSSProperties {
  return {
    height: '100%',
    width: `${pct}%`,
    borderRadius: '999px',
    background:
      pct >= 80 ? 'var(--accent-green)' :
      pct >= 50 ? 'var(--accent-amber)' :
                  'var(--accent-red)',
  };
}

// ── Static styles object ───────────────────────────────────────────────────────

const S: Record<string, CSSProperties> = {
  page: { display: 'flex', flexDirection: 'column', gap: '20px', minHeight: '100%' },

  header: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: '12px',
    flexWrap: 'wrap',
  },
  headerLeft:  { display: 'flex', flexDirection: 'column', gap: '2px' },
  headerTitle: {
    margin: 0,
    fontSize: '22px',
    fontWeight: 700,
    letterSpacing: '-0.3px',
    color: 'var(--text-primary)',
  },
  headerSub: { margin: 0, fontSize: '13px', color: 'var(--text-muted)' },
  headerRight: { display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' },

  versionTag: {
    fontSize: '11px',
    color: 'var(--text-muted)',
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    padding: '3px 8px',
    borderRadius: '6px',
  },

  metricsStrip: { display: 'flex', gap: '10px', flexWrap: 'wrap' },
  metricChip: {
    flex: '1 1 120px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '14px 16px',
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '10px',
    gap: '2px',
  },
  metricValue: {
    fontSize: '26px',
    fontWeight: 700,
    color: 'var(--text-primary)',
    lineHeight: 1,
  },
  metricValueAmber: {
    fontSize: '26px',
    fontWeight: 700,
    lineHeight: 1,
    color: 'var(--accent-amber)',
  },
  metricLabel: { fontSize: '11px', color: 'var(--text-muted)', textAlign: 'center' },

  pipelineSection: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '12px',
    padding: '20px 24px',
  },
  pipelineTitle: {
    margin: '0 0 16px',
    fontSize: '13px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.6px',
    color: 'var(--text-muted)',
  },
  pipelineRow: {
    display: 'flex',
    alignItems: 'stretch',
    gap: '0',
    overflowX: 'auto',
  },

  stageHeader: { display: 'flex', alignItems: 'center', gap: '6px' },
  stageName: {
    fontSize: '13px',
    fontWeight: 700,
    color: 'var(--text-primary)',
    textTransform: 'uppercase',
    letterSpacing: '0.4px',
  },
  stageCount:      { fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1 },
  stageCountLabel: { fontSize: '11px', color: 'var(--text-muted)' },
  stageRunning:    { fontSize: '11px', color: 'var(--accent-blue)' },
  hitlPill: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    padding: '2px 7px',
    borderRadius: '999px',
    fontSize: '10px',
    fontWeight: 700,
    background: 'rgba(245,158,11,0.15)',
    color: 'var(--accent-amber)',
    border: '1px solid rgba(245,158,11,0.3)',
    width: 'fit-content',
  },
  stageOutcome: {
    fontSize: '11px',
    color: 'var(--text-secondary)',
    fontStyle: 'italic',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: '100%',
  },

  arrowWrapper: {
    display: 'flex',
    alignItems: 'center',
    padding: '0 6px',
    flexShrink: 0,
    alignSelf: 'center',
  },

  bottomGrid: {
    display: 'grid',
    gridTemplateColumns: '3fr 2fr',
    gap: '16px',
    alignItems: 'start',
  },

  panel: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '12px',
    overflow: 'hidden',
  },
  panelHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 18px',
    borderBottom: '1px solid var(--border)',
  },
  panelTitle: {
    margin: 0,
    fontSize: '13px',
    fontWeight: 600,
    color: 'var(--text-primary)',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  panelCount: {
    fontSize: '11px',
    color: 'var(--text-muted)',
    background: 'rgba(255,255,255,0.06)',
    padding: '2px 7px',
    borderRadius: '999px',
  },

  goalItem: {
    padding: '12px 18px',
    borderBottom: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  goalText: {
    fontSize: '13px',
    fontWeight: 500,
    color: 'var(--text-primary)',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  goalMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    flexWrap: 'wrap',
  },
  progressBarTrack: {
    flex: 1,
    height: '5px',
    background: 'rgba(255,255,255,0.08)',
    borderRadius: '999px',
    overflow: 'hidden',
    minWidth: '60px',
  },
  progressLabel: { fontSize: '11px', color: 'var(--text-muted)', flexShrink: 0 },

  approveBtn: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    padding: '3px 10px',
    borderRadius: '6px',
    fontSize: '11px',
    fontWeight: 600,
    cursor: 'pointer',
    background: 'rgba(245,158,11,0.15)',
    color: 'var(--accent-amber)',
    border: '1px solid rgba(245,158,11,0.4)',
    transition: 'background 0.15s',
  },

  emptyState: {
    padding: '32px 18px',
    textAlign: 'center',
    color: 'var(--text-muted)',
    fontSize: '13px',
  },

  feedList: {
    display: 'flex',
    flexDirection: 'column',
    maxHeight: '420px',
    overflowY: 'auto',
  },
  feedItem: {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
    padding: '10px 18px',
    borderBottom: '1px solid var(--border)',
  },
  feedRow: { display: 'flex', alignItems: 'center', gap: '7px' },
  feedOutcome: {
    fontSize: '12px',
    color: 'var(--text-secondary)',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
  },
  feedTime: { fontSize: '10px', color: 'var(--text-muted)', flexShrink: 0 },
  confBar: {
    height: '3px',
    borderRadius: '999px',
    background: 'rgba(255,255,255,0.06)',
    overflow: 'hidden',
    width: '100%',
  },
};

// ── Utility functions ─────────────────────────────────────────────────────────

function relativeTime(isoString: string | null): string {
  if (!isoString) return '';
  const diffMs = Date.now() - new Date(isoString).getTime();
  if (diffMs < 10000) return 'just now';
  const secs = Math.floor(diffMs / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

function truncate(str: string | null | undefined, len: number): string {
  if (!str) return '';
  return str.length > len ? str.slice(0, len) + '…' : str;
}

function goalProgress(goal: GoalRecord): { done: number; total: number; hitl: number } {
  const tasks = goal.tasks ?? [];
  return {
    done:  tasks.filter(t => t.status === 'completed').length,
    total: tasks.length,
    hitl:  tasks.filter(t => t.status === 'hitl_pending').length,
  };
}

function taskStage(task: TaskRecord): StageKey | null {
  const t = (task.task_type ?? '').toLowerCase();
  if (t === 'research')                          return 'research';
  if (t === 'code' || t === 'coding' || t === 'implementation') return 'code';
  if (t === 'test' || t === 'testing')           return 'test';
  if (t === 'evaluate' || t === 'evaluation')    return 'evaluate';
  return null;
}

function stageRingColor(
  agentStatus: CLIStatus | 'unknown',
  runningCount: number,
  hitlCount: number,
): string {
  if (hitlCount > 0)                                           return 'var(--accent-amber)';
  if (agentStatus === 'offline' || agentStatus === 'unknown') return 'var(--border)';
  if (runningCount > 0 || agentStatus === 'busy')             return 'rgba(59,130,246,0.5)';
  if (agentStatus === 'online')                               return 'rgba(16,185,129,0.5)';
  if (agentStatus === 'idle')                                 return 'rgba(245,158,11,0.4)';
  return 'var(--border)';
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${Math.round(n / 1_000)}k`;
  return String(n);
}

// ── Sub-components ────────────────────────────────────────────────────────────

/** Animated arrow connector between pipeline stages */
function PipelineArrow({ flowing }: { flowing: boolean }) {
  return (
    <div style={S.arrowWrapper} aria-hidden="true">
      <svg
        width="32"
        height="16"
        viewBox="0 0 32 16"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        style={{ opacity: flowing ? 1 : 0.3 }}
      >
        <style>{`
          @keyframes dashFlow {
            from { stroke-dashoffset: 0; }
            to   { stroke-dashoffset: -14; }
          }
        `}</style>
        <line
          x1="0"
          y1="8"
          x2="22"
          y2="8"
          stroke={flowing ? 'var(--accent-blue)' : 'var(--border)'}
          strokeWidth="1.5"
          strokeDasharray={flowing ? '4 3' : '0'}
          style={flowing ? { animation: 'dashFlow 1s linear infinite' } : undefined}
        />
        <polyline
          points="20,4 27,8 20,12"
          stroke={flowing ? 'var(--accent-blue)' : 'var(--border)'}
          strokeWidth="1.5"
          fill="none"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}

/** Single stage card in the pipeline map */
function StageCard({
  stageKey,
  allTasks,
  agentStatus,
  fleetLoading,
}: {
  stageKey: StageKey;
  allTasks: TaskRecord[];
  agentStatus: CLIStatus | 'unknown';
  fleetLoading: boolean;
}) {
  const meta       = STAGE_META[stageKey];
  const stageTasks = allTasks.filter(t => taskStage(t) === stageKey);
  const doneCount    = stageTasks.filter(t => t.status === 'completed').length;
  const runningCount = stageTasks.filter(
    t => t.status === 'in_progress' || t.status === 'claimed',
  ).length;
  const hitlCount = stageTasks.filter(t => t.status === 'hitl_pending').length;

  const latestCompleted = [...stageTasks]
    .filter(t => t.status === 'completed' && t.completed_at)
    .sort(
      (a, b) =>
        new Date(b.completed_at!).getTime() - new Date(a.completed_at!).getTime(),
    )[0];

  const isConnecting = fleetLoading && agentStatus === 'unknown';
  const displayStatus = isConnecting ? 'idle' : agentStatus;
  const ringColor = stageRingColor(displayStatus, runningCount, hitlCount);
  const isAgentLive = agentStatus === 'online' || agentStatus === 'busy';

  return (
    <div
      style={stageCardStyle(ringColor)}
      role="region"
      aria-label={`${meta.label} stage`}
    >
      <div style={S.stageHeader}>
        <span style={S.stageName}>{meta.label}</span>
      </div>

      <div style={agentBadgeStyle(meta.primaryAgent)}>
        <span style={agentDotStyle(isAgentLive)} aria-hidden="true" />
        {CLI_META.labels[meta.primaryAgent]}
      </div>

      <span style={statusLabelStyle(displayStatus)}>
        {isConnecting ? 'CONNECTING…' : agentStatus === 'unknown' ? 'OFFLINE' : agentStatus.toUpperCase()}
      </span>

      <div>
        <div style={S.stageCount}>{doneCount}</div>
        <div style={S.stageCountLabel}>tasks done</div>
      </div>

      {runningCount > 0 && (
        <span style={S.stageRunning}>{runningCount} running</span>
      )}

      {hitlCount > 0 && (
        <span style={S.hitlPill}>
          {hitlCount} HITL
        </span>
      )}

      {latestCompleted?.outcome && (
        <div style={S.stageOutcome} title={latestCompleted.outcome}>
          {truncate(latestCompleted.outcome, 60)}
        </div>
      )}
    </div>
  );
}

/** Compact goal list item */
function GoalItem({
  goal,
  onApprove,
}: {
  goal: GoalRecord;
  onApprove: (goalId: string, taskId: string) => void;
}) {
  const { done, total, hitl } = goalProgress(goal);
  const pct      = total > 0 ? Math.round((done / total) * 100) : 0;
  const isDone   = goal.status === 'done' || goal.status === 'completed';
  const isFailed = goal.status === 'failed';
  const displayStatus = isDone ? 'done' : isFailed ? 'failed' : 'in_progress';

  const hitlTask = goal.tasks?.find(t => t.status === 'hitl_pending');

  return (
    <div style={S.goalItem}>
      <div style={S.goalText} title={goal.goal}>
        {truncate(goal.goal, 60)}
      </div>
      <div style={S.goalMeta}>
        <div
          style={S.progressBarTrack}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${pct}% complete`}
        >
          <div style={progressBarFillStyle(pct, displayStatus)} />
        </div>
        <span style={S.progressLabel}>{done}/{total}</span>
        <span style={statusBadgeGoalStyle(displayStatus)}>
          {isDone ? 'Done' : isFailed ? 'Failed' : displayStatus.replace('_', ' ')}
        </span>
        {hitl > 0 && hitlTask && !isDone && (
          <button
            style={S.approveBtn}
            onClick={() => onApprove(goal.goal_id, hitlTask.task_id)}
            aria-label={`Approve HITL task for goal: ${goal.goal}`}
          >
            Approve
          </button>
        )}
      </div>
    </div>
  );
}

/** Activity feed item — one completed task */
type FeedTask = TaskRecord & { _goalText?: string };

function FeedItem({ task }: { task: FeedTask }) {
  const agent = task.assigned_to ?? 'system';
  const conf =
    typeof task.artifacts?.confidence === 'number'
      ? (task.artifacts.confidence as number) * 100
      : null;

  return (
    <div style={S.feedItem}>
      <div style={S.feedRow}>
        <span style={feedCliStyle(agent)} aria-label={`Agent: ${agent}`}>
          {agent}
        </span>
        <span style={S.feedOutcome} title={task.outcome ?? ''}>
          {truncate(task.outcome, 40) || task.task_type}
        </span>
        <span style={S.feedTime}>{relativeTime(task.completed_at)}</span>
      </div>
      {task._goalText && (
        <div style={{
          fontSize: '10px',
          color: 'var(--text-muted)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          paddingLeft: '1px',
        }}>
          {truncate(task._goalText, 55)}
        </div>
      )}
      {conf !== null && (
        <div
          style={S.confBar}
          role="meter"
          aria-valuenow={Math.round(conf)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Confidence: ${Math.round(conf)}%`}
        >
          <div style={confFillStyle(conf)} />
        </div>
      )}
    </div>
  );
}

/** Shown when engine is unreachable */
function OfflineFallback({
  error,
  refresh,
}: {
  error: string | null;
  refresh: () => void;
}) {
  return (
    <div className="fade-in" style={S.page}>
      <header style={S.header}>
        <div style={S.headerLeft}>
          <h1 style={S.headerTitle}>Agent Factory</h1>
          <p style={S.headerSub}>Autonomous Delivery Pipeline</p>
        </div>
        <div style={S.headerRight}>
          <span style={statusPillStyle(false)} role="status">
            <span style={statusDotStyle(false)} aria-hidden="true" />
            Offline
          </span>
        </div>
      </header>
      <div
        className="kpi-card"
        style={{ borderColor: 'rgba(239,68,68,0.3)', maxWidth: '420px' }}
      >
        <div className="kpi-label">Engine Unreachable</div>
        <div
          className="kpi-value"
          style={{ color: 'var(--accent-red)', fontSize: '20px' }}
        >
          {error || 'Cannot reach engine at localhost:8082'}
        </div>
        <button className="btn btn-ghost" onClick={refresh} style={{ marginTop: '16px' }}>
          ↻ Retry
        </button>
      </div>
    </div>
  );
}

// ── Main Dashboard component ──────────────────────────────────────────────────

export function Dashboard() {
  const { health, stats, connected, loading, error, refresh: refreshEngine } =
    useEngine(10000);
  const { fleet } = useFleet();
  const navigate = useNavigate();

  const [goals, setGoals] = useState<GoalRecord[]>([]);
  const [goalsLoading, setGoalsLoading] = useState(true);
  const [nexusPending, setNexusPending] = useState<number | null>(null);

  const fetchGoals = useCallback(async () => {
    try {
      const res = await fetch(`${ENGINE}/api/goals?limit=20`);
      if (!res.ok) return;
      const data: GoalRecord[] = await res.json();
      setGoals(data);
    } catch {
      // engine offline — keep stale data
    } finally {
      setGoalsLoading(false);
    }
  }, []);

  // Stable ref so the interval never restarts while goals state updates
  const fetchGoalsRef = useRef(fetchGoals);
  fetchGoalsRef.current = fetchGoals;

  useEffect(() => {
    fetchGoalsRef.current();
    const id = setInterval(() => fetchGoalsRef.current(), GOALS_POLL_MS);
    return () => clearInterval(id);
  }, []); // intentionally empty — interval is bootstrapped once

  // Poll nexus-kb pending review count every 30s
  useEffect(() => {
    const fetchNexus = async () => {
      try {
        const r = await fetch(`${NEXUS_API}/api/v1/review/queue?limit=100`, {
          headers: { 'X-User-Role': 'Reviewer' },
          signal: AbortSignal.timeout(4000),
        });
        if (r.ok) {
          const data: unknown[] = await r.json();
          setNexusPending(data.length);
        }
      } catch {
        // nexus-kb offline — keep last value
      }
    };
    fetchNexus();
    const id = setInterval(fetchNexus, 30_000);
    return () => clearInterval(id);
  }, []);

  const handleApprove = useCallback(async (goalId: string, taskId: string) => {
    try {
      await fetch(`${ENGINE}/api/ba/goals/${goalId}/tasks/${taskId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: true }),
      });
      // Immediate single-goal refresh
      const res = await fetch(`${ENGINE}/api/goals/${goalId}`);
      if (res.ok) {
        const updated: GoalRecord = await res.json();
        setGoals(prev => prev.map(g => (g.goal_id === goalId ? updated : g)));
      }
    } catch {
      // next poll will reflect updated state
    }
  }, []);

  // ── Loading / offline guards ──────────────────────────────────────────────

  if (loading) {
    return (
      <div className="fade-in" style={S.page}>
        <header style={S.header}>
          <div style={S.headerLeft}>
            <h1 style={S.headerTitle}>Agent Factory</h1>
            <p style={S.headerSub}>Connecting to engine…</p>
          </div>
        </header>
      </div>
    );
  }

  if (!connected) {
    return <OfflineFallback error={error} refresh={refreshEngine} />;
  }

  // ── Derived values ────────────────────────────────────────────────────────

  const fleetLoading = fleet.length === 0;

  const STATUS_RANK: Record<string, number> = { in_progress: 0, pending: 1, done: 2, failed: 3 };
  const sortedGoals = [...goals].sort((a, b) => {
    const ra = STATUS_RANK[a.status] ?? 1;
    const rb = STATUS_RANK[b.status] ?? 1;
    if (ra !== rb) return ra - rb;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });

  const allTasks: TaskRecord[] = goals.flatMap(g => g.tasks ?? []);

  const totalDoneTasks = allTasks.filter(t => t.status === 'completed').length;

  const totalTokens = allTasks.reduce((sum, t) => {
    const v = t.artifacts?.tokens_estimated;
    return sum + (typeof v === 'number' ? v : 0);
  }, 0);

  const onlineCount = fleet.filter(
    c => c.status === 'online' || c.status === 'busy',
  ).length;

  const hitlPendingCount = allTasks.filter(t => t.status === 'hitl_pending').length;

  const agentStatus = (cli: CLIType): CLIStatus | 'unknown' => {
    const rec = fleet.find(f => f.cli_type === cli);
    return rec?.status ?? 'unknown';
  };

  const hasRunning = (stage: StageKey): boolean =>
    allTasks.some(
      t =>
        taskStage(t) === stage &&
        (t.status === 'in_progress' || t.status === 'claimed'),
    );

  const completedTasks: FeedTask[] = allTasks
    .filter(t => t.status === 'completed' && t.completed_at)
    .map(t => ({
      ...t,
      _goalText: goals.find(g => g.goal_id === t.goal_id)?.goal,
    }))
    .sort(
      (a, b) =>
        new Date(b.completed_at!).getTime() - new Date(a.completed_at!).getTime(),
    )
    .slice(0, 12);

  const timeStr = new Date().toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="fade-in" style={S.page}>

      {/* 1. Header */}
      <header style={S.header}>
        <div style={S.headerLeft}>
          <h1 style={S.headerTitle}>Agent Factory</h1>
          <p style={S.headerSub}>Autonomous Delivery Pipeline</p>
        </div>
        <div style={S.headerRight}>
          <span
            style={statusPillStyle(connected)}
            role="status"
            aria-live="polite"
            aria-label={`Engine status: ${connected ? 'Online' : 'Offline'}`}
          >
            <span style={statusDotStyle(connected)} aria-hidden="true" />
            {connected ? 'Online' : 'Offline'}
          </span>
          <span
            style={S.versionTag}
            aria-label={`Version ${health?.version ?? '0.3.0'}`}
          >
            v{health?.version ?? '0.3.0'}
          </span>
          <button
            className="btn btn-ghost"
            onClick={() => { refreshEngine(); fetchGoals(); }}
            aria-label="Refresh dashboard data"
            style={{ fontSize: '14px', padding: '4px 10px' }}
          >
            ↻ {timeStr}
          </button>
        </div>
      </header>

      {/* 2. Metrics strip */}
      <section aria-label="Live metrics" style={S.metricsStrip}>
        <div style={S.metricChip}>
          <span style={S.metricValue}>{goals.length}</span>
          <span style={S.metricLabel}>Goals</span>
        </div>
        <div style={S.metricChip}>
          <span style={S.metricValue}>{totalDoneTasks}</span>
          <span style={S.metricLabel}>Tasks Done</span>
        </div>
        <div style={S.metricChip}>
          <span style={S.metricValue}>
            {totalTokens > 0
              ? `~${fmtTokens(totalTokens)}`
              : (stats?.queries_today ?? 0)}
          </span>
          <span style={S.metricLabel}>
            {totalTokens > 0 ? 'Tokens Est.' : 'Queries Today'}
          </span>
        </div>
        <div style={S.metricChip}>
          <span style={S.metricValue}>{onlineCount}</span>
          <span style={S.metricLabel}>CLIs Online</span>
        </div>
        <div style={S.metricChip}>
          <span
            style={
              hitlPendingCount > 0 ? S.metricValueAmber : S.metricValue
            }
          >
            {hitlPendingCount}
          </span>
          <span style={S.metricLabel}>HITL Pending</span>
        </div>
        <div
          style={{ ...S.metricChip, cursor: nexusPending !== null ? 'pointer' : 'default' }}
          onClick={() => nexusPending !== null && navigate('/nexus-review')}
          role={nexusPending !== null ? 'button' : undefined}
          aria-label="Nexus-KB pending reviews"
        >
          <span style={nexusPending ? S.metricValueAmber : S.metricValue}>
            {nexusPending ?? '—'}
          </span>
          <span style={S.metricLabel}>Nexus Reviews</span>
        </div>
      </section>

      {/* 3. Pipeline coverage map */}
      <section style={S.pipelineSection} aria-label="Pipeline coverage map">
        <h2 style={S.pipelineTitle}>Pipeline Coverage</h2>
        <div style={S.pipelineRow}>
          {STAGE_ORDER.map((stage, idx) => (
            <div key={stage} style={{ display: 'contents' }}>
              <StageCard
                stageKey={stage}
                allTasks={allTasks}
                agentStatus={agentStatus(STAGE_META[stage].primaryAgent)}
                fleetLoading={fleetLoading}
              />
              {idx < STAGE_ORDER.length - 1 && (
                <PipelineArrow
                  flowing={
                    hasRunning(stage) ||
                    hasRunning(STAGE_ORDER[idx + 1])
                  }
                />
              )}
            </div>
          ))}
        </div>
      </section>

      {/* 4. Bottom grid */}
      <div style={S.bottomGrid}>

        {/* Active Goals — left 60% */}
        <section style={S.panel} aria-label="Active goals">
          <div style={S.panelHeader}>
            <h2 style={S.panelTitle}>Active Goals</h2>
            <span style={S.panelCount}>
              {sortedGoals.length} goal{sortedGoals.length !== 1 ? 's' : ''}
            </span>
          </div>
          {goalsLoading ? (
            <div style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {[0, 1, 2].map(i => (
                <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div className="skeleton" style={{ height: '14px', width: `${70 - i * 10}%` }} />
                  <div className="skeleton" style={{ height: '5px', width: '100%' }} />
                </div>
              ))}
            </div>
          ) : sortedGoals.length === 0 ? (
            <div style={S.emptyState}>
              No goals yet — submit one via the Goals tab
            </div>
          ) : (
            <div role="list" aria-label="Goals list">
              {sortedGoals.slice(0, 8).map(g => (
                <div key={g.goal_id} role="listitem">
                  <GoalItem goal={g} onApprove={handleApprove} />
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Activity Feed — right 40% */}
        <section style={S.panel} aria-label="Activity feed">
          <div style={S.panelHeader}>
            <h2 style={S.panelTitle}>Activity Feed</h2>
            <span style={S.panelCount}>{completedTasks.length} recent</span>
          </div>
          {completedTasks.length === 0 ? (
            <div style={S.emptyState}>No completed tasks yet</div>
          ) : (
            <div
              style={S.feedList}
              role="log"
              aria-label="Completed task activity"
              aria-live="polite"
            >
              {completedTasks.map(task => (
                <FeedItem key={task.task_id} task={task} />
              ))}
            </div>
          )}
        </section>

      </div>

    </div>
  );
}
