import { stripBasePath } from "../utils/base-path.js";
import { VINEXT_MOUNTED_SLOTS_HEADER, VINEXT_PARAMS_HEADER } from "../server/headers.js";
import { assertSafeNavigationUrl } from "./url-safety.js";
import { isHashOnlyBrowserUrlChange, toBrowserNavigationHref, toSameOriginAppPath } from "./url-utils.js";
import { notifyAppRouterTransitionStart } from "../client/instrumentation-client-state.js";
import { AppElementsWire } from "../server/app-elements-wire.js";
import "../server/app-elements.js";
import { createRscRequestHeaders, createRscRequestUrl } from "../server/app-rsc-cache-busting.js";
import { ReadonlyURLSearchParams } from "./readonly-url-search-params.js";
import * as React$1 from "react";
//#region src/shims/navigation.ts
/**
* next/navigation shim
*
* App Router navigation hooks. These work on both server (RSC) and client.
* Server-side: reads from a request context set by the RSC handler.
* Client-side: reads from browser Location API and provides navigation.
*/
const _LAYOUT_SEGMENT_CTX_KEY = Symbol.for("vinext.layoutSegmentContext");
const _SERVER_INSERTED_HTML_CTX_KEY = Symbol.for("vinext.serverInsertedHTMLContext");
function getServerInsertedHTMLContext() {
	if (typeof React$1.createContext !== "function") return null;
	const globalState = globalThis;
	if (!globalState[_SERVER_INSERTED_HTML_CTX_KEY]) globalState[_SERVER_INSERTED_HTML_CTX_KEY] = React$1.createContext(null);
	return globalState[_SERVER_INSERTED_HTML_CTX_KEY] ?? null;
}
const ServerInsertedHTMLContext = getServerInsertedHTMLContext();
/**
* Get or create the layout segment context.
* Returns null in the RSC environment (createContext unavailable).
*/
function getLayoutSegmentContext() {
	if (typeof React$1.createContext !== "function") return null;
	const globalState = globalThis;
	if (!globalState[_LAYOUT_SEGMENT_CTX_KEY]) globalState[_LAYOUT_SEGMENT_CTX_KEY] = React$1.createContext({ children: [] });
	return globalState[_LAYOUT_SEGMENT_CTX_KEY] ?? null;
}
/**
* Read the child segments for a parallel route below the current layout.
* Returns [] if no context is available (RSC environment, outside React tree)
* or if the requested key is not present in the segment map.
*/
function useChildSegments(parallelRoutesKey = "children") {
	const ctx = getLayoutSegmentContext();
	if (!ctx) return [];
	try {
		return React$1.useContext(ctx)[parallelRoutesKey] ?? [];
	} catch {
		return [];
	}
}
const _READONLY_SEARCH_PARAMS = Symbol("vinext.navigation.readonlySearchParams");
const _READONLY_SEARCH_PARAMS_SOURCE = Symbol("vinext.navigation.readonlySearchParamsSource");
const GLOBAL_ACCESSORS_KEY = Symbol.for("vinext.navigation.globalAccessors");
const _GLOBAL_ACCESSORS_KEY = GLOBAL_ACCESSORS_KEY;
const _GLOBAL_HYDRATION_CONTEXT_KEY = Symbol.for("vinext.navigation.clientHydrationContext");
function _getGlobalAccessors() {
	return globalThis[_GLOBAL_ACCESSORS_KEY];
}
function _getClientHydrationContext() {
	const globalState = globalThis;
	if (Object.prototype.hasOwnProperty.call(globalState, _GLOBAL_HYDRATION_CONTEXT_KEY)) return globalState[_GLOBAL_HYDRATION_CONTEXT_KEY] ?? null;
}
function _setClientHydrationContext(ctx) {
	globalThis[_GLOBAL_HYDRATION_CONTEXT_KEY] = ctx;
}
let _serverContext = null;
let _serverInsertedHTMLCallbacks = [];
let _getServerContext = () => {
	if (typeof window !== "undefined") {
		const hydrationContext = _getClientHydrationContext();
		return hydrationContext !== void 0 ? hydrationContext : _serverContext;
	}
	const g = _getGlobalAccessors();
	return g ? g.getServerContext() : _serverContext;
};
let _setServerContext = (ctx) => {
	if (typeof window !== "undefined") {
		_serverContext = ctx;
		_setClientHydrationContext(ctx);
		return;
	}
	const g = _getGlobalAccessors();
	if (g) g.setServerContext(ctx);
	else _serverContext = ctx;
};
let _getInsertedHTMLCallbacks = () => {
	const g = _getGlobalAccessors();
	return g ? g.getInsertedHTMLCallbacks() : _serverInsertedHTMLCallbacks;
};
let _clearInsertedHTMLCallbacks = () => {
	const g = _getGlobalAccessors();
	if (g) g.clearInsertedHTMLCallbacks();
	else _serverInsertedHTMLCallbacks = [];
};
/**
* Register ALS-backed state accessors. Called by navigation-state.ts on import.
* @internal
*/
function _registerStateAccessors(accessors) {
	_getServerContext = accessors.getServerContext;
	_setServerContext = accessors.setServerContext;
	_getInsertedHTMLCallbacks = accessors.getInsertedHTMLCallbacks;
	_clearInsertedHTMLCallbacks = accessors.clearInsertedHTMLCallbacks;
}
/**
* Get the navigation context for the current SSR/RSC render.
* Reads from AsyncLocalStorage when available (concurrent-safe),
* otherwise falls back to module-level state.
*/
function getNavigationContext() {
	return _getServerContext();
}
/**
* Set the navigation context for the current SSR/RSC render.
* Called by the framework entry before rendering each request.
*/
function setNavigationContext(ctx) {
	_setServerContext(ctx);
}
const isServer = typeof window === "undefined";
/** basePath from next.config.js, injected by the plugin at build time */
const __basePath = process.env.__NEXT_ROUTER_BASEPATH ?? "";
/** Maximum number of entries in the RSC prefetch cache. */
const MAX_PREFETCH_CACHE_SIZE = 50;
/** TTL for prefetch cache entries in ms (matches Next.js static prefetch TTL). */
const PREFETCH_CACHE_TTL = 3e4;
function getCurrentInterceptionContext() {
	if (isServer) return null;
	return stripBasePath(window.location.pathname, __basePath);
}
function getCurrentNextUrl() {
	if (isServer) return "/";
	return window.location.pathname + window.location.search;
}
/** Get or create the shared in-memory RSC prefetch cache on window. */
function getPrefetchCache() {
	if (isServer) return /* @__PURE__ */ new Map();
	if (!window.__VINEXT_RSC_PREFETCH_CACHE__) window.__VINEXT_RSC_PREFETCH_CACHE__ = /* @__PURE__ */ new Map();
	return window.__VINEXT_RSC_PREFETCH_CACHE__;
}
/**
* Get or create the shared set of already-prefetched RSC URLs on window.
* Keyed by interception-aware cache key so distinct source routes do not alias.
*/
function getPrefetchedUrls() {
	if (isServer) return /* @__PURE__ */ new Set();
	if (!window.__VINEXT_RSC_PREFETCHED_URLS__) window.__VINEXT_RSC_PREFETCHED_URLS__ = /* @__PURE__ */ new Set();
	return window.__VINEXT_RSC_PREFETCHED_URLS__;
}
/**
* Evict prefetch cache entries if at capacity.
* First sweeps expired entries, then falls back to FIFO eviction.
*/
function evictPrefetchCacheIfNeeded() {
	const cache = getPrefetchCache();
	if (cache.size < 50) return;
	const now = Date.now();
	const prefetched = getPrefetchedUrls();
	for (const [key, entry] of cache) if (now - entry.timestamp >= 3e4) {
		cache.delete(key);
		prefetched.delete(key);
	}
	while (cache.size >= 50) {
		const oldest = cache.keys().next().value;
		if (oldest !== void 0) {
			cache.delete(oldest);
			prefetched.delete(oldest);
		} else break;
	}
}
/**
* Store a prefetched RSC response in the cache by snapshotting it to an
* ArrayBuffer.  The snapshot completes asynchronously; during that window
* the entry is marked `pending` so consumePrefetchResponse() will skip it
* (the caller falls back to a fresh fetch, which is acceptable).
*
* Prefer prefetchRscResponse() for new call-sites — it handles the full
* prefetch lifecycle including dedup and explicit slot context.
* storePrefetchResponse() is kept for backward compatibility and test
* helpers. It is slot-unaware: the snapshot's mountedSlotsHeader comes
* from the response headers, not the caller, so consumePrefetchResponse
* may reject the entry if the caller's slot context differs.
*
* NB: Caller is responsible for managing getPrefetchedUrls() — this
* function only stores the response in the prefetch cache.
*/
function storePrefetchResponse(rscUrl, response, interceptionContext = null) {
	const cacheKey = AppElementsWire.encodeCacheKey(rscUrl, interceptionContext);
	evictPrefetchCacheIfNeeded();
	const entry = {
		outcome: "pending",
		timestamp: Date.now()
	};
	entry.pending = snapshotRscResponse(response).then((snapshot) => {
		entry.snapshot = snapshot;
	}).catch(() => {
		getPrefetchCache().delete(cacheKey);
	}).finally(() => {
		entry.pending = void 0;
		if (entry.snapshot) entry.outcome = "cache-seeded";
	});
	getPrefetchCache().set(cacheKey, entry);
}
/**
* Snapshot an RSC response to an ArrayBuffer for caching and replay.
* Consumes the response body and stores it with content-type and URL metadata.
*/
async function snapshotRscResponse(response) {
	return {
		buffer: await response.arrayBuffer(),
		contentType: response.headers.get("content-type") ?? "text/x-component",
		mountedSlotsHeader: response.headers.get(VINEXT_MOUNTED_SLOTS_HEADER),
		paramsHeader: response.headers.get(VINEXT_PARAMS_HEADER),
		url: response.url
	};
}
/**
* Reconstruct a Response from a cached RSC snapshot.
* Creates a new Response with the original ArrayBuffer so createFromFetch
* can consume the stream from scratch.
*
* NOTE: The reconstructed Response always has `url === ""` — the Response
* constructor does not accept a `url` option, and `response.url` is read-only
* set by the fetch infrastructure. Callers that need the original URL should
* read it from `cached.url` directly rather than from the restored Response.
*
* @param copy - When true (default), copies the ArrayBuffer so the cached
*   snapshot remains replayable (needed for the visited-response cache).
*   Pass false for single-consumption paths (e.g. prefetch cache entries
*   that are deleted after consumption) to avoid the extra allocation.
*/
function restoreRscResponse(cached, copy = true) {
	const headers = new Headers({ "content-type": cached.contentType });
	if (cached.mountedSlotsHeader != null) headers.set(VINEXT_MOUNTED_SLOTS_HEADER, cached.mountedSlotsHeader);
	if (cached.paramsHeader != null) headers.set(VINEXT_PARAMS_HEADER, cached.paramsHeader);
	return new Response(copy ? cached.buffer.slice(0) : cached.buffer, {
		status: 200,
		headers
	});
}
/**
* Prefetch an RSC response and snapshot it for later consumption.
* Stores the in-flight promise so immediate clicks can await it instead
* of firing a duplicate fetch.
* Enforces a maximum cache size to prevent unbounded memory growth on
* link-heavy pages.
*/
function prefetchRscResponse(rscUrl, fetchPromise, interceptionContext = null, mountedSlotsHeader = null) {
	const cacheKey = AppElementsWire.encodeCacheKey(rscUrl, interceptionContext);
	const cache = getPrefetchCache();
	const prefetched = getPrefetchedUrls();
	const entry = {
		outcome: "pending",
		timestamp: Date.now()
	};
	entry.pending = fetchPromise.then(async (response) => {
		if (response.ok) entry.snapshot = {
			...await snapshotRscResponse(response),
			mountedSlotsHeader
		};
		else {
			prefetched.delete(cacheKey);
			cache.delete(cacheKey);
		}
	}).catch(() => {
		prefetched.delete(cacheKey);
		cache.delete(cacheKey);
	}).finally(() => {
		entry.pending = void 0;
		if (entry.snapshot) entry.outcome = "cache-seeded";
	});
	cache.set(cacheKey, entry);
	evictPrefetchCacheIfNeeded();
}
/**
* Consume a prefetched response for a given rscUrl.
* Only returns settled (non-pending) snapshots synchronously.
* Returns null if the entry is still in flight or doesn't exist.
*/
function consumePrefetchResponse(rscUrl, interceptionContext = null, mountedSlotsHeader = null) {
	const cacheKey = AppElementsWire.encodeCacheKey(rscUrl, interceptionContext);
	const cache = getPrefetchCache();
	const entry = cache.get(cacheKey);
	if (!entry) return null;
	if (entry.pending || entry.outcome !== "cache-seeded") return null;
	cache.delete(cacheKey);
	getPrefetchedUrls().delete(cacheKey);
	if (entry.snapshot) {
		if ((entry.snapshot.mountedSlotsHeader ?? null) !== mountedSlotsHeader) return null;
		if (Date.now() - entry.timestamp >= 3e4) return null;
		return entry.snapshot;
	}
	return null;
}
const _CLIENT_NAV_STATE_KEY = Symbol.for("vinext.clientNavigationState");
const _MOUNTED_SLOTS_HEADER_KEY = Symbol.for("vinext.mountedSlotsHeader");
function setMountedSlotsHeader(header) {
	if (isServer) return;
	const globalState = window;
	globalState[_MOUNTED_SLOTS_HEADER_KEY] = header;
}
function getMountedSlotsHeader() {
	if (isServer) return null;
	return window[_MOUNTED_SLOTS_HEADER_KEY] ?? null;
}
function getClientNavigationState() {
	if (isServer) return null;
	const globalState = window;
	globalState[_CLIENT_NAV_STATE_KEY] ??= {
		listeners: /* @__PURE__ */ new Set(),
		cachedSearch: window.location.search,
		cachedReadonlySearchParams: new ReadonlyURLSearchParams(window.location.search),
		cachedPathname: stripBasePath(window.location.pathname, __basePath),
		clientParams: {},
		clientParamsJson: "{}",
		pendingClientParams: null,
		pendingClientParamsJson: null,
		pendingPathname: null,
		pendingPathnameNavId: null,
		originalPushState: window.history.pushState.bind(window.history),
		originalReplaceState: window.history.replaceState.bind(window.history),
		patchInstalled: false,
		hasPendingNavigationUpdate: false,
		suppressUrlNotifyCount: 0,
		navigationSnapshotActiveCount: 0
	};
	return globalState[_CLIENT_NAV_STATE_KEY];
}
function notifyNavigationListeners() {
	const state = getClientNavigationState();
	if (!state) return;
	for (const fn of state.listeners) fn();
}
let _cachedEmptyServerSearchParams = null;
/**
* Get cached pathname snapshot for useSyncExternalStore.
* Note: Returns cached value from ClientNavigationState, not live window.location.
* The cache is updated by syncCommittedUrlStateFromLocation() after navigation commits.
* This ensures referential stability and prevents infinite re-renders.
* External pushState/replaceState while URL notifications are suppressed won't
* be visible until the next commit.
*/
function getPathnameSnapshot() {
	return getClientNavigationState()?.cachedPathname ?? "/";
}
let _cachedEmptyClientSearchParams = null;
/**
* Get cached search params snapshot for useSyncExternalStore.
* Note: Returns cached value from ClientNavigationState, not live window.location.search.
* The cache is updated by syncCommittedUrlStateFromLocation() after navigation commits.
* This ensures referential stability and prevents infinite re-renders.
* External pushState/replaceState while URL notifications are suppressed won't
* be visible until the next commit.
*/
function getSearchParamsSnapshot() {
	const cached = getClientNavigationState()?.cachedReadonlySearchParams;
	if (cached) return cached;
	if (_cachedEmptyClientSearchParams === null) _cachedEmptyClientSearchParams = new ReadonlyURLSearchParams();
	return _cachedEmptyClientSearchParams;
}
function syncCommittedUrlStateFromLocation() {
	const state = getClientNavigationState();
	if (!state) return false;
	let changed = false;
	const pathname = stripBasePath(window.location.pathname, __basePath);
	if (pathname !== state.cachedPathname) {
		state.cachedPathname = pathname;
		changed = true;
	}
	const search = window.location.search;
	if (search !== state.cachedSearch) {
		state.cachedSearch = search;
		state.cachedReadonlySearchParams = new ReadonlyURLSearchParams(search);
		changed = true;
	}
	return changed;
}
function getServerSearchParamsSnapshot() {
	const ctx = _getServerContext();
	if (!ctx) {
		if (_cachedEmptyServerSearchParams === null) _cachedEmptyServerSearchParams = new ReadonlyURLSearchParams();
		return _cachedEmptyServerSearchParams;
	}
	const source = ctx.searchParams;
	const cached = ctx[_READONLY_SEARCH_PARAMS];
	const cachedSource = ctx[_READONLY_SEARCH_PARAMS_SOURCE];
	if (cached && cachedSource === source) return cached;
	const readonly = new ReadonlyURLSearchParams(source);
	ctx[_READONLY_SEARCH_PARAMS] = readonly;
	ctx[_READONLY_SEARCH_PARAMS_SOURCE] = source;
	return readonly;
}
/**
* Mark a navigation snapshot as active. Called before startTransition
* in renderNavigationPayload. While active, hooks prefer the snapshot
* context value over useSyncExternalStore. Uses a counter (not boolean)
* to handle overlapping navigations — rapid clicks can interleave
* activate/deactivate if multiple transitions are in flight.
*/
function activateNavigationSnapshot() {
	const state = getClientNavigationState();
	if (state) state.navigationSnapshotActiveCount++;
}
const _EMPTY_PARAMS = {};
const _CLIENT_NAV_RENDER_CTX_KEY = Symbol.for("vinext.clientNavigationRenderContext");
function getClientNavigationRenderContext() {
	if (typeof React$1.createContext !== "function") return null;
	const globalState = globalThis;
	if (!globalState[_CLIENT_NAV_RENDER_CTX_KEY]) globalState[_CLIENT_NAV_RENDER_CTX_KEY] = React$1.createContext(null);
	return globalState[_CLIENT_NAV_RENDER_CTX_KEY] ?? null;
}
function useClientNavigationRenderSnapshot() {
	const ctx = getClientNavigationRenderContext();
	if (!ctx || typeof React$1.useContext !== "function") return null;
	try {
		return React$1.useContext(ctx);
	} catch {
		return null;
	}
}
function createClientNavigationRenderSnapshot(href, params) {
	const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost";
	const url = new URL(href, origin);
	return {
		pathname: stripBasePath(url.pathname, __basePath),
		searchParams: new ReadonlyURLSearchParams(url.search),
		params
	};
}
let _fallbackClientParams = _EMPTY_PARAMS;
let _fallbackClientParamsJson = "{}";
function setClientParams(params) {
	const state = getClientNavigationState();
	if (!state) {
		const json = JSON.stringify(params);
		if (json !== _fallbackClientParamsJson) {
			_fallbackClientParams = params;
			_fallbackClientParamsJson = json;
		}
		return;
	}
	const json = JSON.stringify(params);
	if (json !== state.clientParamsJson) {
		state.clientParams = params;
		state.clientParamsJson = json;
		state.pendingClientParams = null;
		state.pendingClientParamsJson = null;
		notifyNavigationListeners();
	}
}
function replaceClientParamsWithoutNotify(params) {
	const state = getClientNavigationState();
	if (!state) return;
	const json = JSON.stringify(params);
	if (json !== state.clientParamsJson && json !== state.pendingClientParamsJson) {
		state.pendingClientParams = params;
		state.pendingClientParamsJson = json;
		state.hasPendingNavigationUpdate = true;
	}
}
/** Get the current client params (for testing referential stability). */
function getClientParams() {
	return getClientNavigationState()?.clientParams ?? _fallbackClientParams;
}
/**
* Set the pending pathname for client-side navigation.
* Strips the base path before storing. Associates the pathname with the given navId
* so only that navigation (or a newer one) can clear it.
*/
function setPendingPathname(pathname, navId) {
	const state = getClientNavigationState();
	if (!state) return;
	state.pendingPathname = stripBasePath(pathname, __basePath);
	state.pendingPathnameNavId = navId;
}
/**
* Clear the pending pathname, but only if the given navId matches the one
* that set it, or if pendingPathnameNavId is null (no active owner).
* This prevents superseded navigations from clearing state belonging to newer navigations.
*/
function clearPendingPathname(navId) {
	const state = getClientNavigationState();
	if (!state) return;
	if (state.pendingPathnameNavId === null || state.pendingPathnameNavId === navId) {
		state.pendingPathname = null;
		state.pendingPathnameNavId = null;
	}
}
function getClientParamsSnapshot() {
	return getClientNavigationState()?.clientParams ?? _EMPTY_PARAMS;
}
function getServerParamsSnapshot() {
	return _getServerContext()?.params ?? _EMPTY_PARAMS;
}
function subscribeToNavigation(cb) {
	const state = getClientNavigationState();
	if (!state) return () => {};
	state.listeners.add(cb);
	return () => {
		state.listeners.delete(cb);
	};
}
/**
* Returns the current pathname.
* Server: from request context. Client: from window.location.
*/
function usePathname() {
	if (isServer) return _getServerContext()?.pathname ?? "/";
	const renderSnapshot = useClientNavigationRenderSnapshot();
	const pathname = React$1.useSyncExternalStore(subscribeToNavigation, getPathnameSnapshot, () => _getServerContext()?.pathname ?? "/");
	if (renderSnapshot && (getClientNavigationState()?.navigationSnapshotActiveCount ?? 0) > 0) return renderSnapshot.pathname;
	return pathname;
}
/**
* Returns the current search params as a read-only URLSearchParams.
*/
function useSearchParams() {
	if (isServer) return getServerSearchParamsSnapshot();
	const renderSnapshot = useClientNavigationRenderSnapshot();
	const searchParams = React$1.useSyncExternalStore(subscribeToNavigation, getSearchParamsSnapshot, getServerSearchParamsSnapshot);
	if (renderSnapshot && (getClientNavigationState()?.navigationSnapshotActiveCount ?? 0) > 0) return renderSnapshot.searchParams;
	return searchParams;
}
/**
* Returns the dynamic params for the current route.
*/
function useParams() {
	if (isServer) return _getServerContext()?.params ?? _EMPTY_PARAMS;
	const renderSnapshot = useClientNavigationRenderSnapshot();
	const params = React$1.useSyncExternalStore(subscribeToNavigation, getClientParamsSnapshot, getServerParamsSnapshot);
	if (renderSnapshot && (getClientNavigationState()?.navigationSnapshotActiveCount ?? 0) > 0) return renderSnapshot.params;
	return params;
}
/**
* Check if a href is an external URL (any URL scheme per RFC 3986, or protocol-relative).
*/
function isExternalUrl(href) {
	return /^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith("//");
}
/**
* Check if a href is only a hash change relative to the current URL.
*/
function isHashOnlyChange(href) {
	if (typeof window === "undefined") return false;
	if (href.startsWith("#")) return true;
	return isHashOnlyBrowserUrlChange(href, window.location.href, __basePath);
}
/**
* Scroll to a hash target element, or to the top if no hash.
*/
function scrollToHash(hash) {
	if (!hash || hash === "#") {
		window.scrollTo(0, 0);
		return;
	}
	const id = hash.slice(1);
	const element = document.getElementById(id);
	if (element) element.scrollIntoView({ behavior: "auto" });
}
function withSuppressedUrlNotifications(fn) {
	const state = getClientNavigationState();
	if (!state) return fn();
	state.suppressUrlNotifyCount += 1;
	try {
		return fn();
	} finally {
		state.suppressUrlNotifyCount -= 1;
	}
}
/**
* Commit pending client navigation state to committed snapshots.
*
* navId is optional: callers that don't own pendingPathname (for example,
* superseded pre-paint cleanup) may pass undefined to flush URL/params state
* without clearing pendingPathname owned by the active navigation. Such callers
* must opt in explicitly if they also own an activated render snapshot.
*/
function commitClientNavigationState(navId, options) {
	if (isServer) return;
	const state = getClientNavigationState();
	if (!state) return;
	if ((navId !== void 0 || options?.releaseSnapshot === true) && state.navigationSnapshotActiveCount > 0) state.navigationSnapshotActiveCount -= 1;
	const urlChanged = syncCommittedUrlStateFromLocation();
	if (state.pendingClientParams !== null && state.pendingClientParamsJson !== null) {
		state.clientParams = state.pendingClientParams;
		state.clientParamsJson = state.pendingClientParamsJson;
		state.pendingClientParams = null;
		state.pendingClientParamsJson = null;
	}
	if (state.pendingPathnameNavId === null || navId !== void 0 && state.pendingPathnameNavId === navId) {
		state.pendingPathname = null;
		state.pendingPathnameNavId = null;
	}
	const shouldNotify = urlChanged || state.hasPendingNavigationUpdate;
	state.hasPendingNavigationUpdate = false;
	if (shouldNotify) notifyNavigationListeners();
}
function pushHistoryStateWithoutNotify(data, unused, url) {
	withSuppressedUrlNotifications(() => {
		getClientNavigationState()?.originalPushState.call(window.history, data, unused, url);
	});
}
function replaceHistoryStateWithoutNotify(data, unused, url) {
	withSuppressedUrlNotifications(() => {
		getClientNavigationState()?.originalReplaceState.call(window.history, data, unused, url);
	});
}
/**
* Save the current scroll position into the current history state.
* Called before every navigation to enable scroll restoration on back/forward.
*
* Uses replaceHistoryStateWithoutNotify to avoid triggering the patched
* history.replaceState interception (which would cause spurious re-renders).
*/
function saveScrollPosition() {
	replaceHistoryStateWithoutNotify({
		...window.history.state ?? {},
		__vinext_scrollX: window.scrollX,
		__vinext_scrollY: window.scrollY
	}, "");
}
/**
* Restore scroll position from a history state object (used on popstate).
*
* When an RSC navigation is in flight (back/forward triggers both this
* handler and the browser entry's popstate handler which calls
* __VINEXT_RSC_NAVIGATE__), we must wait for the new content to render
* before scrolling. Otherwise the user sees old content flash at the
* restored scroll position.
*
* This handler fires before the browser entry's popstate handler (because
* navigation.ts is loaded before hydration completes), so we defer via a
* microtask to give the browser entry handler a chance to set
* __VINEXT_RSC_PENDING__. Promise.resolve() schedules a microtask
* that runs after all synchronous event listeners have completed.
*/
function restoreScrollPosition(state) {
	if (state && typeof state === "object" && "__vinext_scrollY" in state) {
		const { __vinext_scrollX: x, __vinext_scrollY: y } = state;
		Promise.resolve().then(() => {
			const pending = window.__VINEXT_RSC_PENDING__ ?? null;
			if (pending) pending.then(() => {
				requestAnimationFrame(() => {
					window.scrollTo(x, y);
				});
			});
			else requestAnimationFrame(() => {
				window.scrollTo(x, y);
			});
		});
	}
}
/**
* Navigate to a URL, handling external URLs, hash-only changes, and RSC navigation.
*/
async function navigateClientSide(href, mode, scroll, programmaticTransition = false) {
	let normalizedHref = href;
	if (isExternalUrl(href)) {
		const localPath = toSameOriginAppPath(href, __basePath);
		if (localPath == null) {
			if (mode === "replace") window.location.replace(href);
			else window.location.assign(href);
			return;
		}
		normalizedHref = localPath;
	}
	const fullHref = toBrowserNavigationHref(normalizedHref, window.location.href, __basePath);
	notifyAppRouterTransitionStart(fullHref, mode);
	if (mode === "push") saveScrollPosition();
	if (isHashOnlyChange(fullHref)) {
		const hash = fullHref.includes("#") ? fullHref.slice(fullHref.indexOf("#")) : "";
		if (mode === "replace") replaceHistoryStateWithoutNotify(null, "", fullHref);
		else pushHistoryStateWithoutNotify(null, "", fullHref);
		commitClientNavigationState();
		if (scroll) scrollToHash(hash);
		return;
	}
	const hashIdx = fullHref.indexOf("#");
	const hash = hashIdx !== -1 ? fullHref.slice(hashIdx) : "";
	if (typeof window.__VINEXT_RSC_NAVIGATE__ === "function") await window.__VINEXT_RSC_NAVIGATE__(fullHref, 0, "navigate", mode, void 0, programmaticTransition);
	else {
		if (mode === "replace") replaceHistoryStateWithoutNotify(null, "", fullHref);
		else pushHistoryStateWithoutNotify(null, "", fullHref);
		commitClientNavigationState();
	}
	if (scroll) if (hash) scrollToHash(hash);
	else window.scrollTo(0, 0);
}
/**
* App Router public router instance. Mirrors Next.js's
* `publicAppRouterInstance` from
* `packages/next/src/client/components/app-router-instance.ts`.
*
* Exported so the App Router browser entry can install it on
* `window.next.router` for Next.js parity (see `client/window-next.ts`).
* Internal callers in this file continue to use `_appRouter` for brevity.
*/
const _appRouter = {
	bfcacheId: "0",
	push(href, options) {
		assertSafeNavigationUrl(href);
		if (isServer) return;
		React$1.startTransition(() => {
			navigateClientSide(href, "push", options?.scroll !== false, true);
		});
	},
	replace(href, options) {
		assertSafeNavigationUrl(href);
		if (isServer) return;
		React$1.startTransition(() => {
			navigateClientSide(href, "replace", options?.scroll !== false, true);
		});
	},
	back() {
		if (isServer) return;
		window.history.back();
	},
	forward() {
		if (isServer) return;
		window.history.forward();
	},
	refresh() {
		if (isServer) return;
		const clearCaches = window.__VINEXT_CLEAR_NAV_CACHES__;
		if (typeof clearCaches === "function") clearCaches();
		const rscNavigate = window.__VINEXT_RSC_NAVIGATE__;
		if (typeof rscNavigate === "function") {
			const navigate = () => {
				rscNavigate(window.location.href, 0, "refresh", void 0, void 0, true);
			};
			React$1.startTransition(navigate);
		}
	},
	prefetch(href) {
		assertSafeNavigationUrl(href);
		if (isServer) return;
		(async () => {
			let prefetchHref = href;
			if (href.startsWith("http://") || href.startsWith("https://") || href.startsWith("//")) {
				const localPath = toSameOriginAppPath(href, __basePath);
				if (localPath == null) return;
				prefetchHref = localPath;
			}
			const fullHref = toBrowserNavigationHref(prefetchHref, window.location.href, __basePath);
			const interceptionContext = getCurrentInterceptionContext();
			const mountedSlotsHeader = getMountedSlotsHeader();
			const headers = createRscRequestHeaders({ interceptionContext });
			if (mountedSlotsHeader) headers.set(VINEXT_MOUNTED_SLOTS_HEADER, mountedSlotsHeader);
			const rscUrl = await createRscRequestUrl(fullHref, headers);
			const cacheKey = AppElementsWire.encodeCacheKey(rscUrl, interceptionContext);
			const prefetched = getPrefetchedUrls();
			if (prefetched.has(cacheKey)) return;
			prefetched.add(cacheKey);
			prefetchRscResponse(rscUrl, fetch(rscUrl, {
				headers,
				credentials: "include",
				priority: "low"
			}), interceptionContext, mountedSlotsHeader);
		})().catch((error) => {
			console.error("[vinext] RSC prefetch setup error:", error);
		});
	}
};
/**
* Public App Router instance, exposed for the browser entry so it can wire
* `window.next.router` to the same singleton returned from `useRouter()`.
*
* Mirrors `publicAppRouterInstance` from Next.js's
* `packages/next/src/client/components/app-router-instance.ts` (line 392).
*/
const appRouterInstance = _appRouter;
/**
* App Router's useRouter — returns push/replace/back/forward/refresh.
* Different from Pages Router's useRouter (next/router).
*
* Returns a stable singleton: the same object reference on every call,
* matching Next.js behavior so components using referential equality
* (e.g. useMemo / useEffect deps, React.memo) don't re-render unnecessarily.
*/
function useRouter() {
	return _appRouter;
}
/**
* Returns the active child segment one level below the layout where it's called.
*
* Returns the first segment from the route tree below this layout, including
* route groups (e.g., "(marketing)") and resolved dynamic params. Returns null
* if at the leaf (no child segments).
*
* @param parallelRoutesKey - Which parallel route to read (default: "children")
*/
function useSelectedLayoutSegment(parallelRoutesKey) {
	const segments = useSelectedLayoutSegments(parallelRoutesKey);
	if (segments.length === 0) return null;
	return parallelRoutesKey === void 0 || parallelRoutesKey === "children" ? segments[0] : segments[segments.length - 1];
}
/**
* Returns all active segments below the layout where it's called.
*
* Each layout in the App Router tree wraps its children with a
* LayoutSegmentProvider whose value is a map of parallel route key to
* segment arrays. The "children" key is the default parallel route.
*
* @param parallelRoutesKey - Which parallel route to read (default: "children")
*/
function useSelectedLayoutSegments(parallelRoutesKey) {
	return useChildSegments(parallelRoutesKey);
}
/**
* useServerInsertedHTML — inject HTML during SSR from client components.
*
* Used by CSS-in-JS libraries (styled-components, emotion, StyleX) to inject
* <style> tags during SSR so styles appear in the initial HTML (no FOUC).
*
* The callback is called once after each SSR render pass. The returned JSX/HTML
* is serialized and injected into the HTML stream.
*
* Usage (in a "use client" component wrapping children):
*   useServerInsertedHTML(() => {
*     const styles = sheet.getStyleElement();
*     sheet.instance.clearTag();
*     return <>{styles}</>;
*   });
*/
function useServerInsertedHTML(callback) {
	if (typeof document !== "undefined") return;
	_getInsertedHTMLCallbacks().push(callback);
}
/**
* Flush all collected useServerInsertedHTML callbacks.
* Returns an array of results (React elements or strings).
* Clears the callback list so the next render starts fresh.
*
* Called by the SSR entry after renderToReadableStream completes.
*/
function flushServerInsertedHTML() {
	const callbacks = _getInsertedHTMLCallbacks();
	const results = [];
	for (const cb of callbacks) try {
		const result = cb();
		if (result != null) results.push(result);
	} catch {}
	callbacks.length = 0;
	return results;
}
/**
* Render collected useServerInsertedHTML callbacks without unregistering them.
*
* Streaming SSR needs to invoke the same style-registry callbacks after each
* Fizz flush. Libraries such as styled-components and Emotion clear their own
* per-flush buffers inside the callback; the registration itself must survive
* until the request stream is closed.
*/
function renderServerInsertedHTML() {
	const callbacks = _getInsertedHTMLCallbacks();
	const results = [];
	for (const cb of callbacks) try {
		const result = cb();
		if (result != null) results.push(result);
	} catch {}
	return results;
}
/**
* Clear all collected useServerInsertedHTML callbacks without flushing.
* Used for cleanup between requests.
*/
function clearServerInsertedHTML() {
	_clearInsertedHTMLCallbacks();
}
/**
* HTTP Access Fallback error code — shared prefix for notFound/forbidden/unauthorized.
* Matches Next.js 16's unified error handling approach.
*/
const HTTP_ERROR_FALLBACK_ERROR_CODE = "NEXT_HTTP_ERROR_FALLBACK";
/**
* Check if an error is an HTTP Access Fallback error (notFound, forbidden, unauthorized).
*/
function isHTTPAccessFallbackError(error) {
	if (error && typeof error === "object" && "digest" in error) {
		const digest = String(error.digest);
		return digest === "NEXT_NOT_FOUND" || digest.startsWith(`NEXT_HTTP_ERROR_FALLBACK;`);
	}
	return false;
}
/**
* Extract the HTTP status code from an HTTP Access Fallback error.
* Returns 404 for legacy NEXT_NOT_FOUND errors.
*/
function getAccessFallbackHTTPStatus(error) {
	if (error && typeof error === "object" && "digest" in error) {
		const digest = String(error.digest);
		if (digest === "NEXT_NOT_FOUND") return 404;
		if (digest.startsWith(`NEXT_HTTP_ERROR_FALLBACK;`)) return parseInt(digest.split(";")[1], 10);
	}
	return 404;
}
/**
* Enum matching Next.js RedirectType for type-safe redirect calls.
*/
let RedirectType = /* @__PURE__ */ function(RedirectType) {
	RedirectType["push"] = "push";
	RedirectType["replace"] = "replace";
	return RedirectType;
}({});
/**
* Internal error class used by redirect/notFound/forbidden/unauthorized.
* The `digest` field is the serialised control-flow signal read by the
* framework's error boundary and server-side request handlers.
*/
var VinextNavigationError = class extends Error {
	digest;
	constructor(message, digest) {
		super(message);
		this.digest = digest;
	}
};
/**
* Throw a redirect. Caught by the framework to send a redirect response.
*
* When `type` is omitted, the digest carries an empty sentinel so the
* catch site can resolve the default based on context:
* - Server Action context → "push"  (Back button works after form submission)
* - SSR render context    → "replace"
*
* This matches Next.js behavior where `redirect()` checks
* `actionAsyncStorage.getStore()?.isAction` at call time.
*
* @see https://github.com/vercel/next.js/blob/canary/packages/next/src/client/components/redirect.ts
*/
function redirect(url, type) {
	throw new VinextNavigationError(`NEXT_REDIRECT:${url}`, `NEXT_REDIRECT;${type ?? ""};${encodeURIComponent(url)}`);
}
/**
* Trigger a permanent redirect (308).
*
* Accepts an optional `type` parameter matching Next.js's signature.
* Defaults to "replace" (not context-dependent like `redirect()`).
*
* @see https://github.com/vercel/next.js/blob/canary/packages/next/src/client/components/redirect.ts
*/
function permanentRedirect(url, type = "replace") {
	throw new VinextNavigationError(`NEXT_REDIRECT:${url}`, `NEXT_REDIRECT;${type};${encodeURIComponent(url)};308`);
}
/**
* Trigger a not-found response (404). Caught by the framework.
*/
function notFound() {
	throw new VinextNavigationError("NEXT_NOT_FOUND", `${HTTP_ERROR_FALLBACK_ERROR_CODE};404`);
}
/**
* Trigger a forbidden response (403). Caught by the framework.
* In Next.js, this is gated behind experimental.authInterrupts — we
* support it unconditionally for maximum compatibility.
*/
function forbidden() {
	throw new VinextNavigationError("NEXT_FORBIDDEN", `${HTTP_ERROR_FALLBACK_ERROR_CODE};403`);
}
/**
* Trigger an unauthorized response (401). Caught by the framework.
* In Next.js, this is gated behind experimental.authInterrupts — we
* support it unconditionally for maximum compatibility.
*/
function unauthorized() {
	throw new VinextNavigationError("NEXT_UNAUTHORIZED", `${HTTP_ERROR_FALLBACK_ERROR_CODE};401`);
}
if (!isServer) {
	const state = getClientNavigationState();
	if (state && !state.patchInstalled) {
		state.patchInstalled = true;
		window.addEventListener("popstate", (event) => {
			if (typeof window.__VINEXT_RSC_NAVIGATE__ !== "function") {
				commitClientNavigationState();
				restoreScrollPosition(event.state);
			}
		});
		window.history.pushState = function patchedPushState(data, unused, url) {
			state.originalPushState.call(window.history, data, unused, url);
			if (state.suppressUrlNotifyCount === 0) commitClientNavigationState();
		};
		window.history.replaceState = function patchedReplaceState(data, unused, url) {
			state.originalReplaceState.call(window.history, data, unused, url);
			if (state.suppressUrlNotifyCount === 0) commitClientNavigationState();
		};
	}
}
//#endregion
export { GLOBAL_ACCESSORS_KEY, HTTP_ERROR_FALLBACK_ERROR_CODE, MAX_PREFETCH_CACHE_SIZE, PREFETCH_CACHE_TTL, ReadonlyURLSearchParams, RedirectType, ServerInsertedHTMLContext, __basePath, _registerStateAccessors, activateNavigationSnapshot, appRouterInstance, clearPendingPathname, clearServerInsertedHTML, commitClientNavigationState, consumePrefetchResponse, createClientNavigationRenderSnapshot, flushServerInsertedHTML, forbidden, getAccessFallbackHTTPStatus, getClientNavigationRenderContext, getClientNavigationState, getClientParams, getCurrentInterceptionContext, getCurrentNextUrl, getLayoutSegmentContext, getMountedSlotsHeader, getNavigationContext, getPrefetchCache, getPrefetchedUrls, isHTTPAccessFallbackError, navigateClientSide, notFound, permanentRedirect, prefetchRscResponse, pushHistoryStateWithoutNotify, redirect, renderServerInsertedHTML, replaceClientParamsWithoutNotify, replaceHistoryStateWithoutNotify, restoreRscResponse, setClientParams, setMountedSlotsHeader, setNavigationContext, setPendingPathname, snapshotRscResponse, storePrefetchResponse, unauthorized, useParams, usePathname, useRouter, useSearchParams, useSelectedLayoutSegment, useSelectedLayoutSegments, useServerInsertedHTML };

//# sourceMappingURL=navigation.js.map