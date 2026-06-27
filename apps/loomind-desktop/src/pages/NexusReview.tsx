/**
 * NexusReview — Display and action on Nexus-KB pending review items.
 *
 * Polls GET http://127.0.0.1:8000/api/v1/review/queue every 15 seconds.
 * Approve / Reject via POST http://127.0.0.1:8000/api/v1/review/action.
 * Requires header X-User-Role: Reviewer on every request.
 */

import { useState, useEffect, useCallback, CSSProperties } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

interface QdrantPayload {
  title?: string;
  source?: string;
  chunk_index?: number;
}

interface ReviewItemPayload {
  qdrant_payload?: QdrantPayload;
}

interface ReviewItemRecord {
  id: string;
  content: string;
  status: 'pending' | 'approved' | 'rejected' | 'modified';
  created_at: string;
  payload?: ReviewItemPayload;
}

type ReviewAction = 'approve' | 'reject';

// ── Constants ─────────────────────────────────────────────────────────────────

const NEXUS_BASE = 'http://127.0.0.1:8000';
const REVIEWER_HEADERS: HeadersInit = {
  'Content-Type': 'application/json',
  'X-User-Role': 'Reviewer',
};
const POLL_MS = 15_000;

// ── Helpers ───────────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function getTitle(item: ReviewItemRecord): string {
  return (
    item.payload?.qdrant_payload?.title ||
    item.content.slice(0, 60) + (item.content.length > 60 ? '...' : '')
  );
}

function getSource(item: ReviewItemRecord): string | null {
  return item.payload?.qdrant_payload?.source ?? null;
}

function getPreview(content: string): string {
  return content.slice(0, 120) + (content.length > 120 ? '...' : '');
}

// ── Toast ─────────────────────────────────────────────────────────────────────

interface ToastMsg {
  id: number;
  text: string;
  type: 'success' | 'error';
}

function Toast({ msgs }: { msgs: ToastMsg[] }) {
  return (
    <div style={{
      position: 'fixed',
      bottom: 24,
      right: 24,
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      zIndex: 9999,
      pointerEvents: 'none',
    }}>
      {msgs.map(m => (
        <div key={m.id} style={{
          padding: '10px 16px',
          borderRadius: 'var(--radius-sm)',
          fontSize: 13,
          fontWeight: 600,
          color: '#fff',
          background: m.type === 'success'
            ? 'rgba(16,185,129,0.92)'
            : 'rgba(239,68,68,0.92)',
          border: `1px solid ${m.type === 'success' ? 'rgba(16,185,129,0.6)' : 'rgba(239,68,68,0.6)'}`,
          boxShadow: 'var(--shadow)',
          backdropFilter: 'blur(8px)',
          transition: 'opacity 0.3s',
        }}>
          {m.text}
        </div>
      ))}
    </div>
  );
}

// ── Review item card ──────────────────────────────────────────────────────────

function ReviewCard({
  item,
  onAction,
}: {
  item: ReviewItemRecord;
  onAction: (id: string, action: ReviewAction) => Promise<void>;
}) {
  const [busy, setBusy] = useState<ReviewAction | null>(null);
  const title = getTitle(item);
  const source = getSource(item);
  const preview = getPreview(item.content);

  const handle = async (action: ReviewAction) => {
    setBusy(action);
    await onAction(item.id, action);
    setBusy(null);
  };

  const cardStyle: CSSProperties = {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: '16px 20px',
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    transition: 'border-color 0.2s',
  };

  return (
    <div style={cardStyle}>
      {/* Title row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 14,
            fontWeight: 600,
            color: 'var(--text-primary)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}>
            {title}
          </div>
          {source && (
            <div style={{
              fontSize: 11,
              color: 'var(--accent-blue)',
              marginTop: 2,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}>
              {source}
            </div>
          )}
        </div>
        <div style={{
          fontSize: 11,
          color: 'var(--text-muted)',
          whiteSpace: 'nowrap',
          flexShrink: 0,
          marginTop: 2,
        }}>
          {relativeTime(item.created_at)}
        </div>
      </div>

      {/* Content preview */}
      <div style={{
        fontSize: 12,
        color: 'var(--text-secondary)',
        lineHeight: 1.6,
        background: 'rgba(0,0,0,0.2)',
        borderRadius: 6,
        padding: '8px 12px',
        fontFamily: 'monospace',
      }}>
        {preview}
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
        <button
          onClick={() => handle('reject')}
          disabled={busy !== null}
          style={{
            padding: '6px 16px',
            fontSize: 12,
            fontWeight: 600,
            fontFamily: 'var(--font)',
            cursor: busy !== null ? 'not-allowed' : 'pointer',
            border: '1px solid rgba(239,68,68,0.4)',
            borderRadius: 'var(--radius-sm)',
            background: busy === 'reject' ? 'rgba(239,68,68,0.2)' : 'rgba(239,68,68,0.08)',
            color: 'var(--accent-red)',
            opacity: busy !== null && busy !== 'reject' ? 0.5 : 1,
            transition: 'all 0.15s',
          }}
        >
          {busy === 'reject' ? 'Rejecting...' : 'Reject'}
        </button>
        <button
          onClick={() => handle('approve')}
          disabled={busy !== null}
          style={{
            padding: '6px 16px',
            fontSize: 12,
            fontWeight: 600,
            fontFamily: 'var(--font)',
            cursor: busy !== null ? 'not-allowed' : 'pointer',
            border: '1px solid rgba(16,185,129,0.4)',
            borderRadius: 'var(--radius-sm)',
            background: busy === 'approve' ? 'rgba(16,185,129,0.25)' : 'rgba(16,185,129,0.1)',
            color: 'var(--accent-green)',
            opacity: busy !== null && busy !== 'approve' ? 0.5 : 1,
            transition: 'all 0.15s',
          }}
        >
          {busy === 'approve' ? 'Approving...' : 'Approve'}
        </button>
      </div>
    </div>
  );
}

// ── NexusReview page ──────────────────────────────────────────────────────────

export function NexusReview() {
  const [items, setItems] = useState<ReviewItemRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [toasts, setToasts] = useState<ToastMsg[]>([]);
  let toastCounter = 0;

  // ── Fetch queue ──

  const fetchQueue = useCallback(async () => {
    try {
      const res = await fetch(
        `${NEXUS_BASE}/api/v1/review/queue?limit=50&offset=0`,
        { headers: REVIEWER_HEADERS },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: ReviewItemRecord[] = await res.json();
      setItems(data.filter(i => i.status === 'pending'));
      setConnected(true);
    } catch {
      setConnected(false);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load + polling
  useEffect(() => {
    fetchQueue();
    const id = setInterval(fetchQueue, POLL_MS);
    return () => clearInterval(id);
  }, [fetchQueue]);

  // ── Toast helpers ──

  const pushToast = (text: string, type: 'success' | 'error') => {
    const id = ++toastCounter;
    setToasts(prev => [...prev, { id, text, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 2500);
  };

  // ── Action handler ──

  const handleAction = useCallback(
    async (itemId: string, action: ReviewAction) => {
      // Optimistic removal
      setItems(prev => prev.filter(i => i.id !== itemId));
      try {
        const res = await fetch(`${NEXUS_BASE}/api/v1/review/action`, {
          method: 'POST',
          headers: REVIEWER_HEADERS,
          body: JSON.stringify({ item_id: itemId, action }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        pushToast(action === 'approve' ? 'Approved' : 'Rejected', 'success');
      } catch {
        // Restore on failure
        pushToast('Action failed — item restored', 'error');
        fetchQueue();
      }
    },
    [fetchQueue],
  );

  // ── Derived state ──

  const pendingCount = items.length;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="fade-in">
      {/* Page header */}
      <div className="page-header">
        <h2>Nexus Review</h2>
        <p>Review and action pending knowledge-base items from Nexus-KB at :8000</p>
      </div>

      {/* KPI chips */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 24, flexWrap: 'wrap' }}>
        {/* Pending count chip */}
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 14px',
          borderRadius: 100,
          background: pendingCount > 0 ? 'rgba(245,158,11,0.1)' : 'rgba(16,185,129,0.08)',
          border: `1px solid ${pendingCount > 0 ? 'rgba(245,158,11,0.35)' : 'rgba(16,185,129,0.3)'}`,
        }}>
          <span style={{
            fontSize: 18,
            fontWeight: 700,
            color: pendingCount > 0 ? 'var(--accent-amber)' : 'var(--accent-green)',
            fontVariantNumeric: 'tabular-nums',
            lineHeight: 1,
          }}>
            {loading ? '—' : pendingCount}
          </span>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}>
            {pendingCount === 1 ? 'pending item' : 'pending items'}
          </span>
        </div>

        {/* Nexus-KB label chip */}
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 14px',
          borderRadius: 100,
          background: 'rgba(59,130,246,0.08)',
          border: '1px solid rgba(59,130,246,0.25)',
        }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent-blue)', letterSpacing: '0.04em' }}>
            Nexus-KB
          </span>
        </div>

        {/* Connection status dot */}
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 14px',
          borderRadius: 100,
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
        }}>
          <span style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            display: 'inline-block',
            background: connected === null
              ? 'var(--text-muted)'
              : connected
                ? 'var(--accent-green)'
                : 'var(--accent-red)',
            boxShadow: connected
              ? '0 0 6px rgba(16,185,129,0.6)'
              : connected === false
                ? '0 0 6px rgba(239,68,68,0.5)'
                : 'none',
          }} />
          <span style={{
            fontSize: 12,
            color: connected === null
              ? 'var(--text-muted)'
              : connected
                ? 'var(--accent-green)'
                : 'var(--accent-red)',
            fontWeight: 500,
          }}>
            {connected === null ? 'Connecting...' : connected ? 'Online' : 'Offline'}
          </span>
        </div>

        {/* Poll interval note */}
        <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>
          polling every 15s
        </span>
      </div>

      {/* Loading skeletons */}
      {loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[0, 1, 2].map(i => (
            <div key={i} className="skeleton" style={{ height: 120, borderRadius: 'var(--radius)' }} />
          ))}
        </div>
      )}

      {/* Offline error state */}
      {!loading && connected === false && (
        <div style={{
          padding: '32px 24px',
          borderRadius: 'var(--radius)',
          background: 'rgba(239,68,68,0.07)',
          border: '1px solid rgba(239,68,68,0.25)',
          textAlign: 'center',
        }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--accent-red)', marginBottom: 8 }}>
            Nexus-KB offline at :8000
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20 }}>
            Could not reach http://127.0.0.1:8000 — ensure the Nexus-KB service is running.
          </div>
          <button
            onClick={() => { setLoading(true); fetchQueue(); }}
            style={{
              padding: '8px 20px',
              fontSize: 13,
              fontWeight: 600,
              fontFamily: 'var(--font)',
              cursor: 'pointer',
              border: '1px solid rgba(239,68,68,0.4)',
              borderRadius: 'var(--radius-sm)',
              background: 'rgba(239,68,68,0.12)',
              color: 'var(--accent-red)',
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* Empty state */}
      {!loading && connected === true && items.length === 0 && (
        <div
          className="empty-state"
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
          }}
        >
          <h3>All caught up</h3>
          <p>No pending reviews — check back soon or wait for the next poll.</p>
        </div>
      )}

      {/* Review items list */}
      {!loading && connected === true && items.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {items.map(item => (
            <ReviewCard
              key={item.id}
              item={item}
              onAction={handleAction}
            />
          ))}
        </div>
      )}

      {/* Toasts */}
      <Toast msgs={toasts} />
    </div>
  );
}
