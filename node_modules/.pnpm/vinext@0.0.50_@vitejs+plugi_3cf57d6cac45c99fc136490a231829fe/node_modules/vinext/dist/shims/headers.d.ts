//#region src/shims/headers.d.ts
/**
 * next/headers shim
 *
 * Provides cookies() and headers() functions for App Router Server Components.
 * These read from a request context set by the RSC handler before rendering.
 *
 * In Next.js 15+, cookies() and headers() return Promises (async).
 * We support both the sync (legacy) and async patterns.
 */
type HeadersContext = {
  headers: Headers;
  cookies: Map<string, string>;
  accessError?: Error;
  forceStatic?: boolean;
  mutableCookies?: RequestCookies;
  readonlyCookies?: RequestCookies;
  readonlyHeaders?: Headers;
};
type HeadersAccessPhase = "render" | "action" | "route-handler";
type VinextHeadersShimState = {
  headersContext: HeadersContext | null;
  dynamicUsageDetected: boolean; /** Error recorded by throwIfInsideCacheScope for dev diagnostics, persists even if caught by user code. */
  invalidDynamicUsageError: unknown;
  pendingSetCookies: string[];
  draftModeCookieHeader: string | null;
  phase: HeadersAccessPhase;
};
/**
 * Dynamic usage flag — set when a component calls connection(), cookies(),
 * headers(), or noStore() during rendering. When true, ISR caching is
 * bypassed and the response gets Cache-Control: no-store.
 */
/**
 * Mark the current render as requiring dynamic (uncached) rendering.
 * Called by connection(), cookies(), headers(), and noStore().
 */
declare function markDynamicUsage(): void;
/**
 * Throw if the current execution is inside a "use cache" or unstable_cache()
 * scope. Called by dynamic request APIs (headers, cookies, connection) to
 * prevent request-specific data from being frozen into cached results.
 *
 * @param apiName - The name of the API being called (e.g. "connection()")
 */
declare function throwIfInsideCacheScope(apiName: string): void;
/**
 * Check, consume, and return any invalid dynamic usage error recorded during
 * the render (e.g. cookies() called inside "use cache"). This error persists
 * even if the throw was caught by user-code try/catch, so it can surface on
 * client-side navigations where the static shell validation is skipped.
 * Ported from Next.js: workStore.invalidDynamicUsageError in
 * packages/next/src/server/app-render/app-render.tsx
 * https://github.com/vercel/next.js/commit/f5e54c06726b571a042fce67417e40a29f6b8689
 */
declare function consumeInvalidDynamicUsageError(): unknown;
/**
 * Check and reset the dynamic usage flag.
 * Called by the server after rendering to decide on caching.
 */
declare function consumeDynamicUsage(): boolean;
declare function setHeadersAccessPhase(phase: HeadersAccessPhase): HeadersAccessPhase;
declare function getHeadersAccessPhase(): HeadersAccessPhase;
/**
 * Set the headers/cookies context for the current RSC render.
 * Called by the framework's RSC entry before rendering each request.
 *
 * @deprecated Prefer runWithHeadersContext() which uses als.run() for
 * proper per-request isolation. This function mutates the ALS store
 * in-place and is only safe for cleanup (ctx=null) within an existing
 * als.run() scope.
 */
/**
 * Returns the current live HeadersContext from ALS (or the fallback).
 * Used after applyMiddlewareRequestHeaders() to build a post-middleware
 * request context for afterFiles/fallback rewrite has/missing evaluation.
 */
declare function getHeadersContext(): HeadersContext | null;
declare function setHeadersContext(ctx: HeadersContext | null): void;
/**
 * Run a function with headers context, ensuring the context propagates
 * through all async operations (including RSC streaming).
 *
 * Uses AsyncLocalStorage.run() to guarantee per-request isolation.
 * The ALS store propagates through all async continuations including
 * ReadableStream consumption, setTimeout callbacks, and Promise chains,
 * so RSC streaming works correctly — components that render when the
 * stream is consumed still see the correct request's context.
 */
declare function runWithHeadersContext<T>(ctx: HeadersContext, fn: () => Promise<T>): Promise<T>;
declare function runWithHeadersContext<T>(ctx: HeadersContext, fn: () => T | Promise<T>): T | Promise<T>;
/**
 * Apply middleware-forwarded request headers to the current headers context.
 *
 * When Next.js middleware calls `NextResponse.next()` or `NextResponse.rewrite()`
 * with `{ request: { headers } }`, the modified headers are encoded on the
 * middleware response. This function decodes that protocol and applies the
 * resulting request header set to the live `HeadersContext`. When an override
 * list is present, omitted headers are deleted as part of the rebuild.
 *
 * Cached `readonlyHeaders` and `readonlyCookies` snapshots on the
 * HeadersContext must be invalidated whenever this function rebuilds the
 * underlying `headers`/`cookies`. Otherwise a middleware that reads
 * `headers()` (or `cookies()`) before returning a request-header override —
 * for example `@clerk/nextjs`, whose `clerkClient()` reads `headers()` via
 * `buildRequestLike()` during middleware execution — primes a sealed snapshot
 * built from the *pre*-override request, and any subsequent `headers()` call
 * from a Server Component would return that stale snapshot instead of the
 * middleware-modified view.
 */
declare function applyMiddlewareRequestHeaders(middlewareResponseHeaders: Headers): void;
/**
 * Create a HeadersContext from a standard Request object.
 *
 * Performance note: In Workerd (Cloudflare Workers), `new Headers(request.headers)`
 * copies the entire header map across the V8/C++ boundary, which shows up as
 * ~815 ms self-time in production profiles when requests carry many headers.
 * We defer this copy with a lazy proxy:
 *
 * - Reads (`get`, `has`, `entries`, …) are forwarded directly to the original
 *   immutable `request.headers` — zero copy cost on the hot path.
 * - The first mutating call (`set`, `delete`, `append`) materialises
 *   `new Headers(request.headers)` once, then applies the mutation to the copy.
 *   All subsequent operations go to the copy.
 *
 * This means the ~815 ms copy only occurs when middleware actually rewrites
 * request headers via `NextResponse.next({ request: { headers } })`, which is
 * uncommon.  Pure read requests (the vast majority) pay zero copy cost.
 *
 * Cookie parsing is also deferred: the `cookie` header string is not split
 * until the first call to `cookies()` or `draftMode()`.
 */
declare function headersContextFromRequest(request: Request): HeadersContext;
/**
 * Read-only Headers instance from the incoming request.
 * Returns a Promise in Next.js 15+ style (but resolves synchronously since
 * the context is already available).
 */
declare function headers(): Promise<Headers> & Headers;
/**
 * Cookie jar from the incoming request.
 * Returns a ReadonlyRequestCookies-like object.
 */
declare function cookies(): Promise<RequestCookies> & RequestCookies;
/** Accumulated Set-Cookie headers from cookies().set() / .delete() calls */
/**
 * Get and clear all pending Set-Cookie headers generated by cookies().set()/delete().
 * Called by the framework after rendering to attach headers to the response.
 */
declare function getAndClearPendingCookies(): string[];
/**
 * Get any Set-Cookie header generated by draftMode().enable()/disable().
 * Called by the framework after rendering to attach the header to the response.
 */
declare function getDraftModeCookieHeader(): string | null;
declare function isDraftModeRequest(request: Request): boolean;
type DraftModeResult = {
  readonly isEnabled: boolean;
  enable(): void;
  disable(): void;
};
/**
 * Draft mode — check/toggle via a `__prerender_bypass` cookie.
 *
 * - `isEnabled`: true if the bypass cookie is present in the request
 * - `enable()`: sets the bypass cookie (for Route Handlers)
 * - `disable()`: clears the bypass cookie
 */
declare function draftMode(): Promise<DraftModeResult>;
declare class RequestCookies {
  private _cookies;
  constructor(cookies: Map<string, string>);
  get(name: string): {
    name: string;
    value: string;
  } | undefined;
  getAll(nameOrOptions?: string | {
    name: string;
  }): Array<{
    name: string;
    value: string;
  }>;
  has(name: string): boolean;
  /**
   * Set a cookie. In Route Handlers and Server Actions, this produces
   * a Set-Cookie header on the response.
   */
  set(nameOrOptions: string | {
    name: string;
    value: string;
    path?: string;
    domain?: string;
    maxAge?: number;
    expires?: Date;
    httpOnly?: boolean;
    secure?: boolean;
    sameSite?: "Strict" | "Lax" | "None";
  }, value?: string, options?: {
    path?: string;
    domain?: string;
    maxAge?: number;
    expires?: Date;
    httpOnly?: boolean;
    secure?: boolean;
    sameSite?: "Strict" | "Lax" | "None";
  }): this;
  /**
   * Delete a cookie by emitting an expired Set-Cookie header.
   */
  delete(nameOrOptions: string | {
    name: string;
    path?: string;
    domain?: string;
  }): this;
  get size(): number;
  [Symbol.iterator](): IterableIterator<[string, {
    name: string;
    value: string;
  }]>;
  toString(): string;
}
//#endregion
export { HeadersAccessPhase, HeadersContext, type RequestCookies, VinextHeadersShimState, applyMiddlewareRequestHeaders, consumeDynamicUsage, consumeInvalidDynamicUsageError, cookies, draftMode, getAndClearPendingCookies, getDraftModeCookieHeader, getHeadersAccessPhase, getHeadersContext, headers, headersContextFromRequest, isDraftModeRequest, markDynamicUsage, runWithHeadersContext, setHeadersAccessPhase, setHeadersContext, throwIfInsideCacheScope };
//# sourceMappingURL=headers.d.ts.map