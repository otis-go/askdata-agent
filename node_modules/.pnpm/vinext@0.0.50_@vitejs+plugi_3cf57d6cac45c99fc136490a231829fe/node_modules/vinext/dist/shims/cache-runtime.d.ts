import { CacheLifeConfig } from "./cache.js";
import * as _$node_async_hooks0 from "node:async_hooks";

//#region src/shims/cache-runtime.d.ts
type CacheContext = {
  /** Tags collected via cacheTag() during execution */tags: string[]; /** Cache life configs collected via cacheLife() — minimum-wins rule applies */
  lifeConfigs: CacheLifeConfig[]; /** Cache variant: "default" | "remote" | "private" */
  variant: string;
};
declare const cacheContextStorage: _$node_async_hooks0.AsyncLocalStorage<CacheContext>;
/**
 * Get the current cache context. Returns null if not inside a "use cache" function.
 */
declare function getCacheContext(): CacheContext | null;
/**
 * Convert an encodeReply result (string | FormData) to a cache key string.
 * For FormData (binary args), produces a deterministic SHA-256 hash over
 * the sorted entries. We can't hash `new Response(formData).arrayBuffer()`
 * because multipart boundaries are non-deterministic across serializations.
 *
 * Exported for testing.
 */
declare function replyToCacheKey(reply: string | FormData): Promise<string>;
type PrivateCacheState = {
  _privateCache: Map<string, unknown> | null;
};
/**
 * Run a function within a private cache ALS scope.
 * Ensures per-request isolation for "use cache: private" entries
 * on concurrent runtimes.
 */
declare function runWithPrivateCache<T>(fn: () => Promise<T>): Promise<T>;
declare function runWithPrivateCache<T>(fn: () => T | Promise<T>): T | Promise<T>;
/**
 * Clear the private per-request cache. Should be called at the start of each request.
 * Only needed when not using runWithPrivateCache() (legacy path).
 */
declare function clearPrivateCache(): void;
/**
 * Register a function as a cached function. This is called by the Vite
 * transform for each "use cache" function.
 *
 * @param fn - The original async function
 * @param id - A stable identifier for the function (module path + export name)
 * @param variant - Cache variant: "" (default/shared), "remote", "private"
 * @returns A wrapper function that checks cache before calling the original
 */
declare function registerCachedFunction<T extends (...args: any[]) => Promise<any>>(fn: T, id: string, variant?: string): T;
//#endregion
export { CacheContext, PrivateCacheState, cacheContextStorage, clearPrivateCache, getCacheContext, registerCachedFunction, replyToCacheKey, runWithPrivateCache };
//# sourceMappingURL=cache-runtime.d.ts.map