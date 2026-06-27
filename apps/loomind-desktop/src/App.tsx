/**
 * App — Root component with sidebar layout, routing, and engine startup screen
 */

import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { Dashboard } from './pages/Dashboard.tsx';
import { Experiences } from './pages/Experiences.tsx';
import { Settings } from './pages/Settings.tsx';
import { Agents } from './pages/Agents.tsx';
import { Goals } from './pages/Goals.tsx';
import { Monitor } from './pages/Monitor.tsx';
import { Graph } from './pages/Graph.tsx';
import { Terminal } from './pages/Terminal.tsx';
import { Fleet } from './pages/Fleet.tsx';
import { NexusReview } from './pages/NexusReview.tsx';
import { Worktrees } from './pages/Worktrees.tsx';
import { useEngine } from './hooks/useEngine.ts';
import { useState, useEffect } from 'react';

// ─── Engine Startup Screen ───
// Shown while engine sidecar is starting up
// PyInstaller --onefile: 20-60s first run (extracts to %TEMP%), 5-15s after
function EngineStartupScreen({ onReady }: { onReady: () => void }) {
  const [dots, setDots] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [status, setStatus] = useState('Extracting engine files...');
  const [timedOut, setTimedOut] = useState(false);

  // Animate dots
  useEffect(() => {
    const timer = setInterval(() => {
      setDots((d) => (d.length >= 3 ? '' : d + '.'));
    }, 500);
    return () => clearInterval(timer);
  }, []);

  // Track elapsed time
  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed((e) => e + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Update status messages based on realistic PyInstaller timing
  useEffect(() => {
    if (elapsed < 5) setStatus('Extracting engine files...');
    else if (elapsed < 15) setStatus('Loading Python runtime...');
    else if (elapsed < 30) setStatus('Loading AI model (first launch is slower)...');
    else if (elapsed < 60) setStatus('Starting vector database...');
    else if (elapsed < 90) setStatus('Almost ready — please wait...');
    else if (elapsed >= 120) {
      setStatus('Engine startup is taking too long');
      setTimedOut(true);
    }
  }, [elapsed]);

  // Poll engine health — use 127.0.0.1 (not localhost) for Tauri WebView compatibility
  useEffect(() => {
    const poll = setInterval(async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 2000);
      try {
        const resp = await fetch('http://127.0.0.1:8082/health', {
          signal: controller.signal,
        });
        if (resp.ok) {
          clearInterval(poll);
          setTimeout(onReady, 500);
        }
      } catch {
        // Engine not ready yet
      } finally {
        clearTimeout(timeout);
      }
    }, 2000);

    return () => clearInterval(poll);
  }, [onReady]);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        background: 'var(--bg-primary)',
        color: 'var(--text-primary)',
        fontFamily: 'Inter, system-ui, sans-serif',
      }}
    >
      {/* Logo */}
      <div
        style={{
          fontSize: '48px',
          fontWeight: 800,
          background: 'linear-gradient(135deg, var(--accent-blue), var(--accent-purple, #a855f7))',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          marginBottom: '8px',
          letterSpacing: '-1px',
        }}
      >
        Loomind
      </div>
      <div style={{ fontSize: '14px', color: 'var(--text-muted)', marginBottom: '48px' }}>
        Experience Engine
      </div>

      {/* Spinner */}
      <div
        style={{
          width: '48px',
          height: '48px',
          border: '3px solid var(--border)',
          borderTopColor: 'var(--accent-blue)',
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
          marginBottom: '24px',
        }}
      />

      {/* Status */}
      <div style={{ fontSize: '15px', color: 'var(--text-secondary)', minWidth: '240px', textAlign: 'center' }}>
        {status}{dots}
      </div>

      {/* Elapsed time */}
      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '12px' }}>
        {elapsed}s elapsed
      </div>

      {/* Tip — shown early */}
      {elapsed >= 10 && !timedOut && (
        <div
          style={{
            fontSize: '12px',
            color: 'var(--text-muted)',
            marginTop: '32px',
            padding: '12px 20px',
            background: 'var(--bg-secondary)',
            borderRadius: '8px',
            maxWidth: '400px',
            textAlign: 'center',
            lineHeight: 1.5,
          }}
        >
          💡 First launch extracts engine files and loads AI model. Subsequent launches will be much faster (~5-10s).
        </div>
      )}

      {/* Skip button — after 30s */}
      {elapsed >= 30 && !timedOut && (
        <button
          onClick={onReady}
          style={{
            marginTop: '24px',
            padding: '8px 24px',
            background: 'transparent',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            fontSize: '12px',
          }}
        >
          Skip — connect to external engine
        </button>
      )}

      {/* Timeout error — after 120s */}
      {timedOut && (
        <div
          style={{
            marginTop: '24px',
            padding: '16px 24px',
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: '8px',
            maxWidth: '420px',
            textAlign: 'center',
            lineHeight: 1.6,
          }}
        >
          <div style={{ color: '#ef4444', fontWeight: 600, marginBottom: '8px' }}>
            ⚠️ Engine failed to start
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Try starting the engine manually:<br />
            <code style={{ background: 'var(--bg-secondary)', padding: '2px 6px', borderRadius: '4px' }}>
              python -m uvicorn src.main:app --port 8082
            </code>
          </div>
          <button
            onClick={onReady}
            style={{
              marginTop: '12px',
              padding: '8px 24px',
              background: 'var(--accent-blue)',
              border: 'none',
              borderRadius: '6px',
              color: 'white',
              cursor: 'pointer',
              fontSize: '13px',
            }}
          >
            Open Dashboard Anyway
          </button>
        </div>
      )}

      {/* CSS animation */}
      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

// ─── Sidebar ───
function Sidebar() {
  const { connected } = useEngine(15000);

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="sidebar-logo">
        <h1>Loomind</h1>
        <p>Experience Engine</p>
      </div>

      {/* Navigation */}
      <nav>
        <ul className="sidebar-nav">
          <li>
            <NavLink to="/" end className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/></svg></span>Dashboard
            </NavLink>
          </li>
          <li>
            <NavLink to="/experiences" className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M8 2a4 4 0 0 1 4 4c0 1.7-.9 3.1-2.3 3.9L9.5 12h-3L6.3 9.9A4 4 0 0 1 4 6a4 4 0 0 1 4-4z"/><line x1="6" y1="13.5" x2="10" y2="13.5"/></svg></span>Experiences
            </NavLink>
          </li>
          <li>
            <NavLink to="/nexus-review" className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 4h12M2 8h8M2 12h5"/><circle cx="13" cy="11" r="2.5"/><path d="M11.8 12.2l-1.3 1.3"/></svg></span>Nexus Review
            </NavLink>
          </li>
          <li className="sidebar-section-label">Harness Brain</li>
          <li>
            <NavLink to="/agents" className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8" cy="5.5" r="2.5"/><path d="M2.5 14c0-2.8 2.5-4.5 5.5-4.5s5.5 1.7 5.5 4.5"/></svg></span>Agents
            </NavLink>
          </li>
          <li>
            <NavLink to="/goals" className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8" cy="8" r="6.5"/><circle cx="8" cy="8" r="3"/><circle cx="8" cy="8" r="1" fill="currentColor" stroke="none"/></svg></span>Goals
            </NavLink>
          </li>
          <li>
            <NavLink to="/worktrees" className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 4h3v8H2zM7 2h7v4H7zM7 8h7v6H7z"/></svg></span>Workspaces
            </NavLink>
          </li>
          <li>
            <NavLink to="/monitor" className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M1.5 10a9 9 0 0 1 13 0"/><path d="M4.5 13a5 5 0 0 1 7 0"/><circle cx="8" cy="14.5" r="1" fill="currentColor" stroke="none"/></svg></span>Monitor
            </NavLink>
          </li>
          <li>
            <NavLink to="/terminal" className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="1.5" y="2.5" width="13" height="11" rx="2"/><polyline points="4,6.5 7,9 4,11.5"/><line x1="9" y1="11.5" x2="12" y2="11.5"/></svg></span>Terminal
            </NavLink>
          </li>
          <li>
            <NavLink to="/fleet" className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8" cy="3" r="1.5"/><circle cx="3" cy="12" r="1.5"/><circle cx="13" cy="12" r="1.5"/><line x1="8" y1="4.5" x2="3.5" y2="10.5"/><line x1="8" y1="4.5" x2="12.5" y2="10.5"/><line x1="4.5" y1="12" x2="11.5" y2="12"/></svg></span>Fleet
            </NavLink>
          </li>
          <li>
            <NavLink to="/graph" className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8" cy="8" r="1.5"/><circle cx="3" cy="3" r="1.5"/><circle cx="13" cy="3" r="1.5"/><circle cx="3" cy="13" r="1.5"/><circle cx="13" cy="13" r="1.5"/><line x1="4" y1="4" x2="7" y2="7"/><line x1="12" y1="4" x2="9" y2="7"/><line x1="4" y1="12" x2="7" y2="9"/><line x1="12" y1="12" x2="9" y2="9"/></svg></span>Agent Graph
            </NavLink>
          </li>
          <li className="sidebar-section-label">System</li>
          <li>
            <NavLink to="/settings" className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8" cy="8" r="2.5"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4"/></svg></span>Settings
            </NavLink>
          </li>
        </ul>
      </nav>

      {/* Engine Status */}
      <div className="sidebar-status">
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}>
          Engine Status
        </div>
        <div style={{ display: 'flex', alignItems: 'center', fontSize: '13px' }}>
          <span className={`status-dot ${connected ? 'online' : 'offline'}`}></span>
          <span style={{ color: connected ? 'var(--accent-green)' : 'var(--accent-red)' }}>
            {connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
          127.0.0.1:8082
        </div>
      </div>
    </aside>
  );
}

// ─── Main App ───
export function App() {
  const [engineReady, setEngineReady] = useState(false);

  // On first mount, check if engine is already running
  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2000);
    fetch('http://127.0.0.1:8082/health', { signal: controller.signal })
      .then((r) => { if (r.ok) setEngineReady(true); })
      .catch(() => { /* not ready, show startup screen */ })
      .finally(() => clearTimeout(timeout));
  }, []);

  if (!engineReady) {
    return <EngineStartupScreen onReady={() => setEngineReady(true)} />;
  }

  return (
    <BrowserRouter>
      <div className="app-layout">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/experiences" element={<Experiences />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/goals" element={<Goals />} />
            <Route path="/monitor" element={<Monitor />} />
            <Route path="/terminal" element={<Terminal />} />
            <Route path="/fleet" element={<Fleet />} />
            <Route path="/nexus-review" element={<NexusReview />} />
            <Route path="/worktrees" element={<Worktrees />} />
            <Route path="/graph" element={<Graph />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
