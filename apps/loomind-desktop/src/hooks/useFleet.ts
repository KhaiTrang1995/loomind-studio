/**
 * useFleet — SSE hook for multi-CLI fleet status.
 * Subscribes to /api/stream/fleet and maintains live CLIStatusRecord[] state.
 */

import { useState, useEffect, useRef, useCallback, useTransition } from 'react';

const ENGINE = 'http://127.0.0.1:8082';

export type CLIType = 'claude' | 'grok' | 'codex' | 'agy';
export type CLIStatus = 'online' | 'busy' | 'idle' | 'offline';

export interface CLIStatusRecord {
  cli_type: CLIType;
  status: CLIStatus;
  current_task: string | null;
  current_deliberation_id: string | null;
  pid: number | null;
  tasks_completed: number;
  last_seen: string | null;
  // cumulative metrics (populated when engine tracks task artifacts)
  tokens_estimated?: number;
  lines_generated?: number;
  files_count?: number;
  avg_confidence?: number;
}

const CLI_LABELS: Record<CLIType, string> = {
  claude: 'Claude',
  grok: 'Grok',
  codex: 'Codex',
  agy: 'AGY',
};

const CLI_COLORS: Record<CLIType, string> = {
  claude: '#f97316',
  grok:   '#a855f7',
  codex:  '#3b82f6',
  agy:    '#10b981',
};

export const CLI_META = { labels: CLI_LABELS, colors: CLI_COLORS };

export interface CliLogLine {
  id: string;
  cli: string;
  level: string;
  message: string;
  timestamp: string;
  deliberation_id?: string;
}

const MAX_CLI_LOGS = 200;

export function useFleet() {
  const [fleet, setFleet] = useState<CLIStatusRecord[]>([]);
  const [connected, setConnected] = useState(false);
  const [cliLogs, setCliLogs] = useState<CliLogLine[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const [, startTransition] = useTransition();

  const updateFleet = useCallback((records: CLIStatusRecord[]) => {
    setFleet(records);
  }, []);

  const addLog = useCallback((payload: Record<string, string>) => {
    const logger: string = payload.logger ?? 'cli';
    const cli = logger.startsWith('cli.') ? logger.slice(4) : logger;
    const line: CliLogLine = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      cli,
      level: payload.level ?? 'INFO',
      message: payload.message ?? '',
      timestamp: new Date().toISOString(),
      deliberation_id: payload.deliberation_id,
    };
    // Low-priority update so log appends never block fleet card renders
    startTransition(() => {
      setCliLogs((prev) => [...prev, line].slice(-MAX_CLI_LOGS));
    });
  }, [startTransition]);

  useEffect(() => {
    // REST fetch on mount — populate immediately without waiting for SSE
    fetch(`${ENGINE}/api/agents/fleet`)
      .then((r) => r.ok ? r.json() : [])
      .then((data: CLIStatusRecord[]) => { if (data.length) updateFleet(data); })
      .catch(() => null);

    const es = new EventSource(`${ENGINE}/api/stream/fleet`);
    esRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.event === 'fleet_snapshot' || msg.event === 'fleet_status') {
          updateFleet(msg.payload as CLIStatusRecord[]);
        } else if (msg.event === 'log') {
          addLog(msg.payload ?? {});
        }
      } catch {
        // ignore malformed
      }
    };

    return () => {
      es.close();
      esRef.current = null;
      setConnected(false);
    };
  }, [updateFleet, addLog]);

  // Manual refresh
  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${ENGINE}/api/agents/fleet`);
      if (r.ok) {
        const data: CLIStatusRecord[] = await r.json();
        if (data.length) updateFleet(data);
      }
    } catch {
      // engine offline
    }
  }, [updateFleet]);

  const clearLogs = useCallback(() => setCliLogs([]), []);

  return { fleet, connected, refresh, cliLogs, clearLogs };
}
