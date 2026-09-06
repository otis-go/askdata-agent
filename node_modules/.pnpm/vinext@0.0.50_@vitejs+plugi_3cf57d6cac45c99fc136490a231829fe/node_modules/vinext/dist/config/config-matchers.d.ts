import { HasCondition, NextHeader, NextRedirect, NextRewrite } from "./next-config.js";

//#region src/config/config-matchers.d.ts
/**
 * Detect regex patterns vulnerable to catastrophic backtracking (ReDoS).
 *
 * Uses a lightweight heuristic: scans the pattern string for nested quantifiers
 * (a quantifier applied to a group that itself contains a quantifier). This
 * catches the most common pathological patterns like `(a+)+`, `(.*)*`,
 * `([^/]+)+`, `(a|a+)+` without needing a full regex parser.
 *
 * Returns true if the pattern appears safe, false if it's potentially dangerous.
 */
declare function isSafeRegex(pattern: string): boolean;
/**
 * Compile a regex pattern safely. Returns the compiled RegExp or null if the
 * pattern is invalid or vulnerable to ReDoS.
 *
 * Logs a warning when a pattern is rejected so developers can fix their config.
 */
declare function safeRegExp(pattern: string, flags?: string): RegExp | null;
/**
 * Convert a Next.js header/rewrite/redirect source pattern into a regex string.
 *
 * Regex groups in the source (e.g. `(\d+)`) are extracted first, the remaining
 * text is escaped/converted in a **single pass** (avoiding chained `.replace()`
 * which CodeQL flags as incomplete sanitization), then groups are restored.
 */
declare function escapeHeaderSource(source: string): string;
/**
 * Request context needed for evaluating has/missing conditions.
 * Callers extract the relevant parts from the incoming Request.
 */
type RequestContext = {
  headers: Headers;
  cookies: Record<string, string>;
  query: URLSearchParams;
  host: string;
};
/**
 * Parse a Cookie header string into a key-value record.
 */
declare function parseCookies(cookieHeader: string | null): Record<string, string>;
/**
 * Build a RequestContext from a Web Request object.
 */
declare function requestContextFromRequest(request: Request): RequestContext;
declare function normalizeHost(hostHeader: string | null, fallbackHostname: string): string;
/**
 * Unpack `x-middleware-request-*` headers from the collected middleware
 * response headers into the actual request, and strip all `x-middleware-*`
 * internal signals so they never reach clients.
 *
 * `middlewareHeaders` is mutated in-place (matching keys are deleted).
 * Returns a (possibly cloned) `Request` with the unpacked headers applied,
 * and a fresh `RequestContext` built from it — ready for post-middleware
 * config rule matching (beforeFiles, afterFiles, fallback).
 *
 * Works for both Node.js requests (mutable headers) and Workers requests
 * (immutable — cloned only when there are headers to apply).
 *
 * `x-middleware-request-*` values are always plain strings (they carry
 * individual header values), so the wider `string | string[]` type of
 * `middlewareHeaders` is safe to cast here.
 */
declare function applyMiddlewareRequestHeaders(middlewareHeaders: Record<string, string | string[]>, request: Request, options?: {
  preserveCredentialHeaders?: boolean;
}): {
  request: Request;
  postMwReqCtx: RequestContext;
};
declare function checkHasConditions(has: HasCondition[] | undefined, missing: HasCondition[] | undefined, ctx: RequestContext): boolean;
/**
 * Match a Next.js config pattern (from redirects/rewrites sources) against a pathname.
 * Returns matched params or null.
 *
 * Supports:
 *   :param     - matches a single path segment
 *   :param*    - matches zero or more segments (catch-all)
 *   :param+    - matches one or more segments
 *   (regex)    - inline regex patterns in the source
 *   :param(constraint) - named param with inline regex constraint
 */
declare function matchConfigPattern(pathname: string, pattern: string): Record<string, string> | null;
/**
 * Apply redirect rules from next.config.js.
 * Returns the redirect info if a redirect was matched, or null.
 *
 * `ctx` provides the request context (cookies, headers, query, host) used
 * to evaluate has/missing conditions. Next.js always has request context
 * when evaluating redirects, so this parameter is required.
 *
 * ## Performance
 *
 * Rules with a locale-capture-group prefix (the dominant pattern in large
 * Next.js apps — e.g. `/:locale(en|es|fr|...)?/some-path`) are handled via
 * a pre-built index. Instead of running exec() on each locale regex
 * individually, we:
 *
 *   1. Strip the optional locale prefix from the pathname with one cheap
 *      string-slice check (no regex exec on the hot path).
 *   2. Look up the stripped suffix in a Map<suffix, entry[]>.
 *   3. For each matching entry, validate the captured locale string against
 *      a small, anchored alternation regex.
 *
 * This reduces the per-request cost from O(n × regex) to O(1) map lookup +
 * O(matches × tiny-regex), eliminating the ~2992ms self-time reported in
 * profiles for apps with 63+ locale-prefixed rules.
 *
 * Rules that don't fit the locale-static pattern fall back to the original
 * linear matchConfigPattern scan.
 *
 * ## Ordering invariant
 *
 * First match wins, preserving the original redirect array order. When a
 * locale-static fast-path match is found at position N, all linear rules with
 * an original index < N are checked via matchConfigPattern first — they are
 * few in practice (typically zero) so this is not a hot-path concern.
 */
declare function matchRedirect(pathname: string, redirects: NextRedirect[], ctx: RequestContext): {
  destination: string;
  permanent: boolean;
} | null;
/**
 * Apply rewrite rules from next.config.js.
 * Returns the rewritten URL or null if no rewrite matched.
 *
 * `ctx` provides the request context (cookies, headers, query, host) used
 * to evaluate has/missing conditions. Next.js always has request context
 * when evaluating rewrites, so this parameter is required.
 */
declare function matchRewrite(pathname: string, rewrites: NextRewrite[], ctx: RequestContext): string | null;
/**
 * Sanitize a redirect/rewrite destination to collapse protocol-relative URLs.
 *
 * After parameter substitution, a destination like `/:path*` can become
 * `//evil.com` if the catch-all captured a decoded `%2F` (`/evil.com`).
 * Browsers interpret `//evil.com` as a protocol-relative URL, redirecting
 * users off-site.
 *
 * This function collapses any leading double (or more) slashes to a single
 * slash for non-external (relative) destinations.
 */
declare function sanitizeDestination(dest: string): string;
/**
 * Check if a URL is external (absolute URL or protocol-relative).
 * Detects any URL scheme (http:, https:, data:, javascript:, blob:, etc.)
 * per RFC 3986, plus protocol-relative URLs (//).
 */
declare function isExternalUrl(url: string): boolean;
/**
 * Proxy an incoming request to an external URL and return the upstream response.
 *
 * Used for external rewrites (e.g. `/ph/:path*` → `https://us.i.posthog.com/:path*`).
 * Next.js handles these as server-side reverse proxies, forwarding the request
 * method, headers, and body to the external destination.
 *
 * Works in all runtimes (Node.js, Cloudflare Workers) via the standard fetch() API.
 */
declare function proxyExternalRequest(request: Request, externalUrl: string): Promise<Response>;
/**
 * Apply custom header rules from next.config.js.
 * Returns an array of { key, value } pairs to set on the response.
 *
 * `ctx` provides the request context (cookies, headers, query, host) used
 * to evaluate has/missing conditions. Next.js always has request context
 * when evaluating headers, so this parameter is required.
 */
declare function matchHeaders(pathname: string, headers: NextHeader[], ctx: RequestContext): Array<{
  key: string;
  value: string;
}>;
//#endregion
export { RequestContext, applyMiddlewareRequestHeaders, checkHasConditions, escapeHeaderSource, isExternalUrl, isSafeRegex, matchConfigPattern, matchHeaders, matchRedirect, matchRewrite, normalizeHost, parseCookies, proxyExternalRequest, requestContextFromRequest, safeRegExp, sanitizeDestination };
//# sourceMappingURL=config-matchers.d.ts.map