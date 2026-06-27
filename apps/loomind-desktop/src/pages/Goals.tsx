/**
 * Goals — Submit goals, visualize BA Agent analysis, and manage the agent pipeline.
 *
 * Two submission modes:
 *  • Quick Submit  → POST /api/goals (fixed Research→Code→Test→Evaluate pipeline)
 *  • BA Analyze    → POST /api/ba/analyze (LLM decomposition → User Stories → Fibonacci SP)
 *
 * Phase 11 features: HITL approval, resume-from-checkpoint, mode badges, story points.
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import {
  useGoals,
  GoalRecord,
  TaskRecord,
  TaskMode,
  BAAnalysisResult,
  UserStory,
} from '../hooks/useGoals.ts';
import { useWorktrees, WorktreeRecord } from '../hooks/useWorktrees.ts';

const ENGINE = 'http://127.0.0.1:8082';
const BRIDGE = 'http://127.0.0.1:8083';

// ── Status helpers ────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  pending:      'var(--text-muted)',
  claimed:      'var(--accent-blue)',
  in_progress:  'var(--accent-blue)',
  hitl_pending: 'var(--accent-amber)',
  interrupted:  'var(--accent-purple)',
  verifying:    'var(--accent-cyan)',
  completed:    'var(--accent-green)',
  failed:       'var(--accent-red)',
};

const STATUS_BG: Record<string, string> = {
  pending:      'var(--bg-secondary)',
  claimed:      'rgba(59,130,246,0.08)',
  in_progress:  'rgba(59,130,246,0.08)',
  hitl_pending: 'rgba(245,158,11,0.1)',
  interrupted:  'rgba(139,92,246,0.08)',
  verifying:    'rgba(6,182,212,0.08)',
  completed:    'rgba(16,185,129,0.08)',
  failed:       'rgba(239,68,68,0.08)',
};

const STATUS_BORDER: Record<string, string> = {
  pending:      'var(--border)',
  claimed:      'rgba(59,130,246,0.4)',
  in_progress:  'rgba(59,130,246,0.4)',
  hitl_pending: 'rgba(245,158,11,0.45)',
  interrupted:  'rgba(139,92,246,0.4)',
  verifying:    'rgba(6,182,212,0.4)',
  completed:    'rgba(16,185,129,0.4)',
  failed:       'rgba(239,68,68,0.4)',
};

function statusLabel(s: string) {
  const map: Record<string, string> = {
    pending: 'Pending', claimed: '⟳ Running', in_progress: '⟳ Running',
    hitl_pending: '⏸ Awaiting Approval', interrupted: '⚡ Interrupted',
    verifying: '⟳ Verifying', completed: '✓ Done', failed: '✗ Failed',
  };
  return map[s] ?? s;
}

// ── Mode badge ────────────────────────────────────────────────────────────────

function ModeBadge({ mode }: { mode: TaskMode | string | null }) {
  if (!mode) return null;
  const config: Record<string, { color: string; bg: string; label: string }> = {
    AUTO:     { color: 'var(--accent-green)',  bg: 'rgba(16,185,129,0.12)',  label: 'AUTO' },
    HITL:     { color: 'var(--accent-amber)',  bg: 'rgba(245,158,11,0.12)',  label: 'HITL' },
    SECURITY: { color: 'var(--accent-red)',    bg: 'rgba(239,68,68,0.12)',   label: 'SECURITY' },
  };
  const c = config[mode] ?? config.AUTO;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      padding: '1px 7px', borderRadius: 100,
      fontSize: 10, fontWeight: 700, letterSpacing: '0.06em',
      color: c.color, background: c.bg,
    }}>
      {c.label}
    </span>
  );
}

// ── HITL countdown ────────────────────────────────────────────────────────────

function calcRemaining(deadline: string) {
  return Math.max(0, Math.round((new Date(deadline).getTime() - Date.now()) / 1000));
}

function HITLCountdown({ deadline }: { deadline: string | null }) {
  const [remaining, setRemaining] = useState(() => deadline ? calcRemaining(deadline) : 0);

  useEffect(() => {
    if (!deadline) return;
    setRemaining(calcRemaining(deadline));
    const id = setInterval(() => setRemaining(calcRemaining(deadline)), 1000);
    return () => clearInterval(id);
  }, [deadline]);

  if (!deadline) return null;
  const isExpired = remaining === 0;
  const pct = Math.min(100, Math.max(0, (remaining / 180) * 100));
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      fontSize: 11, fontVariantNumeric: 'tabular-nums',
      color: isExpired || remaining < 30 ? 'var(--accent-red)' : 'var(--accent-amber)',
    }}>
      {isExpired ? '⏰ Expired — auto-proceed' : `⏱ ${remaining}s`}
      {!isExpired && (
        <span style={{
          display: 'inline-block', width: 48, height: 3,
          background: 'rgba(255,255,255,0.12)', borderRadius: 2, overflow: 'hidden',
        }}>
          <span style={{
            display: 'block', height: '100%', borderRadius: 2,
            width: `${pct}%`,
            background: remaining < 30 ? 'var(--accent-red)' : 'var(--accent-amber)',
            transition: 'width 1s linear',
          }} />
        </span>
      )}
    </span>
  );
}

// ── Workflow step (flexible — handles all Phase 11 statuses) ──────────────────

function WorkflowStep({ task, label }: { task: TaskRecord | undefined; label: string }) {
  const status = task?.status ?? 'pending';
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: '8px 14px', borderRadius: 'var(--radius-sm)',
      border: `1px solid ${STATUS_BORDER[status] ?? 'var(--border)'}`,
      background: STATUS_BG[status] ?? 'var(--bg-secondary)',
      minWidth: 96,
    }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>
        {label}
      </div>
      <div style={{ fontSize: 11, marginTop: 3, color: STATUS_COLOR[status] ?? 'var(--text-muted)' }}>
        {statusLabel(status)}
      </div>
      {task?.assigned_to && (
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>
          👤 {task.assigned_to}
        </div>
      )}
      {task?.story_points ? (
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
          {task.story_points} SP
        </div>
      ) : null}
    </div>
  );
}

// ── Pipeline (quick mode — fixed 4 stages) ────────────────────────────────────

const QUICK_STAGES = ['research', 'code', 'test', 'evaluate'] as const;
const QUICK_LABELS: Record<string, string> = {
  research: 'Research', code: 'Code', test: 'Test', evaluate: 'Evaluate',
};

function QuickPipeline({ tasks }: { tasks: TaskRecord[] }) {
  const byType = Object.fromEntries(tasks.map(t => [t.task_type, t]));
  return (
    <div className="workflow-pipeline">
      {QUICK_STAGES.map((type, idx) => (
        <div key={type} style={{ display: 'flex', alignItems: 'center' }}>
          <WorkflowStep task={byType[type]} label={QUICK_LABELS[type]} />
          {idx < QUICK_STAGES.length - 1 && (
            <div className="workflow-arrow">→</div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Pipeline (BA mode — dynamic tasks sorted by story_points DESC) ────────────

function BAPipeline({ tasks }: { tasks: TaskRecord[] }) {
  const sorted = [...tasks].sort((a, b) => b.story_points - a.story_points);
  return (
    <div className="workflow-pipeline" style={{ flexWrap: 'wrap', gap: 8, padding: '12px 16px' }}>
      {sorted.map((task, idx) => (
        <div key={task.task_id} style={{ display: 'flex', alignItems: 'center' }}>
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            padding: '8px 12px', borderRadius: 'var(--radius-sm)',
            border: `1px solid ${STATUS_BORDER[task.status] ?? 'var(--border)'}`,
            background: STATUS_BG[task.status] ?? 'var(--bg-secondary)',
            minWidth: 104,
          }}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 2 }}>
              <ModeBadge mode={task.mode} />
              <span style={{ fontSize: 10, color: 'var(--accent-purple)', fontWeight: 600 }}>
                {task.story_points}SP
              </span>
            </div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textAlign: 'center' }}>
              {task.task_type}
            </div>
            <div style={{ fontSize: 10, marginTop: 3, color: STATUS_COLOR[task.status] ?? 'var(--text-muted)' }}>
              {statusLabel(task.status)}
            </div>
          </div>
          {idx < sorted.length - 1 && <div className="workflow-arrow">→</div>}
        </div>
      ))}
    </div>
  );
}

// ── HITL approval panel ───────────────────────────────────────────────────────

function HITLPanel({
  task, goalId, onApprove,
}: {
  task: TaskRecord;
  goalId: string;
  onApprove: (approved: boolean, comment: string) => void;
}) {
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);

  const handle = async (approved: boolean) => {
    setBusy(true);
    onApprove(approved, comment);
    setBusy(false);
  };

  const isSecurity = task.mode === 'SECURITY';

  return (
    <div style={{
      margin: '8px 0', padding: '12px 16px',
      background: isSecurity ? 'rgba(239,68,68,0.07)' : 'rgba(245,158,11,0.07)',
      border: `1px solid ${isSecurity ? 'rgba(239,68,68,0.3)' : 'rgba(245,158,11,0.3)'}`,
      borderRadius: 'var(--radius-sm)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <ModeBadge mode={task.mode} />
        <span style={{
          fontSize: 13, fontWeight: 600,
          color: isSecurity ? 'var(--accent-red)' : 'var(--accent-amber)',
        }}>
          {isSecurity
            ? 'SECURITY task — explicit human approval required'
            : 'Human approval required before execution'}
        </span>
        <HITLCountdown deadline={task.hitl_deadline} />
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 10 }}>
        {task.description}
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          value={comment}
          onChange={e => setComment(e.target.value)}
          placeholder="Optional comment..."
          style={{
            flex: 1, padding: '6px 10px', fontSize: 12,
            background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
            fontFamily: 'var(--font)',
          }}
        />
        <button
          className="btn btn-primary"
          style={{ padding: '6px 16px', fontSize: 12, background: 'var(--gradient-green)' }}
          onClick={() => handle(true)}
          disabled={busy}
        >
          Approve ✓
        </button>
        <button
          className="btn btn-danger"
          style={{ padding: '6px 14px', fontSize: 12 }}
          onClick={() => handle(false)}
          disabled={busy}
        >
          Reject ✗
        </button>
      </div>
    </div>
  );
}

// ── Task detail row ───────────────────────────────────────────────────────────

function TaskRow({
  task, goalId, onApprove, onResume,
}: {
  task: TaskRecord;
  goalId: string;
  onApprove: (taskId: string, approved: boolean, comment: string) => void;
  onResume: (taskId: string) => void;
}) {
  const [expanded, setExpanded] = useState(task.status === 'hitl_pending');

  return (
    <div>
      <div
        className="task-detail-row"
        style={{ cursor: 'pointer' }}
        onClick={() => setExpanded(e => !e)}
      >
        {/* Type */}
        <span className={`badge ${task.status === 'completed' ? 'green' : task.status === 'failed' ? 'critical' : task.status === 'hitl_pending' ? 'amber' : 'blue'}`}
          style={{ minWidth: 72 }}>
          {task.task_type}
        </span>

        {/* Mode */}
        <ModeBadge mode={task.mode} />

        {/* Story points */}
        {task.story_points > 0 && (
          <span style={{ fontSize: 11, color: 'var(--accent-purple)', fontWeight: 700, minWidth: 30 }}>
            {task.story_points}SP
          </span>
        )}

        {/* Description */}
        <span style={{ flex: 1, fontSize: 12, color: 'var(--text-secondary)' }}>
          {task.description}
        </span>

        {/* Agent */}
        {task.assigned_to && (
          <span className="capability-tag">👤 {task.assigned_to}</span>
        )}

        {/* Status color dot */}
        <span style={{ fontSize: 11, color: STATUS_COLOR[task.status], fontWeight: 600 }}>
          {statusLabel(task.status)}
        </span>

        {/* HITL countdown */}
        {task.status === 'hitl_pending' && <HITLCountdown deadline={task.hitl_deadline} />}

        <span style={{ color: 'var(--text-muted)', fontSize: 14 }}>{expanded ? '▾' : '▸'}</span>
      </div>

      {expanded && (
        <div style={{ paddingLeft: 16, paddingBottom: 8 }}>
          {/* HITL approval panel */}
          {task.status === 'hitl_pending' && (
            <HITLPanel
              task={task}
              goalId={goalId}
              onApprove={(approved, comment) => onApprove(task.task_id, approved, comment)}
            />
          )}

          {/* Checkpoint + resume */}
          {task.status === 'interrupted' && (
            <div style={{
              margin: '8px 0', padding: '10px 14px',
              background: 'rgba(139,92,246,0.07)',
              border: '1px solid rgba(139,92,246,0.3)',
              borderRadius: 'var(--radius-sm)',
            }}>
              <div style={{ fontSize: 12, color: 'var(--accent-purple)', fontWeight: 600, marginBottom: 6 }}>
                ⚡ Task interrupted — checkpoint saved
              </div>
              {task.checkpoint && (
                <pre style={{
                  fontSize: 11, color: 'var(--text-muted)', margin: '0 0 8px',
                  whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 80, overflow: 'auto',
                  background: 'rgba(0,0,0,0.3)', padding: '6px 8px', borderRadius: 4,
                }}>
                  {task.checkpoint.slice(0, 400)}{task.checkpoint.length > 400 ? '…' : ''}
                </pre>
              )}
              <button
                className="btn btn-ghost"
                style={{ fontSize: 12, borderColor: 'rgba(139,92,246,0.5)', color: 'var(--accent-purple)' }}
                onClick={() => onResume(task.task_id)}
              >
                ▶ Resume from checkpoint
              </button>
            </div>
          )}

          {/* Outcome */}
          {task.outcome && (
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.5 }}>
              <span style={{ fontWeight: 600, color: 'var(--text-muted)', marginRight: 6 }}>Outcome:</span>
              {task.outcome}
            </div>
          )}

          {/* Artifacts */}
          {task.artifacts && Object.keys(task.artifacts).length > 0 && (
            <pre style={{
              fontSize: 11, color: 'var(--text-muted)', marginTop: 6,
              background: 'rgba(0,0,0,0.25)', padding: '6px 8px',
              borderRadius: 4, maxHeight: 100, overflow: 'auto',
            }}>
              {JSON.stringify(task.artifacts, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// ── BA Analysis display ───────────────────────────────────────────────────────

function BAAnalysisPanel({ analysis }: { analysis: BAAnalysisResult }) {
  const [expandedStory, setExpandedStory] = useState<string | null>(null);

  const modeColor: Record<string, string> = {
    AUTO: 'var(--accent-green)', HITL: 'var(--accent-amber)', SECURITY: 'var(--accent-red)',
  };

  return (
    <div style={{
      marginTop: 16,
      background: 'rgba(139,92,246,0.06)',
      border: '1px solid rgba(139,92,246,0.25)',
      borderRadius: 'var(--radius)',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 16px', borderBottom: '1px solid rgba(139,92,246,0.2)',
        display: 'flex', alignItems: 'center', gap: 12,
        background: 'rgba(139,92,246,0.08)',
      }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent-purple)' }}>
          BA Agent Analysis
        </span>
        <span style={{
          padding: '2px 10px', background: 'rgba(139,92,246,0.2)',
          borderRadius: 100, fontSize: 12, color: 'var(--accent-purple)', fontWeight: 700,
        }}>
          {analysis.total_story_points} Story Points
        </span>
        <span style={{
          fontSize: 11, color: 'var(--text-muted)',
          marginLeft: 'auto',
        }}>
          {analysis.user_stories.length} User {analysis.user_stories.length === 1 ? 'Story' : 'Stories'} ·{' '}
          recommended: <ModeBadge mode={analysis.recommended_mode} />
        </span>
      </div>

      {/* User stories */}
      <div style={{ padding: '8px 0' }}>
        {analysis.user_stories.map((story, idx) => {
          const key = `${idx}-${story.title}`;
          const open = expandedStory === key;
          return (
            <div key={key} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <div
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '8px 16px', cursor: 'pointer',
                }}
                onClick={() => setExpandedStory(open ? null : key)}
              >
                <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent-purple)', minWidth: 20 }}>
                  US{idx + 1}
                </span>
                <ModeBadge mode={story.mode} />
                <span style={{
                  fontSize: 11, fontWeight: 700,
                  padding: '1px 6px', borderRadius: 4,
                  background: 'rgba(139,92,246,0.15)',
                  color: 'var(--accent-purple)',
                }}>
                  {story.story_points}SP
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)', flex: 1 }}>
                  {story.title}
                </span>
                <span className="capability-tag" style={{ fontSize: 10 }}>{story.task_type}</span>
                <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>{open ? '▾' : '▸'}</span>
              </div>

              {open && (
                <div style={{ padding: '4px 16px 12px 52px' }}>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 8 }}>
                    {story.description}
                  </div>
                  {story.acceptance_criteria.length > 0 && (
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                        Acceptance Criteria
                      </div>
                      {story.acceptance_criteria.map((ac, ai) => (
                        <div key={ai} style={{
                          marginBottom: 6, padding: '6px 10px',
                          background: 'rgba(0,0,0,0.2)', borderRadius: 6,
                          fontSize: 12, lineHeight: 1.7,
                        }}>
                          <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>Given</span>{' '}
                          <span style={{ color: 'var(--text-secondary)' }}>{ac.given}</span>
                          <br />
                          <span style={{ color: 'var(--accent-amber)', fontWeight: 600 }}>When</span>{' '}
                          <span style={{ color: 'var(--text-secondary)' }}>{ac.when}</span>
                          <br />
                          <span style={{ color: 'var(--accent-green)', fontWeight: 600 }}>Then</span>{' '}
                          <span style={{ color: 'var(--text-secondary)' }}>{ac.then}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Goal card ─────────────────────────────────────────────────────────────────

function GoalCard({
  goal, onRefresh, onApprove, onResume,
}: {
  goal: GoalRecord;
  onRefresh: () => void;
  onApprove: (taskId: string, approved: boolean, comment: string) => void;
  onResume: (taskId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const isBA = !!goal.analysis;
  const completedCount = goal.tasks.filter(t => t.status === 'completed').length;
  const hitlCount = goal.tasks.filter(t => t.status === 'hitl_pending').length;
  const interruptedCount = goal.tasks.filter(t => t.status === 'interrupted').length;
  const progress = goal.tasks.length > 0
    ? Math.round((completedCount / goal.tasks.length) * 100) : 0;

  const badgeClass =
    (goal.status === 'completed' || goal.status === 'done') ? 'green'
    : goal.status === 'failed'  ? 'critical'
    : hitlCount > 0             ? 'amber'
    : 'info';

  const totalSP = isBA && goal.analysis
    ? goal.analysis.total_story_points : null;

  return (
    <div className="goal-card">
      {/* Header */}
      <div className="goal-card-header" onClick={() => setExpanded(e => !e)}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
            <div className="goal-text">{goal.goal}</div>
            {isBA && <span style={{ fontSize: 10, padding: '1px 6px', background: 'rgba(139,92,246,0.15)', color: 'var(--accent-purple)', borderRadius: 4, fontWeight: 700 }}>BA</span>}
          </div>
          <div className="goal-meta">
            by {goal.submitted_by} · {new Date(goal.created_at).toLocaleTimeString()}
            {' '}· {completedCount}/{goal.tasks.length} tasks
            {totalSP != null && ` · ${totalSP} SP total`}
            {goal.worktree_id && (
              <span style={{ marginLeft: 6, padding: '1px 6px', borderRadius: 4, fontSize: 10, fontWeight: 600, background: 'rgba(6,182,212,0.12)', color: 'var(--accent-cyan)' }}>
                workspace
              </span>
            )}
            {hitlCount > 0 && <span style={{ color: 'var(--accent-amber)', marginLeft: 6 }}>⏸ {hitlCount} awaiting approval</span>}
            {interruptedCount > 0 && <span style={{ color: 'var(--accent-purple)', marginLeft: 6 }}>⚡ {interruptedCount} interrupted</span>}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 80, height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ width: `${progress}%`, height: '100%', background: progress === 100 ? 'var(--accent-green)' : 'var(--accent-blue)', transition: 'width 0.4s' }} />
          </div>
          <span className={`badge ${badgeClass}`}>{goal.status}</span>
          <button
            className="btn btn-ghost"
            style={{ padding: '4px 10px', fontSize: 12 }}
            onClick={e => { e.stopPropagation(); onRefresh(); }}
          >↻</button>
          <span style={{ color: 'var(--text-muted)', fontSize: 18 }}>{expanded ? '▾' : '▸'}</span>
        </div>
      </div>

      {/* Pipeline visualization */}
      {isBA
        ? <BAPipeline tasks={goal.tasks} />
        : <QuickPipeline tasks={goal.tasks} />
      }

      {/* Expanded: BA analysis + task details */}
      {expanded && (
        <div className="goal-tasks-detail">
          {/* BA analysis panel */}
          {goal.analysis && <BAAnalysisPanel analysis={goal.analysis} />}

          {/* Task details */}
          {goal.tasks.length > 0 && (
            <div style={{ marginTop: goal.analysis ? 12 : 0 }}>
              <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 6 }}>
                Task Details
              </div>
              {[...goal.tasks]
                .sort((a, b) => b.story_points - a.story_points)
                .map(task => (
                  <TaskRow
                    key={task.task_id}
                    task={task}
                    goalId={goal.goal_id}
                    onApprove={onApprove}
                    onResume={onResume}
                  />
                ))}
            </div>
          )}
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
            {goal.worktree_path && (
              <div style={{ marginBottom: 4, fontFamily: 'monospace', fontSize: 11, padding: '4px 8px', background: 'var(--bg-primary)', borderRadius: 4, border: '1px solid var(--border)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                workspace: {goal.worktree_path}
              </div>
            )}
            Goal ID: {goal.goal_id}
          </div>
        </div>
      )}
    </div>
  );
}

// ── File tree picker ─────────────────────────────────────────────────────────

type TreeNode = { name: string; path: string; type: 'file' | 'dir' | 'info'; children?: TreeNode[] };

function TreeNodeRow({
  node, depth, selected, onToggle,
}: {
  node: TreeNode;
  depth: number;
  selected: Set<string>;
  onToggle: (path: string) => void;
}) {
  const [open, setOpen] = useState(depth < 1);
  if (node.type === 'info') {
    return (
      <div style={{ paddingLeft: depth * 16 + 4, fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>
        {node.name}
      </div>
    );
  }
  if (node.type === 'dir') {
    return (
      <div>
        <div
          onClick={() => setOpen(o => !o)}
          style={{
            display: 'flex', alignItems: 'center', gap: 4,
            paddingLeft: depth * 16 + 4, paddingTop: 2, paddingBottom: 2,
            cursor: 'pointer', userSelect: 'none',
            color: 'var(--text-secondary)', fontSize: 12,
          }}
        >
          <span style={{ fontSize: 10, color: 'var(--text-muted)', width: 10, textAlign: 'center' }}>
            {open ? '▾' : '▸'}
          </span>
          <span style={{ fontSize: 12 }}>📁</span>
          <span>{node.name}</span>
        </div>
        {open && node.children?.map(child => (
          <TreeNodeRow
            key={child.path || child.name}
            node={child}
            depth={depth + 1}
            selected={selected}
            onToggle={onToggle}
          />
        ))}
      </div>
    );
  }
  const checked = selected.has(node.path);
  return (
    <label
      style={{
        display: 'flex', alignItems: 'center', gap: 6,
        paddingLeft: depth * 16 + 4, paddingTop: 2, paddingBottom: 2,
        cursor: 'pointer', userSelect: 'none',
        background: checked ? 'rgba(59,130,246,0.08)' : 'transparent',
        borderRadius: 4,
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={() => onToggle(node.path)}
        style={{ accentColor: 'var(--accent-blue)', cursor: 'pointer' }}
      />
      <span style={{ fontSize: 11 }}>📄</span>
      <span style={{ fontSize: 12, color: checked ? 'var(--accent-blue)' : 'var(--text-secondary)' }}>
        {node.name}
      </span>
    </label>
  );
}

function FileTreePicker({
  worktreeName, worktreePath, selected, onToggle, onClearAll,
}: {
  worktreeName: string;
  worktreePath: string;
  selected: Set<string>;
  onToggle: (path: string) => void;
  onClearAll: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      // CLI Bridge runs on host → can access Windows paths directly
      const res = await fetch(`${BRIDGE}/files?root=${encodeURIComponent(worktreePath)}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail ?? res.statusText);
      }
      const data = await res.json();
      setTree(data.tree ?? []);
    } catch (e: any) {
      setError(e.message ?? 'Failed to load files');
    } finally {
      setLoading(false);
    }
  };

  const handleOpen = () => {
    const next = !open;
    setOpen(next);
    if (next && tree.length === 0) load();
  };

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <button
          type="button"
          onClick={handleOpen}
          style={{
            padding: '4px 10px', fontSize: 11, fontFamily: 'var(--font)',
            cursor: 'pointer', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)',
            background: open ? 'rgba(59,130,246,0.12)' : 'transparent',
            color: open ? 'var(--accent-blue)' : 'var(--text-muted)',
          }}
        >
          {open ? '▾' : '▸'} Browse {worktreeName}
        </button>
        {selected.size > 0 && (
          <>
            <span style={{ fontSize: 11, color: 'var(--accent-blue)' }}>
              {selected.size} file{selected.size !== 1 ? 's' : ''} selected
            </span>
            <button
              type="button"
              onClick={onClearAll}
              style={{
                fontSize: 11, padding: '2px 6px', cursor: 'pointer',
                border: '1px solid var(--border)', borderRadius: 4,
                background: 'transparent', color: 'var(--text-muted)',
              }}
            >
              clear
            </button>
          </>
        )}
      </div>

      {open && (
        <div style={{
          marginTop: 6, maxHeight: 280, overflow: 'auto',
          border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
          background: 'var(--bg-primary)', padding: '6px 4px',
        }}>
          {loading && <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 12px' }}>Loading…</div>}
          {error && <div style={{ fontSize: 12, color: 'var(--accent-red)', padding: '8px 12px' }}>{error}</div>}
          {!loading && !error && tree.length === 0 && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 12px' }}>No files found.</div>
          )}
          {tree.map(node => (
            <TreeNodeRow
              key={node.path || node.name}
              node={node}
              depth={0}
              selected={selected}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}

      {/* Selected file chips */}
      {selected.size > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
          {[...selected].map(p => {
            const name = p.replace(/\\/g, '/').split('/').pop() ?? p;
            return (
              <span
                key={p}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 4,
                  padding: '2px 8px', borderRadius: 100,
                  background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.3)',
                  fontSize: 11, color: 'var(--accent-blue)',
                }}
              >
                {name}
                <span
                  onClick={() => onToggle(p)}
                  style={{ cursor: 'pointer', opacity: 0.7, lineHeight: 1 }}
                >×</span>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Submit form ───────────────────────────────────────────────────────────────

function SubmitForm({
  submitting,
  error,
  worktrees,
  onQuick,
  onBA,
}: {
  submitting: boolean;
  error: string | null;
  worktrees: WorktreeRecord[];
  onQuick: (goal: string, by: string, worktreeId?: string) => void;
  onBA: (goal: string, by: string, worktreeId?: string) => void;
}) {
  const [input, setInput] = useState('');
  const [submitter, setSubmitter] = useState('dashboard-user');
  const [mode, setMode] = useState<'quick' | 'ba'>('quick');
  const [selectedWorktree, setSelectedWorktree] = useState('');
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const fileInputRef = useRef<HTMLInputElement>(null);

  const activeWorktrees = worktrees.filter(w => w.active);

  const selectedWorktreeRecord = activeWorktrees.find(w => w.worktree_id === selectedWorktree);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => {
      const text = (ev.target?.result as string) ?? '';
      setInput(text.trim());
    };
    reader.readAsText(file, 'utf-8');
    e.target.value = '';
  };

  const toggleFile = (path: string) => {
    setSelectedFiles(prev => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  };

  const buildGoalText = (base: string) => {
    if (selectedFiles.size === 0) return base;
    const paths = [...selectedFiles].map(p => `- ${p.replace(/\\/g, '/')}`).join('\n');
    return `${base}\n\nATTACHED FILES:\n${paths}`;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    const wtId = selectedWorktree || undefined;
    const goal = buildGoalText(input.trim());
    if (mode === 'quick') {
      onQuick(goal, submitter, wtId);
      setInput('');
      setSelectedFiles(new Set());
    } else {
      onBA(goal, submitter, wtId);
      setInput('');
      setSelectedFiles(new Set());
    }
  };

  return (
    <div className="settings-section" style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0 }}>Submit New Goal</h3>
        {/* Mode toggle */}
        <div style={{ display: 'flex', gap: 0, border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
          {(['quick', 'ba'] as const).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              style={{
                padding: '6px 14px', fontSize: 12, fontFamily: 'var(--font)',
                cursor: 'pointer', border: 'none',
                background: mode === m ? (m === 'ba' ? 'rgba(139,92,246,0.25)' : 'rgba(59,130,246,0.2)') : 'transparent',
                color: mode === m ? (m === 'ba' ? 'var(--accent-purple)' : 'var(--accent-blue)') : 'var(--text-muted)',
                fontWeight: mode === m ? 700 : 400,
                transition: 'all 0.2s',
              }}
            >
              {m === 'quick' ? 'Quick Submit' : '✦ BA Analyze'}
            </button>
          ))}
        </div>
      </div>

      {mode === 'ba' && (
        <div style={{
          padding: '8px 12px', marginBottom: 14,
          background: 'rgba(139,92,246,0.07)', border: '1px solid rgba(139,92,246,0.25)',
          borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--text-secondary)',
        }}>
          BA Analyze uses the LLM to decompose your goal into User Stories with Acceptance Criteria
          and Fibonacci story points. Tasks are classified as <ModeBadge mode="AUTO" />{' '}
          <ModeBadge mode="HITL" /> or <ModeBadge mode="SECURITY" /> and queued by priority.
        </div>
      )}

      {/* Hidden file input for .md upload */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".md,.txt,.rst"
        style={{ display: 'none' }}
        onChange={handleFileUpload}
      />

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <label style={{ margin: 0 }}>Goal Description</label>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              title="Load goal from a .md or .txt file"
              style={{
                display: 'flex', alignItems: 'center', gap: 5,
                padding: '3px 10px', fontSize: 11, fontFamily: 'var(--font)',
                cursor: 'pointer', borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border)',
                background: 'transparent', color: 'var(--text-muted)',
              }}
            >
              📄 Load .md file
            </button>
          </div>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder={
              mode === 'ba'
                ? 'e.g. Build a REST API for user authentication with JWT tokens and refresh token rotation'
                : 'e.g. Build a REST API for user authentication'
            }
            required
            rows={4}
            style={{
              width: '100%', padding: '8px 10px', fontSize: 13,
              background: 'var(--bg-primary)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
              fontFamily: 'var(--font)', resize: 'vertical', lineHeight: 1.6,
              boxSizing: 'border-box',
            }}
          />
        </div>

        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div className="form-group" style={{ marginBottom: 0, width: 200 }}>
            <label>Submitted By</label>
            <input
              value={submitter}
              onChange={e => setSubmitter(e.target.value)}
              placeholder="dashboard-user"
            />
          </div>
          {activeWorktrees.length > 0 && (
            <div className="form-group" style={{ marginBottom: 0, width: 220 }}>
              <label>Workspace (optional)</label>
              <select
                value={selectedWorktree}
                onChange={e => {
                  setSelectedWorktree(e.target.value);
                  setSelectedFiles(new Set());
                }}
                style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)', fontSize: 13 }}
              >
                <option value="">— no workspace —</option>
                {activeWorktrees.map(w => (
                  <option key={w.worktree_id} value={w.worktree_id}>{w.name}</option>
                ))}
              </select>
            </div>
          )}
          <button
            type="submit"
            className="btn btn-primary"
            disabled={submitting || !input.trim()}
            style={{ background: mode === 'ba' ? 'linear-gradient(135deg, #8b5cf6, #ec4899)' : undefined }}
          >
            {submitting
              ? (mode === 'ba' ? 'Analyzing…' : 'Submitting…')
              : (mode === 'ba' ? '✦ Analyze with BA Agent' : 'Submit Goal')
            }
          </button>
        </div>

        {/* File picker — shown when a workspace is selected */}
        {selectedWorktreeRecord && (
          <FileTreePicker
            worktreeName={selectedWorktreeRecord.name}
            worktreePath={selectedWorktreeRecord.path}
            selected={selectedFiles}
            onToggle={toggleFile}
            onClearAll={() => setSelectedFiles(new Set())}
          />
        )}

        {/* Preview of what will be appended */}
        {selectedFiles.size > 0 && (
          <div style={{
            marginTop: 8, padding: '6px 10px',
            background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.2)',
            borderRadius: 'var(--radius-sm)', fontSize: 11, color: 'var(--text-muted)',
          }}>
            {selectedFiles.size} file path{selectedFiles.size !== 1 ? 's' : ''} will be appended to your goal as context for the agents.
          </div>
        )}
      </form>
      {error && <div className="inline-alert error" style={{ marginTop: 12 }}>{error}</div>}
    </div>
  );
}

// ── Goals page ────────────────────────────────────────────────────────────────

export function Goals() {
  const { goals, submitting, initialLoading, error, submitGoal, analyzeGoal, refreshGoal, approveHitl, resumeTask } = useGoals();
  const { worktrees } = useWorktrees();

  const handleApprove = useCallback(
    (goalId: string) => (taskId: string, approved: boolean, comment: string) => {
      approveHitl(goalId, taskId, approved, comment);
    },
    [approveHitl],
  );

  const handleResume = useCallback(
    (goalId: string) => (taskId: string) => {
      resumeTask(goalId, taskId);
    },
    [resumeTask],
  );

  const DONE = new Set(['completed', 'done']);
  const activeCount = goals.filter(g => !DONE.has(g.status) && g.status !== 'failed').length;
  const doneCount = goals.filter(g => DONE.has(g.status)).length;
  const hitlCount = goals.flatMap(g => g.tasks).filter(t => t.status === 'hitl_pending').length;

  return (
    <div className="fade-in">
      <div className="page-header">
        <h2>Goals & Workflows</h2>
        <p>Submit goals and watch the agent pipeline execute — Quick or BA Agent intelligent decomposition</p>
      </div>

      {/* Stats */}
      {goals.length > 0 && (
        <div className="kpi-grid" style={{ marginBottom: 24 }}>
          <div className="kpi-card blue">
            <div className="kpi-label">Total Goals</div>
            <div className="kpi-value">{goals.length}</div>
            <div className="kpi-sub">this session</div>
          </div>
          <div className="kpi-card amber">
            <div className="kpi-label">In Progress</div>
            <div className="kpi-value">{activeCount}</div>
            <div className="kpi-sub">polling every 5s</div>
          </div>
          <div className="kpi-card green">
            <div className="kpi-label">Completed</div>
            <div className="kpi-value">{doneCount}</div>
            <div className="kpi-sub">goals done</div>
          </div>
          {hitlCount > 0 && (
            <div className="kpi-card amber" style={{ borderColor: 'rgba(245,158,11,0.4)' }}>
              <div className="kpi-label" style={{ color: 'var(--accent-amber)' }}>Awaiting Approval</div>
              <div className="kpi-value" style={{ color: 'var(--accent-amber)' }}>{hitlCount}</div>
              <div className="kpi-sub">HITL tasks pending</div>
            </div>
          )}
        </div>
      )}

      {/* Submit form */}
      <SubmitForm
        submitting={submitting}
        error={error}
        worktrees={worktrees}
        onQuick={(goal, by, wtId) => submitGoal(goal, by, wtId)}
        onBA={(goal, by, wtId) => analyzeGoal(goal, by, wtId)}
      />

      {/* Legend */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Status:</span>
        {[
          ['pending', 'Pending'],
          ['in_progress', 'Running'],
          ['hitl_pending', 'Awaiting Approval'],
          ['interrupted', 'Interrupted'],
          ['completed', 'Completed'],
          ['failed', 'Failed'],
        ].map(([s, lbl]) => (
          <div key={s} style={{
            padding: '2px 10px', fontSize: 11, borderRadius: 4,
            border: `1px solid ${STATUS_BORDER[s]}`,
            background: STATUS_BG[s], color: STATUS_COLOR[s],
          }}>
            {lbl}
          </div>
        ))}
      </div>

      {/* Goals list */}
      {initialLoading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[0, 1, 2].map(i => (
            <div key={i} className="skeleton" style={{ height: 80, borderRadius: 'var(--radius)' }} />
          ))}
        </div>
      ) : goals.length === 0 ? (
        <div className="empty-state" style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
          <h3>No goals yet</h3>
          <p>Use Quick Submit for the fixed Research → Code → Test → Evaluate pipeline,
             or BA Analyze for intelligent decomposition with story points.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {goals.map(g => (
            <GoalCard
              key={g.goal_id}
              goal={g}
              onRefresh={() => refreshGoal(g.goal_id)}
              onApprove={handleApprove(g.goal_id)}
              onResume={handleResume(g.goal_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
