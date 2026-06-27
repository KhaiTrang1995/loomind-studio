/**
 * useExperiences — Hook CRUD cho experiences.
 * Gọi API trực tiếp (không qua SDK để tránh axios bundle size).
 */

import { useState, useEffect, useCallback } from 'react';
import type { Experience } from '@loomind/types';

const ENGINE_URL = 'http://localhost:8082';

export interface ExperiencesState {
  experiences: Experience[];
  total: number;
  loading: boolean;
  error: string | null;
  refresh: () => void;
  create: (data: CreateData) => Promise<boolean>;
  remove: (id: string) => Promise<boolean>;
  search: (query: string) => Promise<void>;
}

interface CreateData {
  title: string;
  description: string;
  category: string;
  severity: string;
  tags: string[];
}

export function useExperiences(): ExperiencesState {
  const [experiences, setExperiences] = useState<Experience[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${ENGINE_URL}/api/experiences?limit=100`);
      if (res.ok) {
        const data = await res.json();
        setExperiences(data.items || []);
        setTotal(data.total || 0);
        setError(null);
      } else {
        setError('Failed to load experiences');
      }
    } catch {
      setError('Cannot reach engine');
    } finally {
      setLoading(false);
    }
  }, []);

  const create = useCallback(async (data: CreateData): Promise<boolean> => {
    try {
      const res = await fetch(`${ENGINE_URL}/api/experiences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (res.ok) {
        await refresh();
        return true;
      }
    } catch { /* ignore */ }
    return false;
  }, [refresh]);

  const remove = useCallback(async (id: string): Promise<boolean> => {
    try {
      const res = await fetch(`${ENGINE_URL}/api/experiences/${id}`, { method: 'DELETE' });
      if (res.ok) {
        await refresh();
        return true;
      }
    } catch { /* ignore */ }
    return false;
  }, [refresh]);

  const search = useCallback(async (query: string): Promise<void> => {
    if (!query.trim()) {
      await refresh();
      return;
    }
    try {
      setLoading(true);
      const res = await fetch(`${ENGINE_URL}/api/experiences/search?query=${encodeURIComponent(query)}`, {
        method: 'POST',
      });
      if (res.ok) {
        const data = await res.json();
        setExperiences(data || []);
        setTotal(data?.length || 0);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [refresh]);

  useEffect(() => { refresh(); }, [refresh]);

  return { experiences, total, loading, error, refresh, create, remove, search };
}
