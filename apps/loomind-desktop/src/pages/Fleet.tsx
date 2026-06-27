/**
 * Fleet Monitor — live status of all CLI tools in the automation fleet.
 * Shows which CLI is busy/idle/offline and what task it's executing.
 */

import { useFleet, CLI_META, type CLIStatusRecord, type CLIType, type CliLogLine } from '../hooks/useFleet.ts';
import { useDeliberations } from '../hooks/useDeliberations.ts';
import { useState, useRef, useEffect, useMemo, memo, useCallback } from 'react';

const ENGINE = 'http://127.0.0.1:8082';

// ── Utility ─────────────────────────────────────────────────────────────────

function relativeTime(isoString: string | null): string {
  if (!isoString) return 'never';
  const diffMs = Date.now() - new Date(isoString).getTime();
  if (diffMs < 10_000) return 'just now';
  const secs = Math.floor(diffMs / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

// ── Status badge ────────────────────────────────────────────────────────────

const STATUS_STYLE: Record<string, { bg: string; color: string; dot: string }> = {
  online:  { bg: 'rgba(16,185,129,0.12)', color: '#10b981', dot: '#10b981' },
  busy:    { bg: 'rgba(245,158,11,0.12)', color: '#f59e0b', dot: '#f59e0b' },
  idle:    { bg: 'rgba(59,130,246,0.12)', color: '#3b82f6', dot: '#3b82f6' },
  offline: { bg: 'rgba(107,114,128,0.1)', color: '#6b7280', dot: '#4b5563' },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.offline;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '5px',
      padding: '2px 8px', borderRadius: '9999px',
      background: s.bg, color: s.color,
      fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em',
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: s.dot,
        boxShadow: status !== 'offline' ? `0 0 6px ${s.dot}` : 'none' }} />
      {status}
    </span>
  );
}

// ── CLI Card ────────────────────────────────────────────────────────────────

const CLICard = memo(function CLICard({ rec }: { rec: CLIStatusRecord }) {
  const color = CLI_META.colors[rec.cli_type as CLIType] ?? '#6b7280';
  const label = CLI_META.labels[rec.cli_type as CLIType] ?? rec.cli_type.toUpperCase();

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: `1px solid ${rec.status !== 'offline' ? color + '40' : 'var(--border)'}`,
      borderRadius: '12px',
      padding: '20px',
      display: 'flex', flexDirection: 'column', gap: '12px',
      transition: 'border-color 0.2s',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: 36, height: 36, borderRadius: '8px',
            background: color + '20', border: `1px solid ${color}40`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '16px', fontWeight: 700, color,
          }}>
            {label[0]}
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '15px', color: 'var(--text-primary)' }}>{label} CLI</div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '1px' }}>{rec.cli_type}</div>
          </div>
        </div>
        <StatusBadge status={rec.status} />
      </div>

      {/* Current task */}
      <div style={{
        minHeight: '36px',
        padding: '8px 10px',
        background: 'var(--bg-primary)',
        borderRadius: '6px',
        fontSize: '12px',
        color: rec.current_task ? 'var(--text-secondary)' : 'var(--text-muted)',
        fontFamily: rec.current_task ? 'monospace' : 'inherit',
        lineHeight: 1.4,
        wordBreak: 'break-word',
      }}>
        {rec.current_task || (rec.status === 'offline' ? 'Not registered' : 'Waiting for task...')}
      </div>

      {/* Footer stats */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
            <span style={{ fontSize: '18px', fontWeight: 700, color, lineHeight: 1 }}>
              {rec.tasks_completed}
            </span>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>tasks done</span>
          </div>
          {rec.tokens_estimated != null && rec.tokens_estimated > 0 && (
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              ~{rec.tokens_estimated > 999 ? (rec.tokens_estimated / 1000).toFixed(1) + 'k' : rec.tokens_estimated} tok
            </span>
          )}
          {rec.lines_generated != null && rec.lines_generated > 0 && (
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              {rec.lines_generated} ln
            </span>
          )}
        </div>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          {relativeTime(rec.last_seen)}
        </span>
      </div>

      {/* Deliberation link */}
      {rec.current_deliberation_id && (
        <div style={{
          fontSize: '11px', color: '#f59e0b',
          padding: '4px 8px', background: 'rgba(245,158,11,0.08)',
          borderRadius: '4px', fontFamily: 'monospace',
        }}>
          deliberation: {rec.current_deliberation_id.slice(0, 8)}...
        </div>
      )}
    </div>
  );
});

// ── HITL Resolve Panel ──────────────────────────────────────────────────────

function HITLPanel({ id, topic, onResolve }: {
  id: string;
  topic: string;
  onResolve: (approved: boolean, consensus: string) => void;
}) {
  const [consensus, setConsensus] = useState('');
  return (
    <div style={{
      border: '1px solid rgba(245,158,11,0.4)',
      borderRadius: '8px',
      padding: '16px',
      background: 'rgba(245,158,11,0.06)',
      display: 'flex', flexDirection: 'column', gap: '10px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '16px' }}>⚠️</span>
        <span style={{ fontWeight: 600, fontSize: '13px', color: '#f59e0b' }}>
          HITL Required
        </span>
      </div>
      <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
        <strong>Topic:</strong> {topic}
      </div>
      <textarea
        placeholder="Your decision / consensus text..."
        value={consensus}
        onChange={(e) => setConsensus(e.target.value)}
        style={{
          width: '100%', minHeight: '64px', resize: 'vertical',
          background: 'var(--bg-primary)', border: '1px solid var(--border)',
          borderRadius: '6px', padding: '8px', fontSize: '12px',
          color: 'var(--text-primary)', fontFamily: 'inherit', boxSizing: 'border-box',
        }}
      />
      <div style={{ display: 'flex', gap: '8px' }}>
        <button
          onClick={() => onResolve(true, consensus)}
          disabled={!consensus.trim()}
          style={{
            flex: 1, padding: '8px', borderRadius: '6px', border: 'none',
            background: 'rgba(16,185,129,0.15)', color: '#10b981',
            cursor: consensus.trim() ? 'pointer' : 'not-allowed', fontWeight: 600, fontSize: '12px',
          }}
        >
          Approve
        </button>
        <button
          onClick={() => onResolve(false, '')}
          style={{
            flex: 1, padding: '8px', borderRadius: '6px', border: 'none',
            background: 'rgba(239,68,68,0.12)', color: '#ef4444',
            cursor: 'pointer', fontWeight: 600, fontSize: '12px',
          }}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

// ── Deliberation Card ───────────────────────────────────────────────────────

function DeliberationCard({ d, onResolve }: {
  d: ReturnType<typeof useDeliberations>['deliberations'][0];
  onResolve: (id: string, approved: boolean, consensus: string) => void;
}) {
  const [expanded, setExpanded] = useState(d.status === 'hitl_pending');

  const statusColor: Record<string, string> = {
    open:         '#3b82f6',
    resolved:     '#10b981',
    hitl_pending: '#f59e0b',
    cancelled:    '#6b7280',
  };

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: `1px solid ${d.status === 'hitl_pending' ? 'rgba(245,158,11,0.4)' : 'var(--border)'}`,
      borderRadius: '10px', overflow: 'hidden',
    }}>
      {/* Header row */}
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: '12px 16px', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: '12px',
        }}
      >
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: statusColor[d.status] ?? '#6b7280', flexShrink: 0,
        }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {d.topic}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
            {d.initiator} → [{d.participants.join(', ')}] · {d.rounds.length}/{d.max_rounds} rounds
          </div>
        </div>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)', flexShrink: 0 }}>
          {expanded ? '▲' : '▼'}
        </span>
      </div>

      {/* Expanded body */}
      {expanded && (
        <div style={{ padding: '0 16px 16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {/* Rounds */}
          {d.rounds.map((r) => (
            <div key={r.round_id} style={{
              padding: '10px', background: 'var(--bg-primary)',
              borderRadius: '6px', fontSize: '12px',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ fontWeight: 600, color: CLI_META.colors[r.agent as CLIType] ?? '#6b7280' }}>
                  {CLI_META.labels[r.agent as CLIType] ?? r.agent.toUpperCase()}
                </span>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <span style={{ color: 'var(--text-muted)' }}>
                    conf: {(r.confidence * 100).toFixed(0)}%
                  </span>
                  <span style={{
                    padding: '1px 6px', borderRadius: '4px', fontSize: '10px',
                    fontWeight: 700, textTransform: 'uppercase',
                    background: r.vote === 'agree' ? 'rgba(16,185,129,0.15)' :
                      r.vote === 'need_human' ? 'rgba(245,158,11,0.15)' :
                      r.vote === 'disagree' ? 'rgba(239,68,68,0.12)' : 'rgba(107,114,128,0.1)',
                    color: r.vote === 'agree' ? '#10b981' :
                      r.vote === 'need_human' ? '#f59e0b' :
                      r.vote === 'disagree' ? '#ef4444' : '#9ca3af',
                  }}>
                    {r.vote.replace('_', ' ')}
                  </span>
                </div>
              </div>
              <div style={{ color: 'var(--text-secondary)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                {r.proposal.slice(0, 400)}{r.proposal.length > 400 ? '...' : ''}
              </div>
            </div>
          ))}

          {/* Consensus */}
          {d.consensus && (
            <div style={{
              padding: '10px', background: 'rgba(16,185,129,0.08)',
              border: '1px solid rgba(16,185,129,0.2)', borderRadius: '6px',
            }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#10b981', marginBottom: '4px' }}>
                CONSENSUS
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                {d.consensus}
              </div>
            </div>
          )}

          {/* HITL panel */}
          {d.status === 'hitl_pending' && (
            <HITLPanel
              id={d.deliberation_id}
              topic={d.topic}
              onResolve={(approved, consensus) => onResolve(d.deliberation_id, approved, consensus)}
            />
          )}
        </div>
      )}
    </div>
  );
}

// ── Deliberate Panel ────────────────────────────────────────────────────────

const CLI_OPTIONS = ['claude', 'grok', 'codex', 'agy', 'nexus-kb'];

function DeliberatePanel() {
  const [topic, setTopic] = useState('');
  const [context, setContext] = useState('');
  const [fromCli, setFromCli] = useState('nexus-kb');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ id?: string; error?: string } | null>(null);

  const submit = async () => {
    if (!topic.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const r = await fetch(`${ENGINE}/api/deliberate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: topic.trim(), context: context.trim(), from_cli: fromCli }),
      });
      const data = await r.json();
      if (r.ok) {
        setResult({ id: data.deliberation_id });
        setTopic('');
        setContext('');
      } else {
        setResult({ error: data.detail ?? 'Failed' });
      }
    } catch {
      setResult({ error: 'Engine unreachable' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: '12px', padding: '20px', marginBottom: '28px',
    }}>
      <div style={{ fontWeight: 700, fontSize: '13px', color: 'var(--text-muted)',
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '14px' }}>
        Start Deliberation
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <input
          placeholder="Topic — what should the CLIs deliberate about?"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && submit()}
          style={{
            padding: '9px 12px', background: 'var(--bg-primary)',
            border: '1px solid var(--border)', borderRadius: '7px',
            color: 'var(--text-primary)', fontSize: '13px', width: '100%', boxSizing: 'border-box',
          }}
        />
        <textarea
          placeholder="Context (optional) — e.g. nexus-kb phase, architecture decision..."
          value={context}
          onChange={(e) => setContext(e.target.value)}
          rows={2}
          style={{
            padding: '9px 12px', background: 'var(--bg-primary)',
            border: '1px solid var(--border)', borderRadius: '7px',
            color: 'var(--text-primary)', fontSize: '13px', resize: 'vertical',
            width: '100%', boxSizing: 'border-box', fontFamily: 'inherit',
          }}
        />
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <select
            value={fromCli}
            onChange={(e) => setFromCli(e.target.value)}
            style={{
              padding: '8px 10px', background: 'var(--bg-primary)',
              border: '1px solid var(--border)', borderRadius: '7px',
              color: 'var(--text-primary)', fontSize: '13px',
            }}
          >
            {CLI_OPTIONS.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <button
            onClick={submit}
            disabled={loading || !topic.trim()}
            style={{
              flex: 1, padding: '8px 16px', borderRadius: '7px', border: 'none',
              background: topic.trim() ? '#3b82f6' : 'rgba(107,114,128,0.2)',
              color: topic.trim() ? '#fff' : '#6b7280',
              cursor: topic.trim() ? 'pointer' : 'not-allowed',
              fontWeight: 600, fontSize: '13px',
            }}
          >
            {loading ? 'Starting…' : 'Deliberate'}
          </button>
        </div>
        {result && (
          <div style={{
            padding: '8px 12px', borderRadius: '6px', fontSize: '12px',
            background: result.id ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)',
            color: result.id ? '#10b981' : '#ef4444',
            border: `1px solid ${result.id ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'}`,
          }}>
            {result.id ? `Started: ${result.id.slice(0, 12)}… — see Council Room below` : `Error: ${result.error}`}
          </div>
        )}
      </div>
    </div>
  );
}

// ── CLI Log Panel ────────────────────────────────────────────────────────────

const LOG_LEVEL_COLOR: Record<string, string> = {
  INFO: '#10b981', WARNING: '#f59e0b', ERROR: '#ef4444', DEBUG: '#6b7280',
};

const CliLogPanel = memo(function CliLogPanel({ logs, onClear }: { logs: CliLogLine[]; onClear: () => void }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledUp = useRef(false);

  // Track if user has manually scrolled up
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    userScrolledUp.current = el.scrollHeight - el.scrollTop - el.clientHeight > 40;
  };

  // Auto-scroll only when new lines arrive and user hasn't scrolled up
  useEffect(() => {
    if (userScrolledUp.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  if (logs.length === 0) {
    return (
      <div style={{
        padding: '20px', textAlign: 'center', color: 'var(--text-muted)',
        background: '#060a0f', borderRadius: '8px', fontSize: '12px',
        fontFamily: "'JetBrains Mono',monospace",
      }}>
        CLI output will appear here during deliberations...
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      style={{
        background: '#060a0f', borderRadius: '8px', maxHeight: '240px',
        overflowY: 'auto', contain: 'strict',
      }}
    >
      {logs.map((l) => (
        <div key={l.id} style={{
          display: 'grid', gridTemplateColumns: '70px 48px 80px 1fr',
          padding: '1px 0', fontFamily: "'JetBrains Mono',monospace", fontSize: 11, lineHeight: '17px',
        }}>
          <span style={{ color: '#374151', paddingLeft: 10 }}>
            {new Date(l.timestamp).toLocaleTimeString('en-GB', { hour12: false })}
          </span>
          <span style={{ color: LOG_LEVEL_COLOR[l.level] ?? '#9ca3af', fontWeight: 700 }}>
            {l.level.slice(0, 4)}
          </span>
          <span style={{ color: CLI_META.colors[l.cli as CLIType] ?? '#a855f7', overflow: 'hidden',
            textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {l.cli}
          </span>
          <span style={{ color: '#d1d5db', paddingRight: 10, wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>
            {l.message}
          </span>
        </div>
      ))}
    </div>
  );
});

// ── Skeleton card ────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border)',
      borderRadius: '12px',
      padding: '20px',
      display: 'flex', flexDirection: 'column', gap: '12px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <div className="skeleton" style={{ width: 36, height: 36, borderRadius: '8px' }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div className="skeleton" style={{ width: 80, height: 14 }} />
            <div className="skeleton" style={{ width: 50, height: 10 }} />
          </div>
        </div>
        <div className="skeleton" style={{ width: 60, height: 22, borderRadius: '9999px' }} />
      </div>
      <div className="skeleton" style={{ height: 36, borderRadius: '6px' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div className="skeleton" style={{ width: 40, height: 20 }} />
        <div className="skeleton" style={{ width: 50, height: 10 }} />
      </div>
    </div>
  );
}

// ── Fleet Pause Hook ─────────────────────────────────────────────────────────

function useFleetPause() {
  const [paused, setPaused] = useState(false);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    fetch(`${ENGINE}/api/agents/fleet/pause`)
      .then((r) => r.json())
      .then((d) => setPaused(d.paused ?? false))
      .catch(() => {});
  }, []);

  const toggle = useCallback(async () => {
    setToggling(true);
    try {
      const endpoint = paused ? 'resume' : 'pause';
      const res = await fetch(`${ENGINE}/api/agents/fleet/${endpoint}`, { method: 'POST' });
      const d = await res.json();
      setPaused(d.paused ?? !paused);
    } catch {
      // ignore — UI stays at previous state
    } finally {
      setToggling(false);
    }
  }, [paused]);

  return { paused, toggling, toggle };
}

// ── Fleet Page ──────────────────────────────────────────────────────────────

export function Fleet() {
  const { fleet, connected, cliLogs, clearLogs } = useFleet();
  const { deliberations, hitlPending, active, resolved, resolveHITL } = useDeliberations();
  const { paused, toggling, toggle } = useFleetPause();

  const fleetLoading = fleet.length === 0;

  const { busyCount, onlineCount, totalTasksDone } = useMemo(() => ({
    busyCount:     fleet.filter((r) => r.status === 'busy').length,
    onlineCount:   fleet.filter((r) => r.status !== 'offline').length,
    totalTasksDone: fleet.reduce((s, r) => s + (r.tasks_completed ?? 0), 0),
  }), [fleet]);

  const kpis = useMemo(() => [
    { label: 'CLIs Online',     value: fleetLoading ? '—' : String(onlineCount),    color: '#10b981' },
    { label: 'Busy',            value: fleetLoading ? '—' : String(busyCount),       color: '#f59e0b' },
    { label: 'Tasks Completed', value: fleetLoading ? '—' : String(totalTasksDone),  color: '#3b82f6' },
    { label: 'Awaiting HITL',   value: String(hitlPending.length),
      color: hitlPending.length > 0 ? '#f59e0b' : 'var(--text-muted)' },
  ], [fleetLoading, onlineCount, busyCount, totalTasksDone, hitlPending.length]);

  return (
    <div style={{ padding: '24px 28px', maxWidth: '1200px', width: '100%' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '22px', fontWeight: 700, color: 'var(--text-primary)' }}>
            Fleet Monitor
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: 'var(--text-muted)' }}>
            Multi-CLI automation fleet — autonomous deliberation engine
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            onClick={toggle}
            disabled={toggling}
            title={paused ? 'Resume fleet — agents will pick up tasks again' : 'Pause fleet — agents stop picking up new tasks'}
            style={{
              padding: '5px 14px', borderRadius: '6px', fontSize: '12px', fontWeight: 600,
              cursor: toggling ? 'wait' : 'pointer',
              border: paused ? '1px solid rgba(245,158,11,0.5)' : '1px solid rgba(107,114,128,0.3)',
              background: paused ? 'rgba(245,158,11,0.12)' : 'rgba(107,114,128,0.08)',
              color: paused ? '#f59e0b' : 'var(--text-muted)',
              transition: 'all 0.15s',
            }}
          >
            {paused ? '▶ Resume' : '⏸ Pause'}
          </button>
          <span style={{
            width: 7, height: 7, borderRadius: '50%',
            background: connected ? '#10b981' : '#6b7280',
            boxShadow: connected ? '0 0 6px #10b981' : 'none',
          }} />
          <span style={{ fontSize: '12px', color: connected ? 'var(--accent-green)' : 'var(--text-muted)' }}>
            {connected ? 'Live' : 'Connecting…'}
          </span>
        </div>
      </div>

      {/* Paused banner */}
      {paused && (
        <div style={{
          marginBottom: '20px', padding: '10px 16px', borderRadius: '8px',
          background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)',
          fontSize: '13px', color: '#f59e0b',
          display: 'flex', alignItems: 'center', gap: '8px',
        }}>
          <span>⏸</span>
          <span>Fleet paused — agents are not picking up new tasks. Click <strong>Resume</strong> to restart polling.</span>
        </div>
      )}

      {/* Disconnected banner */}
      {!connected && (
        <div style={{
          marginBottom: '20px', padding: '10px 16px', borderRadius: '8px',
          background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)',
          fontSize: '13px', color: '#f59e0b',
          display: 'flex', alignItems: 'center', gap: '8px',
        }}>
          <span>⚡</span>
          <span>Connecting to engine SSE stream — fleet data will appear momentarily</span>
        </div>
      )}

      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '12px', marginBottom: '28px' }}>
        {kpis.map((k) => (
          <div key={k.label} style={{
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: '10px', padding: '16px',
          }}>
            <div style={{ fontSize: '24px', fontWeight: 700, color: k.color }}>{k.value}</div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* CLI Cards */}
      <div style={{ marginBottom: '32px' }}>
        <h3 style={{ margin: '0 0 12px', fontSize: '13px', fontWeight: 700,
          color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          CLI Fleet
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '14px' }}>
          {fleetLoading
            ? [0, 1, 2, 3].map(i => <SkeletonCard key={i} />)
            : fleet.map((rec) => <CLICard key={rec.cli_type} rec={rec} />)
          }
        </div>
      </div>

      {/* Deliberate Now */}
      <DeliberatePanel />

      {/* CLI Live Log */}
      <div style={{ marginBottom: '32px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
          <h3 style={{ margin: 0, fontSize: '13px', fontWeight: 700,
            color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            CLI Live Output
          </h3>
          {cliLogs.length > 0 && (
            <button
              onClick={clearLogs}
              style={{
                padding: '2px 10px', fontSize: '11px', background: 'transparent',
                border: '1px solid var(--border)', borderRadius: '4px',
                color: 'var(--text-muted)', cursor: 'pointer',
              }}
            >
              Clear
            </button>
          )}
        </div>
        <CliLogPanel logs={cliLogs} onClear={clearLogs} />
      </div>

      {/* Deliberations */}
      <div>
        <h3 style={{ margin: '0 0 12px', fontSize: '13px', fontWeight: 700,
          color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          Council Room — Deliberations
          {hitlPending.length > 0 && (
            <span style={{
              marginLeft: '10px', padding: '1px 8px', borderRadius: '9999px',
              background: 'rgba(245,158,11,0.15)', color: '#f59e0b',
              fontSize: '11px', fontWeight: 700,
            }}>
              {hitlPending.length} HITL
            </span>
          )}
        </h3>

        {deliberations.length === 0 ? (
          <div style={{
            padding: '32px', textAlign: 'center', color: 'var(--text-muted)',
            background: 'var(--bg-secondary)', borderRadius: '10px', fontSize: '13px',
          }}>
            No deliberations yet. CLIs will post here when they need peer consultation.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {/* HITL first */}
            {hitlPending.map((d) => (
              <DeliberationCard key={d.deliberation_id} d={d} onResolve={resolveHITL} />
            ))}
            {/* Active */}
            {active.map((d) => (
              <DeliberationCard key={d.deliberation_id} d={d} onResolve={resolveHITL} />
            ))}
            {/* Resolved (last 5) */}
            {resolved.slice(0, 5).map((d) => (
              <DeliberationCard key={d.deliberation_id} d={d} onResolve={resolveHITL} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
