// ============================================================
// @loomind/client — Offline Queue
// Buffers intercept requests when the engine is offline
// and replays them when the connection is restored.
// ============================================================

import type { InterceptRequest } from '@loomind/types';

export interface QueuedRequest {
  request: InterceptRequest;
  timestamp: number;
}

/**
 * Offline queue that buffers requests when the engine is unreachable.
 * Requests are stored in memory and can be flushed when the engine comes back online.
 */
export class OfflineQueue {
  private queue: QueuedRequest[] = [];
  private readonly maxSize: number;

  constructor(maxSize: number = 100) {
    this.maxSize = maxSize;
  }

  /** Add a request to the queue */
  enqueue(request: InterceptRequest): void {
    if (this.queue.length >= this.maxSize) {
      // Drop oldest request
      this.queue.shift();
    }
    this.queue.push({ request, timestamp: Date.now() });
  }

  /** Get all queued requests and clear the queue */
  drain(): QueuedRequest[] {
    const items = [...this.queue];
    this.queue = [];
    return items;
  }

  /** Number of queued requests */
  get size(): number {
    return this.queue.length;
  }

  /** Check if the queue is empty */
  get isEmpty(): boolean {
    return this.queue.length === 0;
  }

  /** Clear the queue */
  clear(): void {
    this.queue = [];
  }
}
