import { ExecutionContextLike } from "../shims/request-context.js";
import { CacheHandler, CacheHandlerValue, IncrementalCacheValue } from "../shims/cache.js";

//#region src/cloudflare/kv-cache-handler.d.ts
type KVNamespace = {
  get(key: string, options?: {
    type?: string;
  }): Promise<string | null>;
  get(key: string, options: {
    type: "arrayBuffer";
  }): Promise<ArrayBuffer | null>;
  put(key: string, value: string | ArrayBuffer | ReadableStream, options?: {
    expirationTtl?: number;
    metadata?: Record<string, unknown>;
  }): Promise<void>;
  delete(key: string): Promise<void>;
  list(options?: {
    prefix?: string;
    limit?: number;
    cursor?: string;
  }): Promise<{
    keys: Array<{
      name: string;
      metadata?: Record<string, unknown>;
    }>;
    list_complete: boolean;
    cursor?: string;
  }>;
};
/** Key prefix for cache entries. */
declare const ENTRY_PREFIX = "cache:";
declare class KVCacheHandler implements CacheHandler {
  private kv;
  private prefix;
  private ctx;
  private ttlSeconds;
  /** Local in-memory cache for tag invalidation timestamps. Avoids redundant KV reads. */
  private _tagCache;
  /** TTL (ms) for local tag cache entries. After this, re-fetch from KV. */
  private _tagCacheTtl;
  constructor(kvNamespace: KVNamespace, options?: {
    appPrefix?: string;
    ctx?: ExecutionContextLike;
    ttlSeconds?: number; /** TTL in milliseconds for the local tag cache. Defaults to 5000ms. */
    tagCacheTtlMs?: number;
  });
  get(key: string, _ctx?: Record<string, unknown>): Promise<CacheHandlerValue | null>;
  /**
   * Check tag invalidation markers for stored tags or read-time soft tags.
   * Uses a local in-memory cache to avoid redundant KV reads for recently-seen tags.
   */
  private _hasRevalidatedTag;
  set(key: string, data: IncrementalCacheValue | null, ctx?: Record<string, unknown>): Promise<void>;
  revalidateTag(tags: string | string[], _durations?: {
    expire?: number;
  }): Promise<void>;
  /**
   * Invalidate all cache entries whose path tags fall under `pathPrefix`.
   *
   * Uses KV list metadata to discover tags without fetching entry values —
   * entries written by `set()` store their tags in KV metadata, so
   * `kv.list()` returns them inline with each key. This makes prefix
   * invalidation O(list_pages) instead of O(entries × get).
   *
   * Entries written before metadata was added (no metadata.tags) are
   * gracefully skipped — they'll be picked up on next `set()` which
   * writes metadata.
   *
   * When present, this method fully replaces the `revalidateTag` call
   * path in `revalidatePath()` — implementors own all path-based tag
   * handling.
   */
  revalidateByPathPrefix(pathPrefix: string): Promise<void>;
  /**
   * Clear the in-memory tag cache for this KVCacheHandler instance.
   *
   * Note: KVCacheHandler instances are typically reused across multiple
   * requests in a Cloudflare Worker. The `_tagCache` is intentionally
   * cross-request — it reduces redundant KV reads for recently-seen tags
   * across all requests hitting the same isolate, bounded by `tagCacheTtlMs`
   * (default 5s). vinext does NOT call this method per request.
   *
   * This is an opt-in escape hatch for callers that need stricter isolation
   * (e.g., tests, or environments with custom lifecycle management).
   * Callers that require per-request isolation should either construct a
   * fresh KVCacheHandler per request or invoke this method explicitly.
   */
  resetRequestCache(): void;
  /**
   * Fire a KV delete in the background.
   * Prefers the per-request ExecutionContext from ALS (set by
   * runWithExecutionContext in the worker entry) so that background KV
   * operations are registered with the correct request's waitUntil().
   * Falls back to the constructor-provided ctx for callers that set it
   * explicitly, and to fire-and-forget when neither is available (Node.js dev).
   */
  private _deleteInBackground;
  /**
   * Execute a KV put and return the promise so callers can await completion.
   * Also registers with ctx.waitUntil() so the Workers runtime keeps the
   * isolate alive even if the caller does not await the returned promise.
   */
  private _put;
}
//#endregion
export { ENTRY_PREFIX, KVCacheHandler };
//# sourceMappingURL=kv-cache-handler.d.ts.map