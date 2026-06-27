// ============================================================
// @loomind/client — Read-only action filter (Layer 1)
// Skips read-only actions at the client side (0ms overhead)
// ============================================================

/** Patterns that indicate a read-only (non-destructive) command */
const READONLY_PATTERNS: string[] = [
  'ls',
  'dir',
  'cat',
  'type',
  'git log',
  'git status',
  'git diff',
  'git show',
  'grep',
  'find',
  'head',
  'tail',
  'wc',
  'file',
  'stat',
  'tree',
  'pwd',
  'echo',
  'which',
  'where',
  'whoami',
  'env',
  'printenv',
  'read_file',
  'view_file',
  'list_dir',
  'search',
];

/**
 * Determines if an action is read-only (non-destructive).
 * Read-only actions are skipped by the Experience Engine to avoid latency.
 *
 * @param action - The action description string
 * @returns true if the action is read-only
 */
export function isReadOnlyAction(action: string): boolean {
  const lower = action.toLowerCase().trim();
  return READONLY_PATTERNS.some((p) => lower.includes(p));
}

/**
 * Classifies an action into its type.
 *
 * @param action - The action description string
 * @returns The classified action type
 */
export function classifyAction(action: string): 'read' | 'write' | 'execute' | 'unknown' {
  const lower = action.toLowerCase().trim();

  if (isReadOnlyAction(lower)) return 'read';

  const writePatterns = ['edit', 'create', 'write', 'delete', 'remove', 'modify', 'update', 'rename', 'move', 'copy'];
  if (writePatterns.some((p) => lower.includes(p))) return 'write';

  const execPatterns = ['run', 'exec', 'build', 'test', 'deploy', 'install', 'compile', 'start', 'stop'];
  if (execPatterns.some((p) => lower.includes(p))) return 'execute';

  return 'unknown';
}
