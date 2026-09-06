//#region src/server/cache-control.ts
const NEVER_CACHE_CONTROL = "private, no-cache, no-store, max-age=0, must-revalidate";
const STATIC_CACHE_CONTROL = "s-maxage=31536000, stale-while-revalidate";
const STALE_REVALIDATE_CACHE_CONTROL = "s-maxage=0, stale-while-revalidate";
const NO_STORE_CACHE_CONTROL = "no-store, must-revalidate";
/**
* Matches Next.js's `getCacheControlHeader` stale window semantics while
* preserving vinext's legacy unbounded SWR header when no expire ceiling is
* available yet.
*
* Next.js source:
* https://github.com/vercel/next.js/blob/canary/packages/next/src/server/lib/cache-control.ts
*/
function buildRevalidateCacheControl(revalidateSeconds, expireSeconds) {
	if (expireSeconds === void 0) return `s-maxage=${revalidateSeconds}, stale-while-revalidate`;
	if (revalidateSeconds >= expireSeconds) return `s-maxage=${revalidateSeconds}`;
	return `s-maxage=${revalidateSeconds}, stale-while-revalidate=${expireSeconds - revalidateSeconds}`;
}
/**
* Builds Cache-Control for ISR cache reads. HIT responses and STALE responses
* with stored expire metadata use the same route policy because Next.js derives
* this header from cache-control metadata, not from the cache hit/stale state.
* STALE entries without expire metadata keep vinext's legacy `s-maxage=0`
* fallback so older cache entries are not treated as newly fresh downstream.
*/
function buildCachedRevalidateCacheControl(cacheState, revalidateSeconds, expireSeconds) {
	if (revalidateSeconds === Infinity) return STATIC_CACHE_CONTROL;
	if (cacheState === "STALE" && expireSeconds === void 0) return STALE_REVALIDATE_CACHE_CONTROL;
	return buildRevalidateCacheControl(revalidateSeconds, expireSeconds);
}
//#endregion
export { NEVER_CACHE_CONTROL, NO_STORE_CACHE_CONTROL, STATIC_CACHE_CONTROL, buildCachedRevalidateCacheControl, buildRevalidateCacheControl };

//# sourceMappingURL=cache-control.js.map