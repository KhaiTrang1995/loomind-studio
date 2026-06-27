/**
 * Terminal — Real-time engine log viewer.
 *
 * Subscribes to /api/stream/terminal-ui and renders live Python log output
 * from every engine component with level colours, module name, and auto-scroll.
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { useLogs, LogLevel, LogLine } from '../hooks/useLogs.ts';

// ── Level styling ─────────────────────────────────────────────────────────────

const LEVEL_COLOR: Record<LogLevel, string> = {
  DEBUG:    '#4b5563',
  INFO:     '#10b981',
  WARNING:  '#f59e0b',
  ERROR:    '#ef4444',
  CRITICAL: '#ef4444',
};

const LEVEL_BG: Record<LogLevel, string> = {
  DEBUG:    'transparent',
  INFO:     'transparent',
  WARNING:  'rgba(245,158,11,0.05)',
  ERROR:    'rgba(239,68,68,0.06)',
  CRITICAL: 'rgba(239,68,68,0.14)',
};

const LEVELS: LogLevel[] = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];
const LEVEL_RANK: Record<LogLevel, number> = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 4 };

function shortLogger(name: string): string {
  const parts = name.split('.');
  return parts[parts.length - 1] ?? name;
}

// ── Log row ───────────────────────────────────────────────────────────────────

function LogRow({ line }: { line: LogLine }) {
  const time = new Date(line.timestamp).toLocaleTimeString('en-GB', { hour12: false });

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '76px 72px 148px 1fr',
        gap: 0,
        padding: '1px 0',
        background: LEVEL_BG[line.level],
        fontFamily: "'JetBrains Mono','Fira Code','Cascadia Code','Consolas',monospace",
        fontSize: 12,
        lineHeight: '18px',
      }}
    >
      <span style={{ color: '#374151', paddingLeft: 12 }}>{time}</span>
      <span style={{ color: LEVEL_COLOR[line.level], fontWeight: 700 }}>{line.level.padEnd(8)}</span>
      <span
        style={{
          color: '#06b6d4',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          paddingRight: 8,
        }}
        title={line.logger}
      >
        {shortLogger(line.logger)}
      </span>
      <span
        style={{
          color: line.level === 'ERROR' || line.level === 'CRITICAL' ? '#fca5a5' : '#d1d5db',
          paddingRight: 12,
          wordBreak: 'break-word',
          whiteSpace: 'pre-wrap',
        }}
      >
        {line.message}
      </span>
    </div>
  );
}

// ── Terminal page ─────────────────────────────────────────────────────────────

export function Terminal() {
  const { lines, connected, clear } = useLogs(1000);
  const [minLevel, setMinLevel] = useState<LogLevel>('INFO');
  const [loggerFilter, setLoggerFilter] = useState('');
  const [paused, setPaused] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll unless user has scrolled up
  useEffect(() => {
    if (!paused) {
      bottomRef.current?.scrollIntoView({ behavior: 'auto' });
    }
  }, [lines, paused]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setPaused(!atBottom);
  }, []);

  const resumeScroll = useCallback(() => {
    setPaused(false);
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 10);
  }, []);

  const filtered = lines.filter(l => {
    if (LEVEL_RANK[l.level] < LEVEL_RANK[minLevel]) return false;
    if (loggerFilter && !l.logger.toLowerCase().includes(loggerFilter.toLowerCase())) return false;
    return true;
  });

  // Unique short module names for quick-filter chips (top 10 most active)
  const loggerCounts = lines.reduce<Record<string, number>>((acc, l) => {
    const s = shortLogger(l.logger);
    acc[s] = (acc[s] ?? 0) + 1;
    return acc;
  }, {});
  const topLoggers = Object.entries(loggerCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([name]) => name);

  return (
    <div
      className="fade-in"
      style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 64px)', gap: 0 }}
    >
      {/* Header */}
      <div className="page-header" style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h2>Terminal</h2>
            <p>Real-time log output from every engine component — SSE live stream</p>
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '8px 16px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            <span className={`status-dot ${connected ? 'online' : 'offline'}`} />
            <span
              style={{
                fontSize: 13,
                color: connected ? 'var(--accent-green)' : 'var(--accent-red)',
                fontWeight: 600,
                fontFamily: "'JetBrains Mono',monospace",
              }}
            >
              {connected ? 'live' : 'connecting…'}
            </span>
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          marginBottom: 10,
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        {/* Level filter */}
        <select
          value={minLevel}
          onChange={e => setMinLevel(e.target.value as LogLevel)}
          style={{
            padding: '5px 10px',
            background: 'rgba(0,0,0,0.4)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--text-primary)',
            fontFamily: "'JetBrains Mono',monospace",
            fontSize: 12,
          }}
        >
          {LEVELS.map(l => (
            <option key={l} value={l} style={{ color: LEVEL_COLOR[l] }}>
              {l}+
            </option>
          ))}
        </select>

        {/* Module filter */}
        <input
          type="text"
          placeholder="filter module..."
          value={loggerFilter}
          onChange={e => setLoggerFilter(e.target.value)}
          style={{
            padding: '5px 10px',
            background: 'rgba(0,0,0,0.4)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--text-primary)',
            fontFamily: "'JetBrains Mono',monospace",
            fontSize: 12,
            width: 160,
          }}
        />

        {/* Quick-filter module chips */}
        {topLoggers.map(name => (
          <button
            key={name}
            onClick={() => setLoggerFilter(f => f === name ? '' : name)}
            style={{
              padding: '2px 8px',
              background: 'transparent',
              border: `1px solid ${loggerFilter === name ? 'var(--accent-cyan)' : 'var(--border)'}`,
              borderRadius: 100,
              color: loggerFilter === name ? 'var(--accent-cyan)' : '#6b7280',
              cursor: 'pointer',
              fontFamily: "'JetBrains Mono',monospace",
              fontSize: 11,
              whiteSpace: 'nowrap',
            }}
          >
            {name}
          </button>
        ))}

        {/* Right controls */}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          {paused && (
            <button
              onClick={resumeScroll}
              style={{
                padding: '4px 12px',
                background: 'rgba(245,158,11,0.08)',
                border: '1px solid rgba(245,158,11,0.4)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--accent-amber)',
                cursor: 'pointer',
                fontSize: 12,
                fontFamily: 'var(--font)',
              }}
            >
              ↓ Resume scroll
            </button>
          )}
          <span
            style={{
              fontSize: 11,
              color: 'var(--text-muted)',
              fontFamily: "'JetBrains Mono',monospace",
            }}
          >
            {filtered.length}/{lines.length} lines
          </span>
          <button
            className="btn btn-ghost"
            style={{ fontSize: 12 }}
            onClick={clear}
            disabled={lines.length === 0}
          >
            Clear
          </button>
        </div>
      </div>

      {/* Terminal window */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{
          flex: 1,
          background: '#060a0f',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 'var(--radius)',
          overflow: 'auto',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Terminal chrome bar */}
        <div
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 10,
            background: '#0d1117',
            borderBottom: '1px solid rgba(255,255,255,0.06)',
            padding: '7px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: 7,
            flexShrink: 0,
          }}
        >
          <span style={{ width: 11, height: 11, borderRadius: '50%', background: '#ef4444', display: 'inline-block', opacity: 0.8 }} />
          <span style={{ width: 11, height: 11, borderRadius: '50%', background: '#f59e0b', display: 'inline-block', opacity: 0.8 }} />
          <span style={{ width: 11, height: 11, borderRadius: '50%', background: '#10b981', display: 'inline-block', opacity: 0.8 }} />
          <span
            style={{
              fontSize: 11,
              color: '#4b5563',
              marginLeft: 8,
              fontFamily: "'JetBrains Mono',monospace",
            }}
          >
            loomind-engine — live log
          </span>
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 11,
              color: connected ? '#10b981' : '#6b7280',
              fontFamily: "'JetBrains Mono',monospace",
            }}
          >
            {connected ? '● connected' : '○ connecting'}
          </span>
        </div>

        {/* Column header */}
        {lines.length > 0 && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '76px 72px 148px 1fr',
              padding: '4px 0 4px 0',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
              fontFamily: "'JetBrains Mono',monospace",
              fontSize: 10,
              color: '#374151',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              background: '#060a0f',
            }}
          >
            <span style={{ paddingLeft: 12 }}>TIME</span>
            <span>LEVEL</span>
            <span>MODULE</span>
            <span>MESSAGE</span>
          </div>
        )}

        {/* Log lines */}
        <div style={{ flex: 1 }}>
          {filtered.length === 0 ? (
            <div
              style={{
                padding: '48px 24px',
                textAlign: 'center',
                fontFamily: "'JetBrains Mono',monospace",
                fontSize: 13,
                color: '#374151',
              }}
            >
              {lines.length === 0 ? (
                <>
                  <div style={{ marginBottom: 8, color: '#10b981' }}>$ waiting for engine output...</div>
                  <div>Submit a goal or run the engine to see live logs here.</div>
                </>
              ) : (
                <div>No lines match current filter.</div>
              )}
            </div>
          ) : (
            filtered.map(line => <LogRow key={line.id} line={line} />)
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
