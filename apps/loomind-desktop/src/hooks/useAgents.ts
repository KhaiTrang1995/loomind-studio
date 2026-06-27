import { useState, useEffect, useCallback } from 'react';

const ENGINE = 'http://127.0.0.1:8082';

export interface AgentInfo {
  agent_id: string;
  role: string;
  capabilities: string[];
  registered_at: string;
  last_seen: string;
}

interface AgentsState {
  agents: AgentInfo[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useAgents(intervalMs = 8000): AgentsState {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch(`${ENGINE}/api/agents`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: AgentInfo[] = await resp.json();
      setAgents(data);
      setError(null);
    } catch {
      setError('Engine offline');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  return { agents, loading, error, refresh };
}
