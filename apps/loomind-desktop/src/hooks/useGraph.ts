import { useState, useEffect, useCallback } from 'react';

const ENGINE = 'http://127.0.0.1:8082';

export interface GraphNode {
  id: string;
  role: string;
  capabilities: string[];
  online: boolean;
  unread_count: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: 'message' | 'goal';
  label: string;
  message_count: number;
}

export interface AgentGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface AgentMessage {
  msg_id: string;
  from_agent: string;
  to_agent: string;
  content: string;
  context: Record<string, unknown>;
  created_at: string;
  read: boolean;
}

export function useGraph(intervalMs = 5000) {
  const [graph, setGraph] = useState<AgentGraph>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchGraph = useCallback(async () => {
    try {
      const resp = await fetch(`${ENGINE}/api/agents/graph`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setGraph(await resp.json());
      setError(null);
    } catch {
      setError('Engine offline');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGraph();
    const id = setInterval(fetchGraph, intervalMs);
    return () => clearInterval(id);
  }, [fetchGraph, intervalMs]);

  async function sendMessage(
    toAgentId: string,
    fromAgent: string,
    content: string,
    context: Record<string, unknown> = {},
  ) {
    const resp = await fetch(`${ENGINE}/api/agents/${toAgentId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from_agent: fromAgent, content, context }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await fetchGraph();
    return resp.json();
  }

  async function getMessages(agentId: string, unreadOnly = false): Promise<AgentMessage[]> {
    const resp = await fetch(`${ENGINE}/api/agents/${agentId}/messages?unread_only=${unreadOnly}`);
    if (!resp.ok) return [];
    return resp.json();
  }

  return { graph, loading, error, refresh: fetchGraph, sendMessage, getMessages };
}
