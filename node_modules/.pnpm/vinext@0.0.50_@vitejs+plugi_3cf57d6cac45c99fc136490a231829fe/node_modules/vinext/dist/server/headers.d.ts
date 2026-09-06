//#region src/server/headers.d.ts
/**
 * Internal HTTP header name constants used throughout vinext.
 *
 * Centralizes all custom header names so they are defined once and referenced
 * everywhere via imports. Keeping them in one module prevents typos, makes
 * rename-refactors trivial, and lets grep find every consumer instantly.
 *
 * Standard HTTP headers (Content-Type, Cache-Control, etc.) are intentionally
 * omitted — only vinext-internal and Next.js-protocol headers belong here.
 */
/** ISR / page cache state indicator: "HIT" | "MISS" | "STALE" | "STATIC". */
declare const VINEXT_CACHE_HEADER = "X-Vinext-Cache";
/** Static file signal — value is URL-encoded pathname. */
declare const VINEXT_STATIC_FILE_HEADER = "x-vinext-static-file";
/** Serialized middleware context (JSON) forwarded from dev server to RSC entry. */
declare const VINEXT_MW_CTX_HEADER = "x-vinext-mw-ctx";
/** Timing metrics: `handlerStart,compileMs,renderMs`. */
declare const VINEXT_TIMING_HEADER = "x-vinext-timing";
/** Build-time prerender authentication secret. */
declare const VINEXT_PRERENDER_SECRET_HEADER = "x-vinext-prerender-secret";
/** TPR (Tailored Per-Request) revalidation interval in seconds. */
declare const VINEXT_REVALIDATE_HEADER = "x-vinext-revalidate";
/** Marker on cached ISR entries indicating RSC payload (value "1"). */
declare const VINEXT_RSC_MARKER_HEADER = "x-vinext-rsc";
/** URL-encoded JSON route params carried on RSC responses. */
declare const VINEXT_PARAMS_HEADER = "X-Vinext-Params";
/** Deduplicated, sorted list of mounted layout slots for cache keying. */
declare const VINEXT_MOUNTED_SLOTS_HEADER = "X-Vinext-Mounted-Slots";
/** Route interception context for parallel/intercepting routes. */
declare const VINEXT_INTERCEPTION_CONTEXT_HEADER = "X-Vinext-Interception-Context";
/** RSC render mode (e.g. "navigation", "prefetch"). */
declare const VINEXT_RSC_RENDER_MODE_HEADER = "X-Vinext-Rsc-Render-Mode";
/** Standard RSC header — value "1" indicates an RSC payload request. */
declare const RSC_HEADER = "RSC";
/** Server Action invocation header (vinext/vite-rsc protocol). */
declare const RSC_ACTION_HEADER = "x-rsc-action";
/** Next.js Server Action invocation header (fallback for x-rsc-action). */
declare const NEXT_ACTION_HEADER = "next-action";
/** Next.js action-not-found indicator (value "1"). */
declare const NEXTJS_ACTION_NOT_FOUND_HEADER = "x-nextjs-action-not-found";
/** Indicates revalidation occurred — value is JSON kind (1 = path/tag, 2 = dynamic-only). */
declare const ACTION_REVALIDATED_HEADER = "x-action-revalidated";
/** Redirect URL from a Server Action. */
declare const ACTION_REDIRECT_HEADER = "x-action-redirect";
/** Redirect type from a Server Action ("push" | "replace"). */
declare const ACTION_REDIRECT_TYPE_HEADER = "x-action-redirect-type";
/** HTTP status for a Server Action redirect (e.g. "308"). */
declare const ACTION_REDIRECT_STATUS_HEADER = "x-action-redirect-status";
/** Prefix for forwarded request headers (e.g. `x-middleware-request-cookie`). */
declare const MIDDLEWARE_REQUEST_HEADER_PREFIX = "x-middleware-request-";
/** Comma-separated list of header names that middleware wants to override. */
declare const MIDDLEWARE_OVERRIDE_HEADERS = "x-middleware-override-headers";
/** Carries cookies set by middleware for same-render reads. */
declare const MIDDLEWARE_SET_COOKIE_HEADER = "x-middleware-set-cookie";
/** Signal from `NextResponse.next()` — value "1" means "continue to next handler". */
declare const MIDDLEWARE_NEXT_HEADER = "x-middleware-next";
/** Rewrite destination URL set by `NextResponse.rewrite()`. */
declare const MIDDLEWARE_REWRITE_HEADER = "x-middleware-rewrite";
/** Generic prefix for all middleware internal headers. */
declare const MIDDLEWARE_HEADER_PREFIX = "x-middleware-";
declare const NEXT_ROUTER_STATE_TREE_HEADER = "Next-Router-State-Tree";
declare const NEXT_ROUTER_PREFETCH_HEADER = "Next-Router-Prefetch";
declare const NEXT_ROUTER_SEGMENT_PREFETCH_HEADER = "Next-Router-Segment-Prefetch";
declare const NEXT_URL_HEADER = "Next-Url";
/** Lowercase flight header variants used in middleware forwarding. */
declare const FLIGHT_HEADERS: readonly string[];
/**
 * Headers that must be stripped from external requests before any handler
 * processes them. An attacker could forge these to influence routing or
 * impersonate internal data fetches.
 *
 * Ported from Next.js `INTERNAL_HEADERS`:
 * https://github.com/vercel/next.js/blob/canary/packages/next/src/server/lib/server-ipc/utils.ts
 */
declare const INTERNAL_HEADERS: string[];
//#endregion
export { ACTION_REDIRECT_HEADER, ACTION_REDIRECT_STATUS_HEADER, ACTION_REDIRECT_TYPE_HEADER, ACTION_REVALIDATED_HEADER, FLIGHT_HEADERS, INTERNAL_HEADERS, MIDDLEWARE_HEADER_PREFIX, MIDDLEWARE_NEXT_HEADER, MIDDLEWARE_OVERRIDE_HEADERS, MIDDLEWARE_REQUEST_HEADER_PREFIX, MIDDLEWARE_REWRITE_HEADER, MIDDLEWARE_SET_COOKIE_HEADER, NEXTJS_ACTION_NOT_FOUND_HEADER, NEXT_ACTION_HEADER, NEXT_ROUTER_PREFETCH_HEADER, NEXT_ROUTER_SEGMENT_PREFETCH_HEADER, NEXT_ROUTER_STATE_TREE_HEADER, NEXT_URL_HEADER, RSC_ACTION_HEADER, RSC_HEADER, VINEXT_CACHE_HEADER, VINEXT_INTERCEPTION_CONTEXT_HEADER, VINEXT_MOUNTED_SLOTS_HEADER, VINEXT_MW_CTX_HEADER, VINEXT_PARAMS_HEADER, VINEXT_PRERENDER_SECRET_HEADER, VINEXT_REVALIDATE_HEADER, VINEXT_RSC_MARKER_HEADER, VINEXT_RSC_RENDER_MODE_HEADER, VINEXT_STATIC_FILE_HEADER, VINEXT_TIMING_HEADER };
//# sourceMappingURL=headers.d.ts.map