/**
 * useDeliberations — live deliberation state via SSE + REST.
 * Subscribes to deliberation_update events from /api/stream/fleet.
 */

import { useState, useEffect, useRef, useCallback } from 'react';

const ENGINE = 'http://127.0.0.1:8082';

export type DeliberationVote = 'agree' | 'disagree' | 'counter_propose' | 'need_human' | 'abstain';
export type DeliberationStatus = 'open' | 'resolved' | 'hitl_pending' | 'cancelled';

export interface DeliberationRound {
  round_id: string;
  agent: string;
  proposal: string;
  vote: DeliberationVote;
  confidence: number;
  created_at: string;
}

export interface Deliberation {
  deliberation_id: string;
  topic: string;
  context: string;
  initiator: string;
  participants: string[];
  rounds: DeliberationRound[];
  status: DeliberationStatus;
  consensus: string | null;
  max_rounds: number;
  created_at: string;
  resolved_at: string | null;
}

export function useDeliberations() {
  const [deliberations, setDeliberations] = useState<Deliberation[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const r = await fetch(`${ENGINE}/api/deliberations`);
      if (r.ok) setDeliberations(await r.json());
    } catch {
      // engine offline
    }
  }, []);

  useEffect(() => {
    fetchAll();

    const es = new EventSource(`${ENGINE}/api/stream/fleet`);
    esRef.current = es;
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.event === 'deliberation_update') {
          // Re-fetch full list so we get rounds detail
          fetchAll();
        }
      } catch {
        // ignore
      }
    };

    return () => {
      es.close();
      esRef.current = null;
      setConnected(false);
    };
  }, [fetchAll]);

  const resolveHITL = useCallback(async (id: string, approved: boolean, consensus: string) => {
    await fetch(`${ENGINE}/api/deliberations/${id}/resolve`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved, consensus }),
    });
    await fetchAll();
  }, [fetchAll]);

  const hitlPending = deliberations.filter((d) => d.status === 'hitl_pending');
  const active = deliberations.filter((d) => d.status === 'open');
  const resolved = deliberations.filter((d) => d.status === 'resolved' || d.status === 'cancelled');

  return { deliberations, hitlPending, active, resolved, connected, resolveHITL, refresh: fetchAll };
}
