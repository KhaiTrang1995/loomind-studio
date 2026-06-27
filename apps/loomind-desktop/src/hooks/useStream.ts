import { useState, useEffect, useCallback, useRef } from 'react';

const ENGINE = 'http://127.0.0.1:8082';

export interface StreamEvent {
  id: string;
  event: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

interface StreamState {
  events: StreamEvent[];
  connected: boolean;
  clear: () => void;
}

export function useStream(agentId: string, maxEvents = 200): StreamState {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const clear = useCallback(() => setEvents([]), []);

  useEffect(() => {
    const es = new EventSource(`${ENGINE}/api/stream/${agentId}`);
    esRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data as string);
        if (data.event === 'heartbeat') return;
        const evt: StreamEvent = {
          id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
          event: data.event ?? 'unknown',
          payload: data.payload ?? {},
          timestamp: data.timestamp ?? new Date().toISOString(),
        };
        setEvents(prev => [evt, ...prev].slice(0, maxEvents));
      } catch {
        // ignore parse errors
      }
    };

    return () => {
      es.close();
      setConnected(false);
    };
  }, [agentId, maxEvents]);

  return { events, connected, clear };
}
