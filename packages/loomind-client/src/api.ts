// ============================================================
// @loomind/client — LoomindClient
// Type-safe SDK for communicating with the Experience Engine
// Uses native fetch() — zero external HTTP dependencies
// ============================================================

import type {
  InterceptRequest,
  InterceptResponse,
  Experience,
  CreateExperienceRequest,
  UpdateExperienceRequest,
  FeedbackRequest,
  HealthStatus,
  EngineStats,
  PaginationParams,
  PaginatedResponse,
} from '@loomind/types';
import { isReadOnlyAction, classifyAction } from './filters/readonly-filter';
import { OfflineQueue } from './offline-queue';

// --------------- Event System ---------------

type EventName = 'connected' | 'disconnected' | 'error' | 'suggestion';
type EventCallback = (...args: unknown[]) => void;

// --------------- Config ---------------

export interface LoomindClientConfig {
  /** Base URL of the engine (default: http://localhost:8082) */
  baseUrl?: string;
  /** Request timeout in ms (default: 5000) */
  timeout?: number;
  /** Health check interval in ms (default: 30000) */
  healthCheckInterval?: number;
  /** Max offline queue size (default: 100) */
  maxQueueSize?: number;
}

// --------------- Fetch Helpers ---------------

/** Custom error for HTTP responses with non-OK status */
class HttpError extends Error {
  status: number;
  statusText: string;
  code?: string;

  constructor(status: number, statusText: string, message?: string) {
    super(message ?? `HTTP ${status}: ${statusText}`);
    this.name = 'HttpError';
    this.status = status;
    this.statusText = statusText;
  }
}

/**
 * Wrapper around native fetch() with timeout, JSON parsing, and error handling.
 * Replaces axios — zero dependencies.
 */
async function request<T>(
  baseUrl: string,
  path: string,
  options: {
    method?: string;
    body?: unknown;
    params?: Record<string, string | number | undefined>;
    timeout?: number;
  } = {},
): Promise<T> {
  const { method = 'GET', body, params, timeout = 5000 } = options;

  // Build URL with query params
  let url = `${baseUrl}${path}`;
  if (params) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) searchParams.set(key, String(value));
    }
    const qs = searchParams.toString();
    if (qs) url += `?${qs}`;
  }

  // AbortController for timeout
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const resp = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    if (!resp.ok) {
      throw new HttpError(resp.status, resp.statusText);
    }

    // Handle 204 No Content
    const contentType = resp.headers.get('content-type');
    if (resp.status === 204 || !contentType?.includes('application/json')) {
      return undefined as T;
    }

    return (await resp.json()) as T;
  } catch (err) {
    if (err instanceof HttpError) throw err;

    // Network / timeout errors
    const error = new HttpError(0, 'Network Error', (err as Error).message);
    if ((err as Error).name === 'AbortError') {
      error.code = 'ECONNABORTED';
      error.message = `Request timeout after ${timeout}ms`;
    } else {
      error.code = 'ECONNREFUSED';
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

// --------------- Client ---------------

/**
 * LoomindClient — Main SDK for interacting with the Experience Engine.
 *
 * Features:
 * - Type-safe API calls using native fetch() (zero dependencies)
 * - Client-side read-only filter (Layer 1, 0ms)
 * - Offline queue for requests when engine is down
 * - Automatic health checking with event emission
 */
export class LoomindClient {
  private baseUrl: string;
  private timeout: number;
  private offlineQueue: OfflineQueue;
  private connected: boolean = false;
  private healthTimer: ReturnType<typeof setInterval> | null = null;
  private listeners: Map<EventName, Set<EventCallback>> = new Map();

  constructor(config: LoomindClientConfig = {}) {
    this.baseUrl = config.baseUrl ?? 'http://localhost:8082';
    this.timeout = config.timeout ?? 5000;
    this.offlineQueue = new OfflineQueue(config.maxQueueSize ?? 100);

    // Start periodic health checks
    const interval = config.healthCheckInterval ?? 30000;
    this.healthTimer = setInterval(() => this.checkHealth(), interval);

    // Initial health check
    this.checkHealth();
  }

  // ─── Internal fetch wrapper ───

  private fetch<T>(path: string, options?: { method?: string; body?: unknown; params?: Record<string, string | number | undefined>; timeout?: number }): Promise<T> {
    return request<T>(this.baseUrl, path, { timeout: this.timeout, ...options });
  }

  // ==================== Core API ====================

  /**
   * Intercept an AI agent action.
   * Applies client-side Layer 1 filter before calling the engine.
   */
  async intercept(request: InterceptRequest): Promise<InterceptResponse> {
    // Layer 1: Client-side read-only filter (0ms)
    const actionType = request.action_type ?? classifyAction(request.action);
    if (isReadOnlyAction(request.action)) {
      return {
        skipped: true,
        suggestions: [],
        latency_ms: 0,
        layers_executed: ['L1-client'],
      };
    }

    const payload: InterceptRequest = { ...request, action_type: actionType };

    try {
      const data = await this.fetch<InterceptResponse>('/api/intercept', {
        method: 'POST',
        body: payload,
      });
      this.setConnected(true);
      return data;
    } catch (err) {
      this.handleError(err as HttpError);
      // Queue for later if offline
      this.offlineQueue.enqueue(payload);
      return {
        skipped: false,
        suggestions: [],
        latency_ms: 0,
        layers_executed: ['L1-client', 'offline-queued'],
      };
    }
  }

  // ==================== Experience CRUD ====================

  async getExperiences(params?: PaginationParams): Promise<PaginatedResponse<Experience>> {
    return this.fetch<PaginatedResponse<Experience>>('/api/experiences', {
      params: params as Record<string, string | number | undefined>,
    });
  }

  async getExperience(id: string): Promise<Experience> {
    return this.fetch<Experience>(`/api/experiences/${id}`);
  }

  async addExperience(request: CreateExperienceRequest): Promise<Experience> {
    return this.fetch<Experience>('/api/experiences', { method: 'POST', body: request });
  }

  async updateExperience(id: string, request: UpdateExperienceRequest): Promise<Experience> {
    return this.fetch<Experience>(`/api/experiences/${id}`, { method: 'PUT', body: request });
  }

  async deleteExperience(id: string): Promise<void> {
    await this.fetch<void>(`/api/experiences/${id}`, { method: 'DELETE' });
  }

  async submitFeedback(experienceId: string, feedback: FeedbackRequest): Promise<void> {
    await this.fetch<void>(`/api/experiences/${experienceId}/feedback`, { method: 'POST', body: feedback });
  }

  async searchExperiences(query: string): Promise<Experience[]> {
    return this.fetch<Experience[]>('/api/experiences/search', { method: 'POST', body: { query } });
  }

  // ==================== Backup / Restore ====================

  async exportExperiences(): Promise<{ version: string; total: number; experiences: Experience[] }> {
    return this.fetch('/api/experiences/backup/export', { timeout: 30000 });
  }

  async importExperiences(
    experiences: Record<string, unknown>[],
    overwrite = false,
  ): Promise<{ imported: number; skipped: number; failed: number; total_in_file: number }> {
    return this.fetch('/api/experiences/backup/import', {
      method: 'POST',
      body: { experiences, overwrite },
      timeout: 120000,
    });
  }

  // ==================== Health ====================

  async health(): Promise<HealthStatus> {
    return this.fetch<HealthStatus>('/health');
  }

  async stats(): Promise<EngineStats> {
    return this.fetch<EngineStats>('/api/stats');
  }

  /** Whether the engine is currently reachable */
  isConnected(): boolean {
    return this.connected;
  }

  /** Number of requests queued while offline */
  get queueSize(): number {
    return this.offlineQueue.size;
  }

  // ==================== Events ====================

  on(event: EventName, callback: EventCallback): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(callback);
  }

  off(event: EventName, callback: EventCallback): void {
    this.listeners.get(event)?.delete(callback);
  }

  // ==================== Lifecycle ====================

  /** Stop health checks and clean up */
  dispose(): void {
    if (this.healthTimer) {
      clearInterval(this.healthTimer);
      this.healthTimer = null;
    }
    this.listeners.clear();
  }

  // ==================== Private ====================

  private async checkHealth(): Promise<void> {
    try {
      await this.fetch<HealthStatus>('/health', { timeout: 3000 });
      this.setConnected(true);

      // Flush offline queue if we just reconnected
      if (!this.offlineQueue.isEmpty) {
        const queued = this.offlineQueue.drain();
        for (const item of queued) {
          try {
            await this.fetch<void>('/api/intercept', { method: 'POST', body: item.request });
          } catch {
            // Re-queue if still failing
            this.offlineQueue.enqueue(item.request);
            break;
          }
        }
      }
    } catch {
      this.setConnected(false);
    }
  }

  private setConnected(value: boolean): void {
    const wasConnected = this.connected;
    this.connected = value;

    if (value && !wasConnected) {
      this.emit('connected');
    } else if (!value && wasConnected) {
      this.emit('disconnected');
    }
  }

  private handleError(err: HttpError): void {
    if (err.status === 0 || err.code === 'ECONNREFUSED' || err.code === 'ECONNABORTED') {
      this.setConnected(false);
    }
    this.emit('error', err);
  }

  private emit(event: EventName, ...args: unknown[]): void {
    this.listeners.get(event)?.forEach((cb) => cb(...args));
  }
}
