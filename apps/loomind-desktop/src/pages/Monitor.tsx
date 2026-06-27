/**
 * Monitor — Real-time SSE event stream + engine statistics
 *
 * Subscribes to /api/stream/monitor-ui to receive all broadcast events:
 * task_assigned, task_available, goal_completed, experience_evolved
 */

import { useState } from 'react';
import { useStream, StreamEvent } from '../hooks/useStream.ts';
import { useEngine } from '../hooks/useEngine.ts';

// ── Event type config ─────────────────────────────────────────────────────────

const EVENT_META: Record<string, { color: string }> = {
  task_assigned:      { color: 'var(--accent-blue)' },
  task_available:     { color: 'var(--accent-cyan)' },
  goal_completed:     { color: 'var(--accent-green)' },
  experience_evolved: { color: 'var(--accent-purple)' },
  unknown:            { color: 'var(--text-muted)' },
};

// ── EventItem component ───────────────────────────────────────────────────────

function EventItem({ evt }: { evt: StreamEvent }) {
  const [expanded, setExpanded] = useState(false);
  const meta = EVENT_META[evt.event] ?? EVENT_META.unknown;
  const time = new Date(evt.timestamp).toLocaleTimeString();
  const hasPayload = Object.keys(evt.payload).length > 0;

  return (
    <div
      className="event-item"
      style={{ borderLeft: `3px solid ${meta.color}` }}
      onClick={() => hasPayload && setExpanded(e => !e)}
    >
      <div className="event-item-header">
        <span className="event-type" style={{ color: meta.color }}>{evt.event}</span>
        <span className="event-time">{time}</span>
        {hasPayload && (
          <span style={{ color: 'var(--text-muted)', fontSize: 12, marginLeft: 'auto' }}>
            {expanded ? '▾' : '▸'}
          </span>
        )}
      </div>
      {expanded && hasPayload && (
        <pre className="event-payload">{JSON.stringify(evt.payload, null, 2)}</pre>
      )}
    </div>
  );
}

// ── Monitor page ──────────────────────────────────────────────────────────────

export function Monitor() {
  const [filter, setFilter] = useState('all');
  const { events, connected, clear } = useStream('monitor-ui');
  const { stats, health } = useEngine(10000);

  const filtered = filter === 'all' ? events : events.filter(e => e.event === filter);
  const eventTypes = ['all', ...Array.from(new Set(events.map(e => e.event)))];

  const counts = events.reduce<Record<string, number>>((acc, e) => {
    acc[e.event] = (acc[e.event] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="fade-in">
      {/* Header */}
      <div className="page-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h2>Monitor</h2>
            <p>Real-time event stream from the Harness Brain — SSE push</p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
            <span className={`status-dot ${connected ? 'online' : 'offline'}`} />
            <span style={{ fontSize: 13, color: connected ? 'var(--accent-green)' : 'var(--accent-red)', fontWeight: 600 }}>
              {connected ? 'Stream Connected' : 'Connecting…'}
            </span>
          </div>
        </div>
      </div>

      {/* Engine stats KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card blue">
          <div className="kpi-label">Total Queries</div>
          <div className="kpi-value">{stats?.total_queries ?? '—'}</div>
          <div className="kpi-sub">all time</div>
        </div>
        <div className="kpi-card green">
          <div className="kpi-label">Avg Latency</div>
          <div className="kpi-value">
            {stats?.avg_latency_ms != null ? `${stats.avg_latency_ms.toFixed(0)}ms` : '—'}
          </div>
          <div className="kpi-sub">intercept pipeline</div>
        </div>
        <div className="kpi-card purple">
          <div className="kpi-label">Events Captured</div>
          <div className="kpi-value">{events.length}</div>
          <div className="kpi-sub">this session</div>
        </div>
        <div className="kpi-card amber">
          <div className="kpi-label">Goals Completed</div>
          <div className="kpi-value">{counts['goal_completed'] ?? 0}</div>
          <div className="kpi-sub">this session</div>
        </div>
      </div>

      {/* Engine health row */}
      {health && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
          {[
            { label: 'Qdrant', ok: health.qdrant },
            { label: 'Embedder', ok: health.embedder_loaded },
            { label: 'LLM', ok: health.llm_available },
          ].map(({ label, ok }) => (
            <div
              key={label}
              className="capability-tag"
              style={{
                borderColor: ok ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)',
                color: ok ? 'var(--accent-green)' : 'var(--accent-red)',
              }}
            >
              {label} {ok ? '✓' : '✗'}
            </div>
          ))}
          {stats?.total_experiences != null && (
            <div className="capability-tag">{stats.total_experiences} experiences</div>
          )}
          {stats?.queries_today != null && (
            <div className="capability-tag">{stats.queries_today} queries today</div>
          )}
        </div>
      )}

      {/* Event type breakdown pills */}
      {events.length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
          {Object.entries(counts).map(([type, count]) => {
            const meta = EVENT_META[type] ?? EVENT_META.unknown;
            const active = filter === type;
            return (
              <button
                key={type}
                className="capability-tag"
                onClick={() => setFilter(active ? 'all' : type)}
                style={{
                  cursor: 'pointer',
                  border: active ? `1px solid ${meta.color}` : undefined,
                  color: active ? meta.color : undefined,
                  background: 'none',
                  fontFamily: 'var(--font)',
                }}
              >
                {type} ({count})
              </button>
            );
          })}
        </div>
      )}

      {/* Log header + controls */}
      <div
        className="table-header"
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius) var(--radius) 0 0',
        }}
      >
        <h3>
          Event Log
          {filter !== 'all' && (
            <span style={{ fontWeight: 400, color: 'var(--text-muted)', marginLeft: 8 }}>— {filter}</span>
          )}
        </h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select
            value={filter}
            onChange={e => setFilter(e.target.value)}
            style={{
              padding: '6px 12px',
              background: 'rgba(0,0,0,0.3)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font)',
              fontSize: 13,
            }}
          >
            {eventTypes.map(t => (
              <option key={t} value={t}>{t === 'all' ? 'All events' : t}</option>
            ))}
          </select>
          <button className="btn btn-ghost" onClick={clear} disabled={events.length === 0}>
            Clear
          </button>
        </div>
      </div>

      {/* Event log */}
      <div className="event-log">
        {filtered.length === 0 ? (
          <div className="empty-state">
            <h3>{events.length === 0 ? 'Waiting for events…' : 'No events match filter'}</h3>
            <p>
              {events.length === 0
                ? 'Submit a goal or run agent_loop_template.py to see live events here'
                : `${events.length} events hidden by the current filter`}
            </p>
          </div>
        ) : (
          filtered.map(evt => <EventItem key={evt.id} evt={evt} />)
        )}
      </div>
    </div>
  );
}
