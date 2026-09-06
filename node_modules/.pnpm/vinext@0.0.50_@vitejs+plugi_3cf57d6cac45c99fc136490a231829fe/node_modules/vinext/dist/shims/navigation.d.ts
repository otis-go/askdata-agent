import { ReadonlyURLSearchParams } from "./readonly-url-search-params.js";
import * as React$1 from "react";

//#region src/shims/navigation.d.ts
/**
 * Map of parallel route key → child segments below the current layout.
 * The "children" key is always present (the default parallel route).
 * Named parallel routes add their own keys (e.g., "team", "analytics").
 *
 * Arrays are mutable (`string[]`) to match Next.js's public API return type
 * without requiring `as` casts. The map itself is Readonly — no key addition.
 */
type SegmentMap = Readonly<Record<string, string[]>> & {
  readonly children: string[];
};
declare const ServerInsertedHTMLContext: React$1.Context<((callback: () => unknown) => void) | null> | null;
/**
 * Get or create the layout segment context.
 * Returns null in the RSC environment (createContext unavailable).
 */
declare function getLayoutSegmentContext(): React$1.Context<SegmentMap> | null;
type NavigationContext = {
  pathname: string;
  searchParams: URLSearchParams;
  params: Record<string, string | string[]>;
};
type _StateAccessors = {
  getServerContext: () => NavigationContext | null;
  setServerContext: (ctx: NavigationContext | null) => void;
  getInsertedHTMLCallbacks: () => Array<() => unknown>;
  clearInsertedHTMLCallbacks: () => void;
};
declare const GLOBAL_ACCESSORS_KEY: unique symbol;
/**
 * Register ALS-backed state accessors. Called by navigation-state.ts on import.
 * @internal
 */
declare function _registerStateAccessors(accessors: _StateAccessors): void;
/**
 * Get the navigation context for the current SSR/RSC render.
 * Reads from AsyncLocalStorage when available (concurrent-safe),
 * otherwise falls back to module-level state.
 */
declare function getNavigationContext(): NavigationContext | null;
/**
 * Set the navigation context for the current SSR/RSC render.
 * Called by the framework entry before rendering each request.
 */
declare function setNavigationContext(ctx: NavigationContext | null): void;
/** basePath from next.config.js, injected by the plugin at build time */
declare const __basePath: string;
/** Maximum number of entries in the RSC prefetch cache. */
declare const MAX_PREFETCH_CACHE_SIZE = 50;
/** TTL for prefetch cache entries in ms (matches Next.js static prefetch TTL). */
declare const PREFETCH_CACHE_TTL = 30000;
/** A buffered RSC response stored as an ArrayBuffer for replay. */
type CachedRscResponse = {
  buffer: ArrayBuffer;
  contentType: string;
  mountedSlotsHeader?: string | null;
  paramsHeader: string | null;
  url: string;
};
type PrefetchCacheEntry = {
  outcome: "pending" | "cache-seeded";
  snapshot?: CachedRscResponse;
  pending?: Promise<void>;
  timestamp: number;
};
declare function getCurrentInterceptionContext(): string | null;
declare function getCurrentNextUrl(): string;
/** Get or create the shared in-memory RSC prefetch cache on window. */
declare function getPrefetchCache(): Map<string, PrefetchCacheEntry>;
/**
 * Get or create the shared set of already-prefetched RSC URLs on window.
 * Keyed by interception-aware cache key so distinct source routes do not alias.
 */
declare function getPrefetchedUrls(): Set<string>;
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
declare function storePrefetchResponse(rscUrl: string, response: Response, interceptionContext?: string | null): void;
/**
 * Snapshot an RSC response to an ArrayBuffer for caching and replay.
 * Consumes the response body and stores it with content-type and URL metadata.
 */
declare function snapshotRscResponse(response: Response): Promise<CachedRscResponse>;
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
declare function restoreRscResponse(cached: CachedRscResponse, copy?: boolean): Response;
/**
 * Prefetch an RSC response and snapshot it for later consumption.
 * Stores the in-flight promise so immediate clicks can await it instead
 * of firing a duplicate fetch.
 * Enforces a maximum cache size to prevent unbounded memory growth on
 * link-heavy pages.
 */
declare function prefetchRscResponse(rscUrl: string, fetchPromise: Promise<Response>, interceptionContext?: string | null, mountedSlotsHeader?: string | null): void;
/**
 * Consume a prefetched response for a given rscUrl.
 * Only returns settled (non-pending) snapshots synchronously.
 * Returns null if the entry is still in flight or doesn't exist.
 */
declare function consumePrefetchResponse(rscUrl: string, interceptionContext?: string | null, mountedSlotsHeader?: string | null): CachedRscResponse | null;
type NavigationListener = () => void;
type ClientNavigationState = {
  listeners: Set<NavigationListener>;
  cachedSearch: string;
  cachedReadonlySearchParams: ReadonlyURLSearchParams;
  cachedPathname: string;
  clientParams: Record<string, string | string[]>;
  clientParamsJson: string;
  pendingClientParams: Record<string, string | string[]> | null;
  pendingClientParamsJson: string | null;
  pendingPathname: string | null;
  pendingPathnameNavId: number | null;
  originalPushState: typeof window.history.pushState;
  originalReplaceState: typeof window.history.replaceState;
  patchInstalled: boolean;
  hasPendingNavigationUpdate: boolean;
  suppressUrlNotifyCount: number;
  navigationSnapshotActiveCount: number;
};
type CommitClientNavigationStateOptions = {
  releaseSnapshot?: boolean;
};
declare function setMountedSlotsHeader(header: string | null): void;
declare function getMountedSlotsHeader(): string | null;
declare function getClientNavigationState(): ClientNavigationState | null;
/**
 * Mark a navigation snapshot as active. Called before startTransition
 * in renderNavigationPayload. While active, hooks prefer the snapshot
 * context value over useSyncExternalStore. Uses a counter (not boolean)
 * to handle overlapping navigations — rapid clicks can interleave
 * activate/deactivate if multiple transitions are in flight.
 */
declare function activateNavigationSnapshot(): void;
type ClientNavigationRenderSnapshot = {
  pathname: string;
  searchParams: ReadonlyURLSearchParams;
  params: Record<string, string | string[]>;
};
declare function getClientNavigationRenderContext(): React$1.Context<ClientNavigationRenderSnapshot | null> | null;
declare function createClientNavigationRenderSnapshot(href: string, params: Record<string, string | string[]>): ClientNavigationRenderSnapshot;
declare function setClientParams(params: Record<string, string | string[]>): void;
declare function replaceClientParamsWithoutNotify(params: Record<string, string | string[]>): void;
/** Get the current client params (for testing referential stability). */
declare function getClientParams(): Record<string, string | string[]>;
/**
 * Set the pending pathname for client-side navigation.
 * Strips the base path before storing. Associates the pathname with the given navId
 * so only that navigation (or a newer one) can clear it.
 */
declare function setPendingPathname(pathname: string, navId: number): void;
/**
 * Clear the pending pathname, but only if the given navId matches the one
 * that set it, or if pendingPathnameNavId is null (no active owner).
 * This prevents superseded navigations from clearing state belonging to newer navigations.
 */
declare function clearPendingPathname(navId: number): void;
/**
 * Returns the current pathname.
 * Server: from request context. Client: from window.location.
 */
declare function usePathname(): string;
/**
 * Returns the current search params as a read-only URLSearchParams.
 */
declare function useSearchParams(): ReadonlyURLSearchParams;
/**
 * Returns the dynamic params for the current route.
 */
declare function useParams<T extends Record<string, string | string[]> = Record<string, string | string[]>>(): T;
/**
 * Commit pending client navigation state to committed snapshots.
 *
 * navId is optional: callers that don't own pendingPathname (for example,
 * superseded pre-paint cleanup) may pass undefined to flush URL/params state
 * without clearing pendingPathname owned by the active navigation. Such callers
 * must opt in explicitly if they also own an activated render snapshot.
 */
declare function commitClientNavigationState(navId?: number, options?: CommitClientNavigationStateOptions): void;
declare function pushHistoryStateWithoutNotify(data: unknown, unused: string, url?: string | URL | null): void;
declare function replaceHistoryStateWithoutNotify(data: unknown, unused: string, url?: string | URL | null): void;
/**
 * Navigate to a URL, handling external URLs, hash-only changes, and RSC navigation.
 */
declare function navigateClientSide(href: string, mode: "push" | "replace", scroll: boolean, programmaticTransition?: boolean): Promise<void>;
/**
 * Public App Router instance, exposed for the browser entry so it can wire
 * `window.next.router` to the same singleton returned from `useRouter()`.
 *
 * Mirrors `publicAppRouterInstance` from Next.js's
 * `packages/next/src/client/components/app-router-instance.ts` (line 392).
 */
declare const appRouterInstance: {
  bfcacheId: string;
  push(href: string, options?: {
    scroll?: boolean;
  }): void;
  replace(href: string, options?: {
    scroll?: boolean;
  }): void;
  back(): void;
  forward(): void;
  refresh(): void;
  prefetch(href: string): void;
};
/**
 * App Router's useRouter — returns push/replace/back/forward/refresh.
 * Different from Pages Router's useRouter (next/router).
 *
 * Returns a stable singleton: the same object reference on every call,
 * matching Next.js behavior so components using referential equality
 * (e.g. useMemo / useEffect deps, React.memo) don't re-render unnecessarily.
 */
declare function useRouter(): {
  bfcacheId: string;
  push(href: string, options?: {
    scroll?: boolean;
  }): void;
  replace(href: string, options?: {
    scroll?: boolean;
  }): void;
  back(): void;
  forward(): void;
  refresh(): void;
  prefetch(href: string): void;
};
/**
 * Returns the active child segment one level below the layout where it's called.
 *
 * Returns the first segment from the route tree below this layout, including
 * route groups (e.g., "(marketing)") and resolved dynamic params. Returns null
 * if at the leaf (no child segments).
 *
 * @param parallelRoutesKey - Which parallel route to read (default: "children")
 */
declare function useSelectedLayoutSegment(parallelRoutesKey?: string): string | null;
/**
 * Returns all active segments below the layout where it's called.
 *
 * Each layout in the App Router tree wraps its children with a
 * LayoutSegmentProvider whose value is a map of parallel route key to
 * segment arrays. The "children" key is the default parallel route.
 *
 * @param parallelRoutesKey - Which parallel route to read (default: "children")
 */
declare function useSelectedLayoutSegments(parallelRoutesKey?: string): string[];
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
declare function useServerInsertedHTML(callback: () => unknown): void;
/**
 * Flush all collected useServerInsertedHTML callbacks.
 * Returns an array of results (React elements or strings).
 * Clears the callback list so the next render starts fresh.
 *
 * Called by the SSR entry after renderToReadableStream completes.
 */
declare function flushServerInsertedHTML(): unknown[];
/**
 * Render collected useServerInsertedHTML callbacks without unregistering them.
 *
 * Streaming SSR needs to invoke the same style-registry callbacks after each
 * Fizz flush. Libraries such as styled-components and Emotion clear their own
 * per-flush buffers inside the callback; the registration itself must survive
 * until the request stream is closed.
 */
declare function renderServerInsertedHTML(): unknown[];
/**
 * Clear all collected useServerInsertedHTML callbacks without flushing.
 * Used for cleanup between requests.
 */
declare function clearServerInsertedHTML(): void;
/**
 * HTTP Access Fallback error code — shared prefix for notFound/forbidden/unauthorized.
 * Matches Next.js 16's unified error handling approach.
 */
declare const HTTP_ERROR_FALLBACK_ERROR_CODE = "NEXT_HTTP_ERROR_FALLBACK";
/**
 * Check if an error is an HTTP Access Fallback error (notFound, forbidden, unauthorized).
 */
declare function isHTTPAccessFallbackError(error: unknown): boolean;
/**
 * Extract the HTTP status code from an HTTP Access Fallback error.
 * Returns 404 for legacy NEXT_NOT_FOUND errors.
 */
declare function getAccessFallbackHTTPStatus(error: unknown): number;
/**
 * Enum matching Next.js RedirectType for type-safe redirect calls.
 */
declare enum RedirectType {
  push = "push",
  replace = "replace"
}
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
declare function redirect(url: string, type?: "replace" | "push" | RedirectType): never;
/**
 * Trigger a permanent redirect (308).
 *
 * Accepts an optional `type` parameter matching Next.js's signature.
 * Defaults to "replace" (not context-dependent like `redirect()`).
 *
 * @see https://github.com/vercel/next.js/blob/canary/packages/next/src/client/components/redirect.ts
 */
declare function permanentRedirect(url: string, type?: "replace" | "push" | RedirectType): never;
/**
 * Trigger a not-found response (404). Caught by the framework.
 */
declare function notFound(): never;
/**
 * Trigger a forbidden response (403). Caught by the framework.
 * In Next.js, this is gated behind experimental.authInterrupts — we
 * support it unconditionally for maximum compatibility.
 */
declare function forbidden(): never;
/**
 * Trigger an unauthorized response (401). Caught by the framework.
 * In Next.js, this is gated behind experimental.authInterrupts — we
 * support it unconditionally for maximum compatibility.
 */
declare function unauthorized(): never;
//#endregion
export { CachedRscResponse, ClientNavigationRenderSnapshot, GLOBAL_ACCESSORS_KEY, HTTP_ERROR_FALLBACK_ERROR_CODE, MAX_PREFETCH_CACHE_SIZE, NavigationContext, PREFETCH_CACHE_TTL, PrefetchCacheEntry, ReadonlyURLSearchParams, RedirectType, SegmentMap, ServerInsertedHTMLContext, __basePath, _registerStateAccessors, activateNavigationSnapshot, appRouterInstance, clearPendingPathname, clearServerInsertedHTML, commitClientNavigationState, consumePrefetchResponse, createClientNavigationRenderSnapshot, flushServerInsertedHTML, forbidden, getAccessFallbackHTTPStatus, getClientNavigationRenderContext, getClientNavigationState, getClientParams, getCurrentInterceptionContext, getCurrentNextUrl, getLayoutSegmentContext, getMountedSlotsHeader, getNavigationContext, getPrefetchCache, getPrefetchedUrls, isHTTPAccessFallbackError, navigateClientSide, notFound, permanentRedirect, prefetchRscResponse, pushHistoryStateWithoutNotify, redirect, renderServerInsertedHTML, replaceClientParamsWithoutNotify, replaceHistoryStateWithoutNotify, restoreRscResponse, setClientParams, setMountedSlotsHeader, setNavigationContext, setPendingPathname, snapshotRscResponse, storePrefetchResponse, unauthorized, useParams, usePathname, useRouter, useSearchParams, useSelectedLayoutSegment, useSelectedLayoutSegments, useServerInsertedHTML };
//# sourceMappingURL=navigation.d.ts.map