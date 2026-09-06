import { getRequestExecutionContext } from "../shims/request-context.js";
import { reportRequestError } from "./instrumentation.js";
import { fnv1a64 } from "../utils/hash.js";
import { getCacheHandler } from "../shims/cache.js";
import { normalizeMountedSlotsHeader } from "./app-mounted-slots-header.js";
import { APP_RSC_RENDER_MODE_NAVIGATION, shouldUsePreserveUiCacheVariant } from "./app-rsc-render-mode.js";
//#region src/server/isr-cache.ts
/**
* ISR (Incremental Static Regeneration) cache layer.
*
* Wraps the pluggable CacheHandler with stale-while-revalidate semantics:
* - Fresh hit: serve immediately
* - Stale hit: serve immediately + trigger background regeneration
* - Miss: render synchronously, cache, serve
*
* Background regeneration is deduped — only one regeneration per cache key
* runs at a time, preventing thundering herd on popular pages.
*
* This layer works with any CacheHandler backend (memory, Redis, KV, etc.)
* because it only uses the standard get/set interface.
*/
/**
* Get a cache entry with staleness information.
*
* Returns { value, isStale: false } for fresh entries,
* { value, isStale: true } for expired-but-usable entries,
* or null for cache misses.
*/
async function isrGet(key) {
	const result = await getCacheHandler().get(key);
	if (!result || !result.value) return null;
	if (result.cacheState === "expired") return null;
	return {
		value: result,
		isStale: result.cacheState === "stale"
	};
}
/**
* Store a value in the ISR cache with a revalidation period.
*/
async function isrSet(key, data, revalidateSeconds, tags, expireSeconds) {
	await getCacheHandler().set(key, data, {
		cacheControl: expireSeconds === void 0 ? { revalidate: revalidateSeconds } : {
			revalidate: revalidateSeconds,
			expire: expireSeconds
		},
		revalidate: revalidateSeconds,
		tags: tags ?? []
	});
}
const _PENDING_REGEN_KEY = Symbol.for("vinext.isrCache.pendingRegenerations");
const _g = globalThis;
const pendingRegenerations = _g[_PENDING_REGEN_KEY] ??= /* @__PURE__ */ new Map();
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
function triggerBackgroundRegeneration(key, renderFn, errorContext) {
	if (pendingRegenerations.has(key)) return;
	const promise = renderFn().catch((err) => {
		console.error(`[vinext] ISR background regeneration failed for ${key}:`, err);
		if (errorContext) reportRequestError(err instanceof Error ? err : new Error(String(err)), {
			path: key,
			method: "GET",
			headers: {}
		}, {
			routerKind: errorContext.routerKind,
			routePath: errorContext.routePath,
			routeType: errorContext.routeType,
			revalidateReason: "stale"
		});
	}).finally(() => {
		pendingRegenerations.delete(key);
	});
	pendingRegenerations.set(key, promise);
	getRequestExecutionContext()?.waitUntil(promise);
}
/**
* Build a CachedPagesValue for the Pages Router ISR cache.
*/
function buildPagesCacheValue(html, pageData, status) {
	return {
		kind: "PAGES",
		html,
		pageData,
		headers: void 0,
		status
	};
}
/**
* Build a CachedAppPageValue for the App Router ISR cache.
*/
function buildAppPageCacheValue(html, rscData, status) {
	return {
		kind: "APP_PAGE",
		html,
		rscData,
		headers: void 0,
		postponed: void 0,
		status
	};
}
function normalizeCachePathname(pathname) {
	return pathname === "/" ? "/" : pathname.replace(/\/$/, "");
}
function buildCacheKey(prefix, pathname, suffix) {
	const normalized = normalizeCachePathname(pathname);
	const suffixPart = suffix ? `:${suffix}` : "";
	const key = `${prefix}:${normalized}${suffixPart}`;
	if (key.length <= 200) return key;
	return `${prefix}:__hash:${fnv1a64(normalized)}${suffixPart}`;
}
/**
* Compute an ISR cache key for a given router type and pathname.
* Long pathnames are hashed to stay within KV key-length limits (512 bytes).
*/
function isrCacheKey(router, pathname, buildId) {
	return buildCacheKey(buildId ? `${router}:${buildId}` : router, pathname);
}
/**
* Compute an App Router ISR key for one cache artifact.
*
* App pages store HTML, RSC payloads, and route-handler responses separately.
* The suffix mirrors Next.js's separate on-disk app artifacts while keeping the
* Cloudflare KV key under its 512-byte limit for long pathnames.
*/
function appIsrCacheKey(pathname, suffix, buildId = process.env.__VINEXT_BUILD_ID) {
	return buildCacheKey(buildId ? `app:${buildId}` : "app", pathname, suffix);
}
function appIsrHtmlKey(pathname) {
	return appIsrCacheKey(pathname, "html");
}
/**
* Build the ISR cache key for an RSC payload.
*
* Note: the key format changed from `rsc:<hash>` to `rsc:slots:<hash>` (and
* optionally `rsc:slots:<hash>:preserve-ui`). Existing cached entries under
* the old format will become unreachable after deployment. This is acceptable
* because ISR entries have TTLs and will be regenerated on the next request.
*/
function appIsrRscKey(pathname, mountedSlotsHeader, renderMode = APP_RSC_RENDER_MODE_NAVIGATION) {
	const normalizedMountedSlotsHeader = normalizeMountedSlotsHeader(mountedSlotsHeader);
	const variant = [normalizedMountedSlotsHeader ? `slots:${fnv1a64(normalizedMountedSlotsHeader)}` : null, shouldUsePreserveUiCacheVariant(renderMode) ? "preserve-ui" : null].filter((part) => part !== null).join(":");
	return appIsrCacheKey(pathname, variant ? `rsc:${variant}` : "rsc");
}
function appIsrRouteKey(pathname) {
	return appIsrCacheKey(pathname, "route");
}
const MAX_REVALIDATE_ENTRIES = 1e4;
const _REVALIDATE_KEY = Symbol.for("vinext.isrCache.revalidateDurations");
const revalidateDurations = _g[_REVALIDATE_KEY] ??= /* @__PURE__ */ new Map();
/**
* Store the revalidate duration for a cache key.
* Uses insertion-order LRU eviction to prevent unbounded growth.
*/
function setRevalidateDuration(key, seconds) {
	revalidateDurations.delete(key);
	revalidateDurations.set(key, seconds);
	while (revalidateDurations.size > MAX_REVALIDATE_ENTRIES) {
		const first = revalidateDurations.keys().next().value;
		if (first !== void 0) revalidateDurations.delete(first);
		else break;
	}
}
/**
* Get the revalidate duration for a cache key.
*/
function getRevalidateDuration(key) {
	return revalidateDurations.get(key);
}
//#endregion
export { appIsrHtmlKey, appIsrRouteKey, appIsrRscKey, buildAppPageCacheValue, buildPagesCacheValue, getRevalidateDuration, isrCacheKey, isrGet, isrSet, normalizeMountedSlotsHeader, setRevalidateDuration, triggerBackgroundRegeneration };

//# sourceMappingURL=isr-cache.js.map