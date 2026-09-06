import { normalizeMountedSlotsHeader } from "./app-mounted-slots-header.js";
import { AppRscRenderMode } from "./app-rsc-render-mode.js";

//#region src/server/app-rsc-request-normalization.d.ts
type NormalizedRscRequest = {
  /** Parsed URL. Callers may mutate `url.search` after middleware runs. */url: URL; /** Normalized pathname with basePath stripped. Used for all internal routing. */
  pathname: string; /** Pathname with `.rsc` suffix removed. Used for route matching and navigation context. */
  cleanPathname: string; /** True when the request targets a canonical `.rsc` payload URL. */
  isRscRequest: boolean; /** Sanitized X-Vinext-Interception-Context header (null bytes stripped). null when absent. */
  interceptionContextHeader: string | null; /** Normalized x-vinext-mounted-slots header (deduplicated, sorted). null when absent or blank. */
  mountedSlotsHeader: string | null; /** Semantic RSC payload mode. HTML requests always normalize to "navigation". */
  renderMode: AppRscRenderMode;
};
/**
 * Normalize an App Router RSC request.
 *
 * Performs all security-sensitive and compatibility-sensitive preprocessing before
 * route matching. The ordering of steps is security-critical — changing it introduces
 * vulnerabilities:
 *
 *   1. Parse URL
 *   2. Protocol-relative URL guard — on the raw pathname, BEFORE normalizePath collapses
 *      `//` to `/`. If the guard ran after normalization, `//evil.com` → `/evil.com`
 *      would bypass the check and reach the trailing-slash redirector, which echoes the
 *      path into a `Location` header that browsers interpret as protocol-relative.
 *   3. Strict percent-decode each segment — throws on malformed sequences (→ 400). Must
 *      run before basePath check so %2F-encoded slashes cannot create fake basePath prefixes.
 *   4. Collapse double-slashes, resolve `.` and `..` segments (normalizePath)
 *   5. basePath check + strip — 404 when pathname lacks the basePath prefix.
 *      `/__vinext/` bypasses this for internal prerender endpoints.
 *   6. RSC detection: `.rsc` suffix only. RSC headers do not select payload
 *      rendering at the canonical HTML URL, so caches that ignore Vary cannot
 *      store Flight responses under HTML URLs.
 *   7. cleanPathname — pathname with `.rsc` suffix stripped
 *   8. Sanitize X-Vinext-Interception-Context — strip null bytes (header injection)
 *   9. Normalize x-vinext-mounted-slots — dedup and sort for canonical cache keys
 *   10. Read semantic render mode for refresh/action payload rendering
 *
 * @returns A 400 or 404 Response for invalid or out-of-scope inputs,
 *          or a NormalizedRscRequest for valid requests.
 */
declare function normalizeRscRequest(request: Request, basePath: string): Response | NormalizedRscRequest;
//#endregion
export { NormalizedRscRequest, normalizeMountedSlotsHeader, normalizeRscRequest };
//# sourceMappingURL=app-rsc-request-normalization.d.ts.map