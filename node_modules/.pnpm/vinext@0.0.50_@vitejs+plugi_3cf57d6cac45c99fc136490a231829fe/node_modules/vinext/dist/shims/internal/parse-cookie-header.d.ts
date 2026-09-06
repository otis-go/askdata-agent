//#region src/shims/internal/parse-cookie-header.d.ts
/**
 * Port of the current Next.js/@edge-runtime request cookie parser semantics.
 *
 * Important details:
 * - split on a semicolon-plus-optional-spaces pattern
 * - preserve whitespace around names/values otherwise
 * - bare tokens become "true"
 * - malformed percent-encoded values are skipped
 * - duplicate names collapse to the last value via Map.set()
 */
declare function parseCookieHeader(cookieHeader: string): Map<string, string>;
//#endregion
export { parseCookieHeader };
//# sourceMappingURL=parse-cookie-header.d.ts.map