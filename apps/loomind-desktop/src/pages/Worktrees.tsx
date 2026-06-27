/**
 * Worktrees — Register and manage repository workspaces for scoped task execution.
 *
 * Each workspace is an absolute host path. When a goal is submitted with a workspace,
 * agent_loop.py runs the CLI task inside that directory (cwd=worktree_path).
 */

import { useState } from 'react';
import { useWorktrees, WorktreeRecord } from '../hooks/useWorktrees.ts';

// ── Add workspace form ────────────────────────────────────────────────────────

function AddWorkspaceForm({ onCreate }: { onCreate: (name: string, path: string, desc: string) => Promise<void> }) {
  const [name, setName] = useState('');
  const [path, setPath] = useState('');
  const [desc, setDesc] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !path.trim()) return;
    setBusy(true);
    await onCreate(name.trim(), path.trim(), desc.trim());
    setName(''); setPath(''); setDesc('');
    setBusy(false);
  };

  return (
    <form onSubmit={submit} style={{
      display: 'flex', flexDirection: 'column', gap: 12,
      padding: '20px 24px', borderRadius: 'var(--radius)',
      border: '1px solid var(--border)', background: 'var(--bg-secondary)',
    }}>
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>Register Workspace</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 10 }}>
        <input
          value={name} onChange={e => setName(e.target.value)}
          placeholder="Name (e.g. my-app)" required
          style={inputStyle}
        />
        <input
          value={path} onChange={e => setPath(e.target.value)}
          placeholder="Absolute path (e.g. D:\Projects\my-app)" required
          style={inputStyle}
        />
      </div>
      <input
        value={desc} onChange={e => setDesc(e.target.value)}
        placeholder="Description (optional)"
        style={inputStyle}
      />
      <button type="submit" disabled={busy || !name.trim() || !path.trim()} style={btnStyle}>
        {busy ? 'Registering...' : 'Register Workspace'}
      </button>
    </form>
  );
}

const inputStyle: React.CSSProperties = {
  padding: '8px 12px', borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--border)', background: 'var(--bg-primary)',
  color: 'var(--text-primary)', fontSize: 13, outline: 'none',
};

const btnStyle: React.CSSProperties = {
  alignSelf: 'flex-start', padding: '8px 20px', borderRadius: 'var(--radius-sm)',
  border: 'none', background: 'var(--accent-blue)', color: '#fff',
  fontSize: 13, fontWeight: 600, cursor: 'pointer',
};

// ── Workspace card ────────────────────────────────────────────────────────────

function WorkspaceCard({
  wt,
  goalCount,
  onDelete,
  onToggle,
}: {
  wt: WorktreeRecord;
  goalCount: number;
  onDelete: () => void;
  onToggle: () => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div style={{
      padding: '16px 20px', borderRadius: 'var(--radius)',
      border: `1px solid ${wt.active ? 'var(--border)' : 'rgba(239,68,68,0.25)'}`,
      background: wt.active ? 'var(--bg-secondary)' : 'rgba(239,68,68,0.04)',
      display: 'flex', flexDirection: 'column', gap: 8,
      opacity: wt.active ? 1 : 0.7,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <span style={{
            padding: '2px 10px', borderRadius: 100, fontSize: 11, fontWeight: 700,
            background: wt.active ? 'rgba(59,130,246,0.12)' : 'rgba(239,68,68,0.12)',
            color: wt.active ? 'var(--accent-blue)' : 'var(--accent-red)',
          }}>
            {wt.active ? 'ACTIVE' : 'DISABLED'}
          </span>
          <span style={{ fontWeight: 600, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {wt.name}
          </span>
          {goalCount > 0 && (
            <span style={{
              padding: '2px 8px', borderRadius: 100, fontSize: 11,
              background: 'var(--bg-primary)', color: 'var(--text-muted)',
              border: '1px solid var(--border)',
            }}>
              {goalCount} {goalCount === 1 ? 'goal' : 'goals'}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          <button onClick={onToggle} style={{
            padding: '4px 12px', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)', background: 'transparent',
            color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer',
          }}>
            {wt.active ? 'Disable' : 'Enable'}
          </button>
          {confirmDelete ? (
            <>
              <button onClick={onDelete} style={{
                padding: '4px 12px', borderRadius: 'var(--radius-sm)',
                border: '1px solid rgba(239,68,68,0.5)', background: 'rgba(239,68,68,0.1)',
                color: 'var(--accent-red)', fontSize: 12, cursor: 'pointer',
              }}>Confirm</button>
              <button onClick={() => setConfirmDelete(false)} style={{
                padding: '4px 12px', borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border)', background: 'transparent',
                color: 'var(--text-muted)', fontSize: 12, cursor: 'pointer',
              }}>Cancel</button>
            </>
          ) : (
            <button onClick={() => setConfirmDelete(true)} style={{
              padding: '4px 12px', borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border)', background: 'transparent',
              color: 'var(--text-muted)', fontSize: 12, cursor: 'pointer',
            }}>Remove</button>
          )}
        </div>
      </div>

      <div style={{
        fontFamily: 'monospace', fontSize: 12, padding: '6px 10px',
        borderRadius: 'var(--radius-sm)', background: 'var(--bg-primary)',
        color: 'var(--text-secondary)', border: '1px solid var(--border)',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {wt.path}
      </div>

      {wt.description && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{wt.description}</div>
      )}

      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
        Registered {new Date(wt.created_at).toLocaleDateString()}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function Worktrees() {
  const { worktrees, loading, error, createWorktree, deleteWorktree, toggleActive } = useWorktrees();

  const handleCreate = async (name: string, path: string, desc: string) => {
    await createWorktree(name, path, desc);
  };

  if (loading) {
    return (
      <div style={{ padding: '32px 40px' }}>
        <div style={{ color: 'var(--text-muted)', fontSize: 14 }}>Loading workspaces...</div>
      </div>
    );
  }

  return (
    <div style={{ padding: '32px 40px', maxWidth: 860, display: 'flex', flexDirection: 'column', gap: 28 }}>
      {/* Header */}
      <div>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: '-0.5px' }}>
          Workspaces
        </h1>
        <p style={{ marginTop: 6, fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5 }}>
          Register repository paths. Goals submitted with a workspace will run CLI tasks
          inside that directory — enabling multi-repo coordination.
        </p>
      </div>

      {error && (
        <div style={{
          padding: '10px 16px', borderRadius: 'var(--radius-sm)',
          background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
          color: 'var(--accent-red)', fontSize: 13,
        }}>
          {error}
        </div>
      )}

      <AddWorkspaceForm onCreate={handleCreate} />

      {/* Stats row */}
      <div style={{ display: 'flex', gap: 12 }}>
        {[
          { label: 'Total', value: worktrees.length },
          { label: 'Active', value: worktrees.filter(w => w.active).length },
          { label: 'Disabled', value: worktrees.filter(w => !w.active).length },
        ].map(({ label, value }) => (
          <div key={label} style={{
            flex: 1, padding: '14px 18px', borderRadius: 'var(--radius)',
            border: '1px solid var(--border)', background: 'var(--bg-secondary)',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{label}</div>
          </div>
        ))}
      </div>

      {/* Workspace list */}
      {worktrees.length === 0 ? (
        <div style={{
          padding: '40px', textAlign: 'center',
          border: '1px dashed var(--border)', borderRadius: 'var(--radius)',
          color: 'var(--text-muted)', fontSize: 14,
        }}>
          No workspaces yet. Register a repo path above to get started.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {worktrees.map(wt => (
            <WorkspaceCard
              key={wt.worktree_id}
              wt={wt}
              goalCount={0}
              onDelete={() => deleteWorktree(wt.worktree_id)}
              onToggle={() => toggleActive(wt.worktree_id, !wt.active)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
