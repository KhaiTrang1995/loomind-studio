/**
 * Experiences Page — CRUD table with search, add, delete
 */

import { useState, type FormEvent } from 'react';
import { useExperiences } from '../hooks/useExperiences.ts';

export function Experiences() {
  const { experiences, total, loading, error, refresh, create, remove, search } = useExperiences();
  const [showForm, setShowForm] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [formData, setFormData] = useState({
    title: '',
    description: '',
    category: 'pattern',
    severity: 'info',
    tags: '',
  });

  const handleSearch = (value: string) => {
    setSearchQuery(value);
    search(value);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const ok = await create({
      ...formData,
      tags: formData.tags.split(',').map(t => t.trim()).filter(Boolean),
    });
    if (ok) {
      setShowForm(false);
      setFormData({ title: '', description: '', category: 'pattern', severity: 'info', tags: '' });
    }
  };

  const handleDelete = async (id: string, title: string) => {
    if (confirm(`Delete experience "${title}"?`)) {
      await remove(id);
    }
  };

  return (
    <div className="fade-in">
      <div className="page-header">
        <h2>Experiences</h2>
        <p>Manage stored knowledge entries for the AI pipeline</p>
      </div>

      {/* Toolbar */}
      <div style={{ display: 'flex', gap: '12px', marginBottom: '20px', alignItems: 'center' }}>
        <input
          type="text"
          placeholder="Search experiences..."
          value={searchQuery}
          onChange={(e) => handleSearch(e.target.value)}
          style={{
            flex: 1,
            padding: '10px 16px',
            background: 'rgba(0,0,0,0.3)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--text-primary)',
            fontFamily: 'var(--font)',
            fontSize: '14px',
          }}
        />
        <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? '✕ Cancel' : '+ Add Experience'}
        </button>
        <button className="btn btn-ghost" onClick={refresh}>↻</button>
      </div>

      {/* Add Form */}
      {showForm && (
        <div className="table-container fade-in" style={{ marginBottom: '24px', padding: '24px' }}>
          <h3 style={{ marginBottom: '16px' }}>New Experience</h3>
          <form onSubmit={handleSubmit}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <div className="form-group">
                <label>Title</label>
                <input
                  required
                  value={formData.title}
                  onChange={(e) => setFormData(d => ({ ...d, title: e.target.value }))}
                  placeholder="e.g. Use Singleton for DB connections"
                />
              </div>
              <div className="form-group">
                <label>Tags (comma separated)</label>
                <input
                  value={formData.tags}
                  onChange={(e) => setFormData(d => ({ ...d, tags: e.target.value }))}
                  placeholder="database, singleton, pattern"
                />
              </div>
            </div>
            <div className="form-group">
              <label>Description</label>
              <textarea
                required
                rows={3}
                value={formData.description}
                onChange={(e) => setFormData(d => ({ ...d, description: e.target.value }))}
                placeholder="Detailed description of the experience..."
                style={{ resize: 'vertical' }}
              />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <div className="form-group">
                <label>Category</label>
                <select
                  value={formData.category}
                  onChange={(e) => setFormData(d => ({ ...d, category: e.target.value }))}
                >
                  <option value="pattern">Pattern</option>
                  <option value="bug">Bug</option>
                  <option value="security">Security</option>
                  <option value="performance">Performance</option>
                </select>
              </div>
              <div className="form-group">
                <label>Severity</label>
                <select
                  value={formData.severity}
                  onChange={(e) => setFormData(d => ({ ...d, severity: e.target.value }))}
                >
                  <option value="info">Info</option>
                  <option value="warning">Warning</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
              <button type="submit" className="btn btn-primary">Create Experience</button>
              <button type="button" className="btn btn-ghost" onClick={() => setShowForm(false)}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      {/* Table */}
      {error ? (
        <div className="empty-state">
          <div className="icon">⚠️</div>
          <h3>{error}</h3>
          <p>Make sure the engine is running on localhost:8082</p>
        </div>
      ) : experiences.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📭</div>
          <h3>No experiences yet</h3>
          <p>Click "+ Add Experience" to create your first knowledge entry</p>
        </div>
      ) : (
        <div className="table-container">
          <div className="table-header">
            <h3>{total} Experiences</h3>
          </div>
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Category</th>
                <th>Severity</th>
                <th>Used</th>
                <th>Score</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {experiences.map((exp) => (
                <tr key={exp.id}>
                  <td>
                    <div style={{ fontWeight: 500 }}>{exp.title}</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                      {exp.description?.slice(0, 80)}{(exp.description?.length ?? 0) > 80 ? '...' : ''}
                    </div>
                  </td>
                  <td><span className={`badge ${exp.category}`}>{exp.category}</span></td>
                  <td><span className={`badge ${exp.severity}`}>{exp.severity}</span></td>
                  <td style={{ color: 'var(--text-secondary)' }}>{exp.usage_count ?? 0}×</td>
                  <td>
                    <span style={{
                      color: (exp.feedback_score ?? 0) > 0 ? 'var(--accent-green)' :
                        (exp.feedback_score ?? 0) < 0 ? 'var(--accent-red)' : 'var(--text-muted)'
                    }}>
                      {(exp.feedback_score ?? 0) > 0 ? '+' : ''}{(exp.feedback_score ?? 0).toFixed(1)}
                    </span>
                  </td>
                  <td>
                    <button
                      className="btn btn-danger"
                      style={{ padding: '4px 12px', fontSize: '12px' }}
                      onClick={() => handleDelete(exp.id, exp.title)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
