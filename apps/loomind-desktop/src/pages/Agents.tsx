/**
 * Agents — Online agent registry with real-time status cards and manual registration
 */

import { useState } from 'react';
import { useAgents, AgentInfo } from '../hooks/useAgents.ts';

const ENGINE = 'http://127.0.0.1:8082';

const ROLE_META: Record<string, { color: string }> = {
  orchestrator: { color: 'purple' },
  research:     { color: 'blue' },
  coding:       { color: 'green' },
  testing:      { color: 'amber' },
  evaluation:   { color: 'cyan' },
  general:      { color: 'muted' },
};

const ALL_ROLES = Object.keys(ROLE_META);

function formatAgo(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 5) return 'just now';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function AgentCard({ agent }: { agent: AgentInfo }) {
  const meta = ROLE_META[agent.role] ?? ROLE_META.general;
  const lastSeenSec = (Date.now() - new Date(agent.last_seen).getTime()) / 1000;
  const online = lastSeenSec < 125;

  return (
    <div className="agent-card fade-in">
      <div className="agent-card-header">
        <div className="agent-card-id">
          <span className={`status-dot ${online ? 'online' : 'offline'}`} />
          <span className="agent-name">{agent.agent_id}</span>
        </div>
        <span className={`badge ${meta.color}`}>{agent.role}</span>
      </div>
      {agent.capabilities.length > 0 && (
        <div className="capability-list">
          {agent.capabilities.map(cap => (
            <span key={cap} className="capability-tag">{cap}</span>
          ))}
        </div>
      )}
      <div className="agent-card-meta">last seen {formatAgo(agent.last_seen)}</div>
    </div>
  );
}

export function Agents() {
  const { agents, loading, error, refresh } = useAgents();
  const [showForm, setShowForm] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [form, setForm] = useState({ agent_id: '', role: 'general', capabilities: '' });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const roleCounts = agents.reduce<Record<string, number>>((acc, a) => {
    acc[a.role] = (acc[a.role] ?? 0) + 1;
    return acc;
  }, {});

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    setRegistering(true);
    try {
      const resp = await fetch(`${ENGINE}/api/agents/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: form.agent_id.trim(),
          role: form.role,
          capabilities: form.capabilities.split(',').map(c => c.trim()).filter(Boolean),
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setMsg({ ok: true, text: `Agent '${form.agent_id}' registered.` });
      setForm({ agent_id: '', role: 'general', capabilities: '' });
      setShowForm(false);
      await refresh();
    } catch {
      setMsg({ ok: false, text: 'Registration failed — engine may be offline.' });
    } finally {
      setRegistering(false);
      setTimeout(() => setMsg(null), 4000);
    }
  }

  return (
    <div className="fade-in">
      <div className="page-header">
        <h2>Agents</h2>
        <p>Online agents registered with the Harness Brain — auto-refresh every 8s</p>
      </div>

      {/* Stats KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card blue">
          <div className="kpi-label">Online Agents</div>
          <div className="kpi-value">{agents.length}</div>
          <div className="kpi-sub">TTL 120s</div>
        </div>
        {Object.entries(roleCounts).map(([role, count]) => {
          const meta = ROLE_META[role] ?? ROLE_META.general;
          const cardColor = meta.color === 'muted' ? 'purple' : meta.color;
          return (
            <div key={role} className={`kpi-card ${cardColor}`}>
              <div className="kpi-label">{role}</div>
              <div className="kpi-value">{count}</div>
            </div>
          );
        })}
      </div>

      {/* Toolbar */}
      <div
        className="table-header"
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: showForm ? 'var(--radius) var(--radius) 0 0' : 'var(--radius) var(--radius) 0 0',
        }}
      >
        <h3>Active Agents</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-ghost" onClick={refresh}>↻ Refresh</button>
          <button className="btn btn-primary" onClick={() => setShowForm(s => !s)}>
            {showForm ? '✕ Cancel' : '+ Register Agent'}
          </button>
        </div>
      </div>

      {/* Register form */}
      {showForm && (
        <div className="agent-register-form">
          <form onSubmit={handleRegister}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 16 }}>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Agent ID *</label>
                <input
                  placeholder="e.g. coder-1"
                  value={form.agent_id}
                  required
                  onChange={e => setForm(f => ({ ...f, agent_id: e.target.value }))}
                />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Role</label>
                <select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}>
                  {ALL_ROLES.map(r => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Capabilities (comma-separated)</label>
                <input
                  placeholder="python, fastapi, testing"
                  value={form.capabilities}
                  onChange={e => setForm(f => ({ ...f, capabilities: e.target.value }))}
                />
              </div>
            </div>
            <button type="submit" className="btn btn-primary" disabled={registering}>
              {registering ? 'Registering…' : 'Register'}
            </button>
          </form>
        </div>
      )}

      {msg && (
        <div className={`inline-alert ${msg.ok ? 'success' : 'error'}`}>{msg.text}</div>
      )}

      {/* Agent grid */}
      {loading ? (
        <div className="agent-grid-shell">
          <div className="spinner" />
        </div>
      ) : error ? (
        <div className="agent-grid-shell">
          <div className="empty-state">
            <h3>Engine Offline</h3>
            <p>{error}</p>
          </div>
        </div>
      ) : agents.length === 0 ? (
        <div className="agent-grid-shell">
          <div className="empty-state">
            <h3>No agents online</h3>
            <p>Register an agent above or run <code>python scripts/agent_loop_template.py</code></p>
          </div>
        </div>
      ) : (
        <div className="agents-grid">
          {agents.map(a => <AgentCard key={a.agent_id} agent={a} />)}
        </div>
      )}
    </div>
  );
}
