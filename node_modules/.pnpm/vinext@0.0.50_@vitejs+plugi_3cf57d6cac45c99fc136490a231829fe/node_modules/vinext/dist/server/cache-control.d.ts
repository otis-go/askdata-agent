//#region src/server/cache-control.d.ts
declare const NEVER_CACHE_CONTROL = "private, no-cache, no-store, max-age=0, must-revalidate";
declare const STATIC_CACHE_CONTROL = "s-maxage=31536000, stale-while-revalidate";
declare const NO_STORE_CACHE_CONTROL = "no-store, must-revalidate";
/**
 * Matches Next.js's `getCacheControlHeader` stale window semantics while
 * preserving vinext's legacy unbounded SWR header when no expire ceiling is
 * available yet.
 *
 * Next.js source:
 * https://github.com/vercel/next.js/blob/canary/packages/next/src/server/lib/cache-control.ts
 */
declare function buildRevalidateCacheControl(revalidateSeconds: number, expireSeconds?: number): string;
/**
 * Builds Cache-Control for ISR cache reads. HIT responses and STALE responses
 * with stored expire metadata use the same route policy because Next.js derives
 * this header from cache-control metadata, not from the cache hit/stale state.
 * STALE entries without expire metadata keep vinext's legacy `s-maxage=0`
 * fallback so older cache entries are not treated as newly fresh downstream.
 */
declare function buildCachedRevalidateCacheControl(cacheState: "HIT" | "STALE", revalidateSeconds: number, expireSeconds?: number): string;
//#endregion
export { NEVER_CACHE_CONTROL, NO_STORE_CACHE_CONTROL, STATIC_CACHE_CONTROL, buildCachedRevalidateCacheControl, buildRevalidateCacheControl };
//# sourceMappingURL=cache-control.d.ts.map