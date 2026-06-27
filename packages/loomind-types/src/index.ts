// ============================================================
// @loomind/types — Shared TypeScript Type Definitions
// Auto-aligned with Python FastAPI OpenAPI schema
// ============================================================

// --------------- Enums ---------------

export type ActionType = 'read' | 'write' | 'execute' | 'unknown';
export type Severity = 'info' | 'warning' | 'critical';
export type SuggestionSource = 'semantic_search' | 'exact_match' | 'llm_filter';
export type EngineStatus = 'running' | 'stopped' | 'starting' | 'error';

// --------------- Request / Response ---------------

export interface InterceptRequest {
  /** Description of the action (e.g., "edit file db.ts") */
  action: string;
  /** Classified action type */
  action_type?: ActionType;
  /** File being operated on */
  file_path?: string;
  /** File content snippet for context */
  file_content?: string;
  /** Programming language */
  language?: string;
  /** AI agent name (copilot, cursor, etc.) */
  agent?: string;
  /** Additional context string */
  context?: string;
}

export interface Suggestion {
  /** ID of the source experience */
  experience_id: string;
  /** Short title */
  title: string;
  /** Full suggestion message to inject into agent prompt */
  message: string;
  /** Severity level */
  severity: Severity;
  /** Relevance score 0.0 – 1.0 */
  relevance_score: number;
  /** How this suggestion was sourced */
  source: SuggestionSource;
}

export interface InterceptResponse {
  /** True if Layer 1 skipped (read-only action) */
  skipped: boolean;
  /** List of suggestions for the agent */
  suggestions: Suggestion[];
  /** Total processing time in ms */
  latency_ms: number;
  /** Which layers were executed: ["L1"], ["L1","L2","L3"] */
  layers_executed: string[];
}

// --------------- Experience ---------------

export interface Experience {
  id: string;
  title: string;
  description: string;
  category: string;
  tags: string[];
  file_patterns: string[];
  language?: string;
  severity: Severity;
  created_at: string;
  updated_at: string;
  usage_count: number;
  feedback_score: number;
}

export interface CreateExperienceRequest {
  title: string;
  description: string;
  category: string;
  tags?: string[];
  file_patterns?: string[];
  language?: string;
  severity?: Severity;
}

export interface UpdateExperienceRequest {
  title?: string;
  description?: string;
  category?: string;
  tags?: string[];
  file_patterns?: string[];
  severity?: Severity;
}

export interface FeedbackRequest {
  /** Score from -1.0 (bad) to 1.0 (good) */
  score: number;
  /** Optional comment */
  comment?: string;
}

// --------------- Health ---------------

export interface HealthStatus {
  status: 'ok' | 'degraded' | 'error';
  engine: EngineStatus;
  qdrant: boolean;
  embedder_loaded: boolean;
  llm_available: boolean;
  uptime_seconds: number;
  version: string;
}

export interface EngineStats {
  total_experiences: number;
  total_queries: number;
  avg_latency_ms: number;
  cache_hit_rate: number;
  queries_today: number;
}

// --------------- Pagination ---------------

export interface PaginationParams {
  limit?: number;
  offset?: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
