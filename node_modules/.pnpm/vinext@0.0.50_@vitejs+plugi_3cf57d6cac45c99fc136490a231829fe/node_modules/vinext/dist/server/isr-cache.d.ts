import { CacheHandlerValue, CachedAppPageValue, CachedPagesValue, IncrementalCacheValue } from "../shims/cache.js";
import { OnRequestErrorContext } from "./instrumentation.js";
import { normalizeMountedSlotsHeader } from "./app-mounted-slots-header.js";
import { AppRscRenderMode } from "./app-rsc-render-mode.js";

//#region src/server/isr-cache.d.ts
type ISRCacheEntry = {
  value: CacheHandlerValue;
  isStale: boolean;
};
/**
 * Get a cache entry with staleness information.
 *
 * Returns { value, isStale: false } for fresh entries,
 * { value, isStale: true } for expired-but-usable entries,
 * or null for cache misses.
 */
declare function isrGet(key: string): Promise<ISRCacheEntry | null>;
/**
 * Store a value in the ISR cache with a revalidation period.
 */
declare function isrSet(key: string, data: IncrementalCacheValue, revalidateSeconds: number, tags?: string[], expireSeconds?: number): Promise<void>;
/**
 * Trigger a background regeneration for a cache key.
 *
 * If a regeneration for this key is already in progress, this is a no-op.
 * The renderFn should produce the new cache value and call isrSet internally.
 *
 * On Cloudflare Workers the regeneration promise is registered with
 * `ctx.waitUntil()` via the ALS-backed ExecutionContext, keeping the isolate
 * alive until the regeneration completes even after the Response is returned.
 *
 * When `errorContext` is provided and the render function fails, the error
 * is reported via `reportRequestError` (instrumentation hook) with
 * `revalidateReason: "stale"`.
 */
declare function triggerBackgroundRegeneration(key: string, renderFn: () => Promise<void>, errorContext?: {
  routerKind: OnRequestErrorContext["routerKind"];
  routePath: string;
  routeType: OnRequestErrorContext["routeType"];
}): void;
/**
 * Build a CachedPagesValue for the Pages Router ISR cache.
 */
declare function buildPagesCacheValue(html: string, pageData: object, status?: number): CachedPagesValue;
/**
 * Build a CachedAppPageValue for the App Router ISR cache.
 */
declare function buildAppPageCacheValue(html: string, rscData?: ArrayBuffer, status?: number): CachedAppPageValue;
/**
 * Compute an ISR cache key for a given router type and pathname.
 * Long pathnames are hashed to stay within KV key-length limits (512 bytes).
 */
declare function isrCacheKey(router: "pages" | "app", pathname: string, buildId?: string): string;
declare function appIsrHtmlKey(pathname: string): string;
/**
 * Build the ISR cache key for an RSC payload.
 *
 * Note: the key format changed from `rsc:<hash>` to `rsc:slots:<hash>` (and
 * optionally `rsc:slots:<hash>:preserve-ui`). Existing cached entries under
 * the old format will become unreachable after deployment. This is acceptable
 * because ISR entries have TTLs and will be regenerated on the next request.
 */
declare function appIsrRscKey(pathname: string, mountedSlotsHeader?: string | null, renderMode?: AppRscRenderMode): string;
declare function appIsrRouteKey(pathname: string): string;
/**
 * Store the revalidate duration for a cache key.
 * Uses insertion-order LRU eviction to prevent unbounded growth.
 */
declare function setRevalidateDuration(key: string, seconds: number): void;
/**
 * Get the revalidate duration for a cache key.
 */
declare function getRevalidateDuration(key: string): number | undefined;
//#endregion
export { ISRCacheEntry, appIsrHtmlKey, appIsrRouteKey, appIsrRscKey, buildAppPageCacheValue, buildPagesCacheValue, getRevalidateDuration, isrCacheKey, isrGet, isrSet, normalizeMountedSlotsHeader, setRevalidateDuration, triggerBackgroundRegeneration };
//# sourceMappingURL=isr-cache.d.ts.map