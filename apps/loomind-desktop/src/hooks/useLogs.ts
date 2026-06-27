import { useState, useEffect, useCallback } from 'react';

const ENGINE = 'http://127.0.0.1:8082';

export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';

export interface LogLine {
  id: string;
  level: LogLevel;
  logger: string;
  message: string;
  timestamp: string;
}

interface LogState {
  lines: LogLine[];
  connected: boolean;
  clear: () => void;
}

export function useLogs(maxLines = 1000): LogState {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [connected, setConnected] = useState(false);

  const clear = useCallback(() => setLines([]), []);

  useEffect(() => {
    const es = new EventSource(`${ENGINE}/api/stream/terminal-ui`);

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data as string);
        if (data.event !== 'log') return;
        const p = data.payload ?? {};
        const line: LogLine = {
          id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
          level: (p.level ?? 'INFO') as LogLevel,
          logger: p.logger ?? 'engine',
          message: p.message ?? '',
          timestamp: data.timestamp ?? new Date().toISOString(),
        };
        setLines(prev => [...prev, line].slice(-maxLines));
      } catch {
        // ignore parse errors
      }
    };

    return () => {
      es.close();
      setConnected(false);
    };
  }, [maxLines]);

  return { lines, connected, clear };
}
