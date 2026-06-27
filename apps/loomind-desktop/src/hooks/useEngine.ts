/**
 * useEngine — Hook quản lý kết nối với Experience Engine.
 * Cung cấp health status, stats, và auto-refresh mỗi 10 giây.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { HealthStatus, EngineStats } from '@loomind/types';

const ENGINE_URL = 'http://127.0.0.1:8082';

export interface EngineState {
  health: HealthStatus | null;
  stats: EngineStats | null;
  connected: boolean;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useEngine(refreshInterval = 10000): EngineState {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [stats, setStats] = useState<EngineStats | null>(null);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [healthRes, statsRes] = await Promise.all([
        fetch(`${ENGINE_URL}/health`),
        fetch(`${ENGINE_URL}/api/stats`),
      ]);

      if (healthRes.ok && statsRes.ok) {
        const h = await healthRes.json();
        const s = await statsRes.json();
        setHealth(h);
        setStats(s);
        setConnected(true);
        setError(null);
      } else {
        setConnected(false);
        setError('Engine returned non-OK status');
      }
    } catch {
      setConnected(false);
      setHealth(null);
      setStats(null);
      setError('Cannot reach Experience Engine');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    intervalRef.current = setInterval(refresh, refreshInterval);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [refresh, refreshInterval]);

  return { health, stats, connected, loading, error, refresh };
}
