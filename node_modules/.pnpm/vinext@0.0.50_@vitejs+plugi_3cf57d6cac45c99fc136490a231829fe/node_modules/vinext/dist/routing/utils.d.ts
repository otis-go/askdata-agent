//#region src/routing/utils.d.ts
/**
 * Sort comparator for routes — lower precedence score sorts first (higher priority).
 * Lexicographic tiebreaker on pattern for determinism.
 *
 * Usage: routes.sort(compareRoutes)
 */
declare function compareRoutes<T extends {
  pattern: string;
}>(a: T, b: T): number;
/**
 * Decode a filesystem or URL path segment while preserving encoded path delimiters.
 * Mirrors Next.js segment-wise decoding so "%5F" becomes "_" but "%2F" stays "%2F".
 */
declare function decodeRouteSegment(segment: string): string;
/**
 * Normalize a pathname for route matching by decoding each segment independently.
 * This prevents encoded slashes from turning into real path separators.
 */
declare function normalizePathnameForRouteMatch(pathname: string): string;
/**
 * Strict pathname normalization for live request handling.
 * Throws on malformed percent-encoding so callers can return 400.
 */
declare function normalizePathnameForRouteMatchStrict(pathname: string): string;
/**
 * Decode captured route params with `decodeURIComponent`, mirroring Next.js
 * route-matcher.ts:25-27. Mutates the params object in place. Catch-all
 * arrays are decoded element-wise. Malformed escapes are preserved (the
 * strict normalization layer rejects them at the request boundary).
 */
declare function decodeMatchedParams(params: Record<string, string | string[]>): void;
//#endregion
export { compareRoutes, decodeMatchedParams, decodeRouteSegment, normalizePathnameForRouteMatch, normalizePathnameForRouteMatchStrict };
//# sourceMappingURL=utils.d.ts.map