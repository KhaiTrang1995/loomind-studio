import { useState, useEffect, useCallback, useRef } from 'react';

const ENGINE = 'http://127.0.0.1:8082';

// ── Types ─────────────────────────────────────────────────────────────────────

export type TaskStatus =
  | 'pending' | 'claimed' | 'completed' | 'failed'
  | 'hitl_pending' | 'in_progress' | 'interrupted' | 'verifying';

export type TaskMode = 'AUTO' | 'HITL' | 'SECURITY';

export interface TaskRecord {
  task_id: string;
  goal_id: string;
  task_type: string;
  description: string;
  assigned_to: string | null;
  status: TaskStatus;
  mode: TaskMode | null;
  story_points: number;
  retry_count: number;
  checkpoint: string | null;
  hitl_deadline: string | null;
  outcome: string | null;
  artifacts: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
}

export interface AcceptanceCriteria {
  given: string;
  when: string;
  then: string;
}

export interface UserStory {
  title: string;
  description: string;
  acceptance_criteria: AcceptanceCriteria[];
  story_points: number;
  mode: string;
  task_type: string;
}

export interface BAAnalysisResult {
  user_stories: UserStory[];
  total_story_points: number;
  recommended_mode: string;
}

export interface GoalRecord {
  goal_id: string;
  goal: string;
  submitted_by: string;
  tasks: TaskRecord[];
  status: string;
  analysis: BAAnalysisResult | null;
  created_at: string;
  worktree_id: string | null;
  worktree_path: string | null;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

interface GoalsState {
  goals: GoalRecord[];
  submitting: boolean;
  initialLoading: boolean;
  error: string | null;
  submitGoal: (goal: string, submittedBy?: string, worktreeId?: string) => Promise<void>;
  analyzeGoal: (goal: string, submittedBy?: string, worktreeId?: string) => Promise<GoalRecord | null>;
  refreshGoal: (goalId: string) => Promise<void>;
  approveHitl: (goalId: string, taskId: string, approved: boolean, comment?: string) => Promise<void>;
  resumeTask: (goalId: string, taskId: string, agentId?: string) => Promise<void>;
}

export function useGoals(): GoalsState {
  const [goals, setGoals] = useState<GoalRecord[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Quick submit — fixed 4-stage pipeline
  const submitGoal = useCallback(async (goal: string, submittedBy = 'dashboard-user', worktreeId?: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const resp = await fetch(`${ENGINE}/api/goals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal, submitted_by: submittedBy, worktree_id: worktreeId || undefined }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const record: GoalRecord = await resp.json();
      setGoals(prev => [record, ...prev]);
    } catch {
      setError('Failed to submit goal — engine may be offline');
    } finally {
      setSubmitting(false);
    }
  }, []);

  // Smart analyze — BA Agent decomposes into User Stories + tasks
  const analyzeGoal = useCallback(async (
    goal: string,
    submittedBy = 'dashboard-user',
    worktreeId?: string,
  ): Promise<GoalRecord | null> => {
    setSubmitting(true);
    setError(null);
    try {
      const resp = await fetch(`${ENGINE}/api/ba/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal, submitted_by: submittedBy, worktree_id: worktreeId || undefined }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const record: GoalRecord = await resp.json();
      setGoals(prev => [record, ...prev]);
      return record;
    } catch {
      setError('BA Analysis failed — check engine logs');
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const refreshGoal = useCallback(async (goalId: string) => {
    try {
      const [gResp, tResp] = await Promise.all([
        fetch(`${ENGINE}/api/goals/${goalId}`),
        fetch(`${ENGINE}/api/goals/${goalId}/tasks`),
      ]);
      if (!gResp.ok || !tResp.ok) return;
      const record: GoalRecord = await gResp.json();
      const tasks: TaskRecord[] = await tResp.json();
      record.tasks = tasks;
      setGoals(prev => {
        const existing = prev.find(g => g.goal_id === goalId);
        // Skip update if nothing meaningful changed — prevents unnecessary re-renders
        if (
          existing &&
          existing.status === record.status &&
          existing.tasks.length === record.tasks.length &&
          existing.tasks.every((t, i) =>
            t.status === record.tasks[i]?.status &&
            t.assigned_to === record.tasks[i]?.assigned_to &&
            t.outcome === record.tasks[i]?.outcome
          )
        ) return prev;
        return prev.map(g => g.goal_id === goalId ? record : g);
      });
    } catch {
      // silent — engine may be momentarily unavailable
    }
  }, []);

  // HITL approval/rejection
  const approveHitl = useCallback(async (
    goalId: string,
    taskId: string,
    approved: boolean,
    comment = '',
  ) => {
    try {
      await fetch(`${ENGINE}/api/ba/goals/${goalId}/tasks/${taskId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved, comment }),
      });
      await refreshGoal(goalId);
    } catch {
      // caller can check refreshed task status
    }
  }, [refreshGoal]);

  // Resume an interrupted task from its checkpoint
  const resumeTask = useCallback(async (
    goalId: string,
    taskId: string,
    agentId = 'dashboard-user',
  ) => {
    try {
      await fetch(`${ENGINE}/api/ba/goals/${goalId}/tasks/${taskId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId }),
      });
      await refreshGoal(goalId);
    } catch {
      // silent
    }
  }, [refreshGoal]);

  // Stable ref so the interval closure always sees the latest goals
  // without restarting the interval on every poll result
  const goalsRef = useRef(goals);
  goalsRef.current = goals;

  // Load all goals on mount so history is visible without a new submission
  useEffect(() => {
    fetch(`${ENGINE}/api/goals?limit=50`)
      .then(r => r.ok ? r.json() : [])
      .then((data: GoalRecord[]) => { if (data.length) setGoals(data); })
      .catch(() => null)
      .finally(() => setInitialLoading(false));
  }, []);

  // Poll active (non-terminal) goals every 5s
  useEffect(() => {
    const TERMINAL = new Set(['completed', 'failed', 'done']);
    const id = setInterval(() => {
      goalsRef.current
        .filter(g => !TERMINAL.has(g.status))
        .forEach(g => refreshGoal(g.goal_id));
    }, 5000);
    return () => clearInterval(id);
  }, [refreshGoal]);

  return { goals, submitting, initialLoading, error, submitGoal, analyzeGoal, refreshGoal, approveHitl, resumeTask };
}
