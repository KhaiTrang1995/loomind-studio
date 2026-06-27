/**
 * Settings Page — Engine configuration editor with real persistence.
 *
 * Loads current values from GET /api/config.
 * Saves via PATCH /api/config:
 *   - engine_log_level → hot-reloaded immediately (no restart needed)
 *   - all other fields  → saved to data/ui-settings.json (restart required)
 *
 * Phase 11: Notification settings (webhook + Telegram feature flag).
 */

import { useState, useEffect, useCallback } from 'react';
import { useEngine } from '../hooks/useEngine.ts';

const ENGINE_URL = 'http://127.0.0.1:8082';
const BRIDGE_URL = 'http://127.0.0.1:8083';

// Fields that take effect without restarting the engine
const HOT_RELOADABLE = new Set(['engine_log_level']);

interface SettingsData {
  engine: { host: string; port: string; logLevel: string };
  qdrant: { mode: string; path: string; url: string; collection: string };
  embeddings: { model: string; device: string };
  llm: { provider: string; ollamaUrl: string; ollamaModel: string; llamacppUrl: string };
  hitl: { timeoutSeconds: string; maxRetries: string };
}

interface NotifConfig {
  enabled: boolean;
  webhook_urls: string[];
  telegram_bot_token: string;
  telegram_chat_id: string;
}

interface CLIInfo {
  available: boolean;
  enabled: boolean;
  binary: string;
}

interface BridgeConfig {
  enabled_clis: string[];
  cli_timeout: number;
  poll_interval: number;
  max_iterations: number;
  engine_url: string;
  cli_paths: Record<string, string>;
  cli_status: Record<string, CLIInfo>;
}

const ALL_CLIS = ['claude', 'grok', 'agy', 'codex'];
const CLI_ROLES: Record<string, string> = {
  claude: 'coding',
  grok: 'research',
  agy: 'evaluation',
  codex: 'testing',
};

const BRIDGE_DEFAULTS: BridgeConfig = {
  enabled_clis: ['claude', 'grok', 'agy'],
  cli_timeout: 120,
  poll_interval: 15,
  max_iterations: 3,
  engine_url: 'http://localhost:8082',
  cli_paths: { claude: '', grok: '', agy: '', codex: '' },
  cli_status: {},
};

const DEFAULTS: SettingsData = {
  engine: { host: '127.0.0.1', port: '8082', logLevel: 'info' },
  qdrant: { mode: 'local', path: './data/qdrant', url: 'http://localhost:6333', collection: 'experiences' },
  embeddings: { model: 'all-MiniLM-L6-v2', device: 'cpu' },
  llm: { provider: 'ollama', ollamaUrl: 'http://localhost:11434', ollamaModel: 'llama3.2:3b', llamacppUrl: 'http://localhost:8080' },
  hitl: { timeoutSeconds: '180', maxRetries: '3' },
};

const DEFAULT_NOTIF: NotifConfig = {
  enabled: false, webhook_urls: [], telegram_bot_token: '', telegram_chat_id: '',
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function RestartBadge({ field }: { field: string }) {
  if (HOT_RELOADABLE.has(field)) {
    return (
      <span style={{ fontSize: 10, padding: '1px 6px', background: 'rgba(16,185,129,0.12)', color: 'var(--accent-green)', borderRadius: 4, fontWeight: 600, marginLeft: 6 }}>
        live
      </span>
    );
  }
  return (
    <span style={{ fontSize: 10, padding: '1px 6px', background: 'rgba(245,158,11,0.1)', color: 'var(--accent-amber)', borderRadius: 4, fontWeight: 600, marginLeft: 6 }}>
      restart
    </span>
  );
}

// ── Settings page ─────────────────────────────────────────────────────────────

export function Settings() {
  const { connected } = useEngine();
  const [settings, setSettings] = useState<SettingsData>(DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [saveStatus, setSaveStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [changed, setChanged] = useState(false);

  // Bridge / CLI Fleet state
  const [bridge, setBridge] = useState<BridgeConfig>(BRIDGE_DEFAULTS);
  const [bridgeOnline, setBridgeOnline] = useState(false);
  const [bridgeSaving, setBridgeSaving] = useState(false);
  const [bridgeStatus, setBridgeStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [bridgePaths, setBridgePaths] = useState<Record<string, string>>({});

  // Notification state
  const [notif, setNotif] = useState<NotifConfig>(DEFAULT_NOTIF);
  const [notifStatus, setNotifStatus] = useState<string | null>(null);
  const [newWebhook, setNewWebhook] = useState('');
  const [notifSaving, setNotifSaving] = useState(false);
  const [testStatus, setTestStatus] = useState<string | null>(null);
  const [testDetail, setTestDetail] = useState<string | null>(null);

  // Load config from engine on mount
  const fetchConfig = useCallback(async () => {
    try {
      const r = await fetch(`${ENGINE_URL}/api/config`);
      if (!r.ok) return;
      const data = await r.json();
      setSettings({
        engine: { host: data.engine_host ?? '127.0.0.1', port: String(data.engine_port ?? 8082), logLevel: data.engine_log_level ?? 'info' },
        qdrant: { mode: data.qdrant_mode ?? 'local', path: data.qdrant_path ?? './data/qdrant', url: data.qdrant_url ?? 'http://localhost:6333', collection: data.qdrant_collection ?? 'experiences' },
        embeddings: { model: data.embedding_model ?? 'all-MiniLM-L6-v2', device: data.embedding_device ?? 'cpu' },
        llm: { provider: data.llm_provider ?? 'ollama', ollamaUrl: data.ollama_url ?? 'http://localhost:11434', ollamaModel: data.ollama_model ?? 'llama3.2:3b', llamacppUrl: data.llamacpp_url ?? 'http://localhost:8080' },
        hitl: { timeoutSeconds: String(data.hitl_timeout_seconds ?? 180), maxRetries: String(data.max_task_retries ?? 3) },
      });
      setChanged(false);
    } catch {
      // engine offline — keep defaults
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchBridgeConfig = useCallback(async () => {
    try {
      const r = await fetch(`${BRIDGE_URL}/config`);
      if (r.ok) {
        const data: BridgeConfig = await r.json();
        setBridge(data);
        setBridgePaths(data.cli_paths ?? {});
        setBridgeOnline(true);
      } else {
        setBridgeOnline(false);
      }
    } catch {
      setBridgeOnline(false);
    }
  }, []);

  const fetchNotifConfig = useCallback(async () => {
    try {
      const r = await fetch(`${ENGINE_URL}/api/ba/notifications/config`);
      if (r.ok) setNotif(await r.json());
    } catch {}
  }, []);

  useEffect(() => {
    fetchBridgeConfig();
    if (connected) {
      fetchConfig();
      fetchNotifConfig();
    } else {
      setLoading(false);
    }
  }, [connected, fetchConfig, fetchNotifConfig, fetchBridgeConfig]);

  const update = <K extends keyof SettingsData>(section: K, key: string, value: string) => {
    setSettings(prev => ({ ...prev, [section]: { ...prev[section], [key]: value } }));
    setChanged(true);
    setSaveStatus(null);
  };

  // Build the PATCH body from current settings
  const buildPatch = () => ({
    engine_log_level: settings.engine.logLevel,
    qdrant_mode: settings.qdrant.mode,
    qdrant_path: settings.qdrant.path,
    qdrant_url: settings.qdrant.url,
    qdrant_collection: settings.qdrant.collection,
    embedding_model: settings.embeddings.model,
    embedding_device: settings.embeddings.device,
    llm_provider: settings.llm.provider,
    ollama_url: settings.llm.ollamaUrl,
    ollama_model: settings.llm.ollamaModel,
    llamacpp_url: settings.llm.llamacppUrl,
    hitl_timeout_seconds: parseInt(settings.hitl.timeoutSeconds, 10) || 180,
    max_task_retries: parseInt(settings.hitl.maxRetries, 10) || 3,
  });

  const handleSave = async () => {
    if (!connected) {
      setSaveStatus({ ok: false, msg: 'Engine offline — cannot save' });
      return;
    }
    setSaving(true);
    try {
      const r = await fetch(`${ENGINE_URL}/api/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPatch()),
      });
      if (r.ok) {
        setChanged(false);
        setSaveStatus({ ok: true, msg: 'Saved — log level active now; other settings apply on next restart' });
      } else {
        setSaveStatus({ ok: false, msg: `Save failed (HTTP ${r.status})` });
      }
    } catch {
      setSaveStatus({ ok: false, msg: 'Engine offline' });
    } finally {
      setSaving(false);
      setTimeout(() => setSaveStatus(null), 5000);
    }
  };

  // Bridge helpers
  const patchBridge = async (patch: Partial<Omit<BridgeConfig, 'cli_status'>>) => {
    setBridgeSaving(true);
    try {
      const r = await fetch(`${BRIDGE_URL}/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (r.ok) {
        const data: BridgeConfig = await r.json();
        setBridge(data);
        setBridgePaths(data.cli_paths ?? {});
        setBridgeStatus({ ok: true, msg: 'Saved' });
        setBridgeOnline(true);
      } else {
        setBridgeStatus({ ok: false, msg: `Error HTTP ${r.status}` });
      }
    } catch {
      setBridgeStatus({ ok: false, msg: 'Bridge offline' });
    } finally {
      setBridgeSaving(false);
      setTimeout(() => setBridgeStatus(null), 3000);
    }
  };

  const toggleCli = (cli: string) => {
    const next = bridge.enabled_clis.includes(cli)
      ? bridge.enabled_clis.filter(c => c !== cli)
      : [...bridge.enabled_clis, cli];
    patchBridge({ enabled_clis: next });
  };

  const savePaths = () => patchBridge({ cli_paths: bridgePaths });

  // Notification helpers
  const saveNotif = async (patch: Partial<NotifConfig>) => {
    setNotifSaving(true);
    try {
      const r = await fetch(`${ENGINE_URL}/api/ba/notifications/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (r.ok) {
        setNotif(await r.json());
        setNotifStatus('Saved');
        setTimeout(() => setNotifStatus(null), 2500);
      } else {
        setNotifStatus('Error saving');
      }
    } catch {
      setNotifStatus('Engine offline');
    } finally {
      setNotifSaving(false);
    }
  };

  const addWebhook = async () => {
    const url = newWebhook.trim();
    if (!url) return;
    await saveNotif({ webhook_urls: [...notif.webhook_urls, url] });
    setNewWebhook('');
  };

  const removeWebhook = (url: string) =>
    saveNotif({ webhook_urls: notif.webhook_urls.filter(u => u !== url) });

  const sendTestNotification = async () => {
    setTestStatus('Sending…');
    setTestDetail(null);
    try {
      const r = await fetch(`${ENGINE_URL}/api/ba/notifications/test`, { method: 'POST' });
      const data = await r.json();
      setTestStatus(r.ok && data.ok ? 'Sent ✓' : 'Failed ✗');
      setTestDetail(data.message ?? null);
    } catch {
      setTestStatus('Engine offline');
    }
    setTimeout(() => { setTestStatus(null); setTestDetail(null); }, 5000);
  };

  return (
    <div className="fade-in">
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h2>Settings</h2>
          <p>Configure the Experience Engine — changes persist to <code>data/ui-settings.json</code></p>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          {saveStatus && (
            <span style={{
              fontSize: 13, maxWidth: 360,
              color: saveStatus.ok ? 'var(--accent-green)' : 'var(--accent-red)',
            }}>
              {saveStatus.ok ? '✓' : '✗'} {saveStatus.msg}
            </span>
          )}
          {changed && !saving && (
            <span style={{ fontSize: 12, color: 'var(--accent-amber)' }}>Unsaved changes</span>
          )}
          <button
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving || !connected || loading}
          >
            {saving ? 'Saving…' : 'Save Settings'}
          </button>
        </div>
      </div>

      {!connected && (
        <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 'var(--radius)', padding: '14px 20px', marginBottom: 24, fontSize: 14, color: 'var(--accent-red)' }}>
          ⚠️ Engine is offline. Showing last-saved values — changes cannot be saved until engine reconnects.
        </div>
      )}

      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 20, display: 'flex', gap: 16 }}>
        <span>
          <span style={{ padding: '1px 6px', background: 'rgba(16,185,129,0.12)', color: 'var(--accent-green)', borderRadius: 4, fontWeight: 600, fontSize: 10 }}>live</span>
          {' '}= takes effect immediately
        </span>
        <span>
          <span style={{ padding: '1px 6px', background: 'rgba(245,158,11,0.1)', color: 'var(--accent-amber)', borderRadius: 4, fontWeight: 600, fontSize: 10 }}>restart</span>
          {' '}= saved now, applies on next engine restart
        </span>
      </div>

      <div className="settings-grid">
        {/* Engine */}
        <div className="settings-section fade-in">
          <h3>Engine</h3>
          <div className="form-group">
            <label>
              Host
              <RestartBadge field="engine_host" />
            </label>
            <input
              value={settings.engine.host}
              onChange={e => update('engine', 'host', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label>
              Port
              <RestartBadge field="engine_port" />
            </label>
            <input
              type="number"
              value={settings.engine.port}
              onChange={e => update('engine', 'port', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label>
              Log Level
              <RestartBadge field="engine_log_level" />
            </label>
            <select
              value={settings.engine.logLevel}
              onChange={e => update('engine', 'logLevel', e.target.value)}
            >
              <option value="debug">Debug</option>
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="error">Error</option>
            </select>
          </div>
        </div>

        {/* Qdrant */}
        <div className="settings-section fade-in">
          <h3>Qdrant Vector DB</h3>
          <div className="form-group">
            <label>Mode <RestartBadge field="qdrant_mode" /></label>
            <select
              value={settings.qdrant.mode}
              onChange={e => update('qdrant', 'mode', e.target.value)}
            >
              <option value="local">Local (embedded)</option>
              <option value="server">Server (Docker)</option>
            </select>
          </div>
          {settings.qdrant.mode === 'local' ? (
            <div className="form-group">
              <label>Data Path <RestartBadge field="qdrant_path" /></label>
              <input value={settings.qdrant.path} onChange={e => update('qdrant', 'path', e.target.value)} />
            </div>
          ) : (
            <div className="form-group">
              <label>Server URL <RestartBadge field="qdrant_url" /></label>
              <input value={settings.qdrant.url} onChange={e => update('qdrant', 'url', e.target.value)} />
            </div>
          )}
          <div className="form-group">
            <label>Collection <RestartBadge field="qdrant_collection" /></label>
            <input value={settings.qdrant.collection} onChange={e => update('qdrant', 'collection', e.target.value)} />
          </div>
        </div>

        {/* Embeddings */}
        <div className="settings-section fade-in">
          <h3>Embeddings</h3>
          <div className="form-group">
            <label>Model <RestartBadge field="embedding_model" /></label>
            <select
              value={settings.embeddings.model}
              onChange={e => update('embeddings', 'model', e.target.value)}
            >
              <option value="all-MiniLM-L6-v2">all-MiniLM-L6-v2 (384d, fast)</option>
              <option value="all-mpnet-base-v2">all-mpnet-base-v2 (768d, accurate)</option>
              <option value="paraphrase-MiniLM-L3-v2">paraphrase-MiniLM-L3-v2 (384d, fastest)</option>
            </select>
          </div>
          <div className="form-group">
            <label>Device <RestartBadge field="embedding_device" /></label>
            <select
              value={settings.embeddings.device}
              onChange={e => update('embeddings', 'device', e.target.value)}
            >
              <option value="cpu">CPU</option>
              <option value="cuda">CUDA (GPU)</option>
            </select>
          </div>
        </div>

        {/* LLM */}
        <div className="settings-section fade-in">
          <h3>LLM Anti-Noise Filter</h3>
          <div className="form-group">
            <label>Provider <RestartBadge field="llm_provider" /></label>
            <select
              value={settings.llm.provider}
              onChange={e => update('llm', 'provider', e.target.value)}
            >
              <option value="ollama">Ollama</option>
              <option value="llamacpp">llama.cpp</option>
            </select>
          </div>
          {settings.llm.provider === 'ollama' ? (
            <>
              <div className="form-group">
                <label>Ollama URL <RestartBadge field="ollama_url" /></label>
                <input value={settings.llm.ollamaUrl} onChange={e => update('llm', 'ollamaUrl', e.target.value)} />
              </div>
              <div className="form-group">
                <label>Model <RestartBadge field="ollama_model" /></label>
                <input value={settings.llm.ollamaModel} onChange={e => update('llm', 'ollamaModel', e.target.value)} placeholder="llama3.2:3b" />
              </div>
            </>
          ) : (
            <div className="form-group">
              <label>llama.cpp URL <RestartBadge field="llamacpp_url" /></label>
              <input value={settings.llm.llamacppUrl} onChange={e => update('llm', 'llamacppUrl', e.target.value)} />
            </div>
          )}
        </div>

        {/* Agentic Brain */}
        <div className="settings-section fade-in">
          <h3>Agentic Brain</h3>
          <div className="form-group">
            <label>HITL Timeout (seconds) <RestartBadge field="hitl_timeout_seconds" /></label>
            <input
              type="number"
              value={settings.hitl.timeoutSeconds}
              onChange={e => update('hitl', 'timeoutSeconds', e.target.value)}
              min={30} max={3600}
            />
            <span style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'block' }}>
              After this timeout, non-SECURITY HITL tasks auto-execute. SECURITY tasks always require explicit approval.
            </span>
          </div>
          <div className="form-group">
            <label>Max Task Retries <RestartBadge field="max_task_retries" /></label>
            <input
              type="number"
              value={settings.hitl.maxRetries}
              onChange={e => update('hitl', 'maxRetries', e.target.value)}
              min={1} max={10}
            />
          </div>
        </div>

        {/* CLI Fleet — Bridge config */}
        <div className="settings-section fade-in" style={{ gridColumn: '1 / -1' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div>
              <h3 style={{ margin: 0 }}>CLI Fleet</h3>
              <span style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4, display: 'block' }}>
                Bridge: <code style={{ fontSize: 11 }}>{BRIDGE_URL}</code>
                {' '}
                <span style={{
                  padding: '1px 7px', borderRadius: 10, fontSize: 10, fontWeight: 700,
                  background: bridgeOnline ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)',
                  color: bridgeOnline ? 'var(--accent-green)' : 'var(--accent-red)',
                }}>
                  {bridgeOnline ? 'online' : 'offline'}
                </span>
              </span>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              {bridgeStatus && (
                <span style={{ fontSize: 13, color: bridgeStatus.ok ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                  {bridgeStatus.ok ? '✓' : '✗'} {bridgeStatus.msg}
                </span>
              )}
              <button
                className="btn btn-ghost"
                style={{ fontSize: 12 }}
                onClick={fetchBridgeConfig}
                disabled={bridgeSaving}
              >
                Refresh
              </button>
            </div>
          </div>

          {!bridgeOnline && (
            <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 'var(--radius)', padding: '10px 16px', marginBottom: 16, fontSize: 13, color: 'var(--accent-red)' }}>
              CLI Bridge is offline. Start it with <code>python -m uvicorn main:app --port 8083</code> in <code>apps/cli-bridge/</code>.
            </div>
          )}

          {/* Per-CLI toggle cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginBottom: 20 }}>
            {ALL_CLIS.map(cli => {
              const info = bridge.cli_status?.[cli];
              const enabled = bridge.enabled_clis.includes(cli);
              const available = info?.available ?? false;
              return (
                <div key={cli} style={{
                  padding: '14px 16px', borderRadius: 'var(--radius)',
                  border: `1px solid ${enabled && available ? 'rgba(16,185,129,0.3)' : 'var(--border)'}`,
                  background: enabled && available ? 'rgba(16,185,129,0.04)' : 'var(--bg-secondary)',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <div>
                      <span style={{ fontWeight: 600, fontSize: 14 }}>{cli}</span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>{CLI_ROLES[cli]}</span>
                    </div>
                    <button
                      className={`btn ${enabled ? 'btn-primary' : 'btn-ghost'}`}
                      style={{ padding: '3px 12px', fontSize: 12, minWidth: 52 }}
                      disabled={bridgeSaving || !bridgeOnline}
                      onClick={() => toggleCli(cli)}
                    >
                      {enabled ? 'ON' : 'OFF'}
                    </button>
                  </div>
                  <div style={{ fontSize: 11, display: 'flex', gap: 8 }}>
                    <span style={{
                      padding: '1px 6px', borderRadius: 8, fontWeight: 600,
                      background: available ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)',
                      color: available ? 'var(--accent-green)' : 'var(--accent-red)',
                    }}>
                      {available ? 'found' : 'not found'}
                    </span>
                    {enabled && available && (
                      <span style={{ padding: '1px 6px', borderRadius: 8, background: 'rgba(139,92,246,0.12)', color: 'var(--accent-purple)', fontWeight: 600 }}>
                        active
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* CLI Binary Paths */}
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16 }}>
            <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: 'var(--text-secondary)' }}>
              CLI Binary Paths
              <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)', marginLeft: 8 }}>
                Leave blank to auto-detect from PATH or ~/.local/bin
              </span>
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12, marginBottom: 14 }}>
              {ALL_CLIS.map(cli => (
                <div className="form-group" key={cli} style={{ margin: 0 }}>
                  <label style={{ fontSize: 12, marginBottom: 4 }}>
                    {cli}
                    {bridge.cli_status?.[cli]?.binary && (
                      <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 400, marginLeft: 6 }}>
                        detected: {bridge.cli_status[cli].binary}
                      </span>
                    )}
                  </label>
                  <input
                    value={bridgePaths[cli] ?? ''}
                    onChange={e => setBridgePaths(prev => ({ ...prev, [cli]: e.target.value }))}
                    placeholder="auto-detect"
                    disabled={!bridgeOnline}
                    style={{ fontSize: 12 }}
                  />
                </div>
              ))}
            </div>
            <button
              className="btn btn-ghost"
              onClick={savePaths}
              disabled={bridgeSaving || !bridgeOnline}
            >
              {bridgeSaving ? 'Saving…' : 'Save Paths'}
            </button>
          </div>

          {/* Loop settings */}
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16, marginTop: 16 }}>
            <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: 'var(--text-secondary)' }}>Agent Loop Settings</p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
              <div className="form-group" style={{ margin: 0 }}>
                <label style={{ fontSize: 12 }}>Poll Interval (s)</label>
                <input
                  type="number"
                  value={bridge.poll_interval}
                  min={5} max={300}
                  disabled={!bridgeOnline || bridgeSaving}
                  onChange={e => setBridge(prev => ({ ...prev, poll_interval: +e.target.value }))}
                  onBlur={() => patchBridge({ poll_interval: bridge.poll_interval })}
                />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label style={{ fontSize: 12 }}>CLI Timeout (s)</label>
                <input
                  type="number"
                  value={bridge.cli_timeout}
                  min={10} max={600}
                  disabled={!bridgeOnline || bridgeSaving}
                  onChange={e => setBridge(prev => ({ ...prev, cli_timeout: +e.target.value }))}
                  onBlur={() => patchBridge({ cli_timeout: bridge.cli_timeout })}
                />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label style={{ fontSize: 12 }}>Max Iterations</label>
                <input
                  type="number"
                  value={bridge.max_iterations}
                  min={1} max={10}
                  disabled={!bridgeOnline || bridgeSaving}
                  onChange={e => setBridge(prev => ({ ...prev, max_iterations: +e.target.value }))}
                  onBlur={() => patchBridge({ max_iterations: bridge.max_iterations })}
                />
              </div>
            </div>
          </div>
        </div>

        {/* Notifications — Phase 11 */}
        <div className="settings-section fade-in" style={{ gridColumn: '1 / -1' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0 }}>Notifications — Agentic Brain</h3>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
              {notifStatus && (
                <span style={{ fontSize: 13, color: notifStatus.startsWith('Error') || notifStatus === 'Engine offline' ? 'var(--accent-red)' : 'var(--accent-green)' }}>
                  {notifStatus.startsWith('Error') || notifStatus === 'Engine offline' ? '✗' : '✓'} {notifStatus}
                </span>
              )}
              {testStatus && (
                <div>
                  <span style={{ fontSize: 13, color: testStatus.includes('✓') ? 'var(--accent-green)' : testStatus.includes('offline') ? 'var(--accent-red)' : 'var(--accent-purple)' }}>
                    {testStatus}
                  </span>
                  {testDetail && (
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>{testDetail}</span>
                  )}
                </div>
              )}
            </div>
          </div>

          <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20 }}>
            Receive real-time progress updates as the Agentic Brain executes tasks.
            Feature is <strong>OFF by default</strong> — enable only when webhooks are configured.
          </p>

          {/* Feature flag */}
          <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <label style={{ margin: 0, minWidth: 180 }}>Enable notifications</label>
            <button
              className={`btn ${notif.enabled ? 'btn-primary' : 'btn-ghost'}`}
              disabled={notifSaving || !connected}
              onClick={() => saveNotif({ enabled: !notif.enabled })}
              style={{ minWidth: 72 }}
            >
              {notif.enabled ? 'ON' : 'OFF'}
            </button>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {notif.enabled ? '● Notifications active' : '○ Notifications disabled'}
            </span>
          </div>

          {/* Webhook URLs */}
          <div className="form-group" style={{ marginTop: 16 }}>
            <label>Webhook URLs</label>
            {notif.webhook_urls.length === 0 ? (
              <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '6px 0' }}>No webhooks configured</p>
            ) : (
              <ul style={{ margin: '8px 0', padding: 0, listStyle: 'none' }}>
                {notif.webhook_urls.map(url => (
                  <li key={url} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                    <code style={{ flex: 1, fontSize: 12, padding: '4px 8px', background: 'var(--bg-secondary)', borderRadius: 4, wordBreak: 'break-all' }}>{url}</code>
                    <button
                      className="btn btn-danger"
                      style={{ padding: '4px 10px', fontSize: 12 }}
                      onClick={() => removeWebhook(url)}
                      disabled={notifSaving || !connected}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
              <input
                value={newWebhook}
                onChange={e => setNewWebhook(e.target.value)}
                placeholder="https://your-webhook-url.com/hook"
                onKeyDown={e => e.key === 'Enter' && addWebhook()}
                style={{ flex: 1 }}
              />
              <button
                className="btn btn-ghost"
                onClick={addWebhook}
                disabled={!newWebhook.trim() || notifSaving || !connected}
              >
                Add
              </button>
            </div>
          </div>

          {/* Telegram */}
          <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
            <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: 'var(--text-secondary)' }}>
              Telegram Bot
            </p>
            <div className="form-group">
              <label>Bot Token</label>
              <input
                type="password"
                value={notif.telegram_bot_token}
                onChange={e => setNotif(prev => ({ ...prev, telegram_bot_token: e.target.value }))}
                placeholder="1234567890:ABCdefGHijklMNOpqrSTUVwxyz"
                onBlur={() => saveNotif({ telegram_bot_token: notif.telegram_bot_token })}
              />
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                Get from @BotFather. Stored in engine memory — add TELEGRAM_BOT_TOKEN to .env for persistence.
              </span>
            </div>
            <div className="form-group">
              <label>Chat ID</label>
              <input
                value={notif.telegram_chat_id}
                onChange={e => setNotif(prev => ({ ...prev, telegram_chat_id: e.target.value }))}
                placeholder="-1001234567890"
                onBlur={() => saveNotif({ telegram_chat_id: notif.telegram_chat_id })}
              />
            </div>
          </div>

          {/* Test */}
          <div style={{ marginTop: 16 }}>
            <button
              className="btn btn-ghost"
              onClick={sendTestNotification}
              disabled={!notif.enabled || notifSaving || !connected}
            >
              Send Test Notification
            </button>
            {!notif.enabled && (
              <span style={{ marginLeft: 12, fontSize: 12, color: 'var(--text-muted)' }}>
                Enable notifications first
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
