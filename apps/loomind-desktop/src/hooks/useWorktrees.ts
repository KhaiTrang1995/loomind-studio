import { useState, useEffect, useCallback } from 'react';

const ENGINE = 'http://127.0.0.1:8082';

export interface WorktreeRecord {
  worktree_id: string;
  name: string;
  path: string;
  description: string;
  created_at: string;
  active: boolean;
}

interface WorktreesState {
  worktrees: WorktreeRecord[];
  loading: boolean;
  error: string | null;
  createWorktree: (name: string, path: string, description?: string) => Promise<WorktreeRecord | null>;
  deleteWorktree: (id: string) => Promise<void>;
  toggleActive: (id: string, active: boolean) => Promise<void>;
  refresh: () => void;
}

export function useWorktrees(): WorktreesState {
  const [worktrees, setWorktrees] = useState<WorktreeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const resp = await fetch(`${ENGINE}/api/worktrees`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setWorktrees(await resp.json());
      setError(null);
    } catch (e) {
      setError('Could not load worktrees');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const createWorktree = useCallback(async (
    name: string, path: string, description = '',
  ): Promise<WorktreeRecord | null> => {
    try {
      const resp = await fetch(`${ENGINE}/api/worktrees`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, path, description }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const record: WorktreeRecord = await resp.json();
      setWorktrees(prev => [record, ...prev]);
      return record;
    } catch {
      setError('Failed to register workspace');
      return null;
    }
  }, []);

  const deleteWorktree = useCallback(async (id: string) => {
    try {
      await fetch(`${ENGINE}/api/worktrees/${id}`, { method: 'DELETE' });
      setWorktrees(prev => prev.filter(w => w.worktree_id !== id));
    } catch {
      setError('Failed to remove workspace');
    }
  }, []);

  const toggleActive = useCallback(async (id: string, active: boolean) => {
    try {
      const resp = await fetch(`${ENGINE}/api/worktrees/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active }),
      });
      if (!resp.ok) throw new Error();
      const updated: WorktreeRecord = await resp.json();
      setWorktrees(prev => prev.map(w => w.worktree_id === id ? updated : w));
    } catch {
      setError('Failed to update workspace');
    }
  }, []);

  return { worktrees, loading, error, createWorktree, deleteWorktree, toggleActive, refresh: load };
}
