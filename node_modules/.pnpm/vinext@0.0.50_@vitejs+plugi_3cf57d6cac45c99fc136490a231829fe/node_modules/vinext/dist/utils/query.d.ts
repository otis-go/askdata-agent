//#region src/utils/query.d.ts
/**
 * Add a query parameter value to an object, promoting to array for duplicate keys.
 * Matches Next.js behavior: ?a=1&a=2 → { a: ['1', '2'] }
 */
type UrlQueryValue = string | number | boolean | null | undefined;
type UrlQuery = Record<string, UrlQueryValue | readonly UrlQueryValue[]>;
declare function addQueryParam(obj: Record<string, string | string[]>, key: string, value: string): void;
/**
 * Merge pathname-derived dynamic route params into a query object.
 *
 * Route params must win over same-name URL search params so `/posts/123?id=456`
 * still exposes `id: "123"` to Pages Router APIs.
 */
declare function mergeRouteParamsIntoQuery(query: Record<string, string | string[]>, params: Record<string, string | string[]>): Record<string, string | string[]>;
/**
 * Parse a URL's query string into a Record, with multi-value keys promoted to arrays.
 */
declare function parseQueryString(url: string): Record<string, string | string[]>;
declare function urlQueryToSearchParams(query: UrlQuery): URLSearchParams;
/**
 * Append query parameters to a URL while preserving any existing query string
 * and fragment identifier.
 */
declare function appendSearchParamsToUrl(url: string, params: Iterable<[string, string]>): string;
//#endregion
export { UrlQuery, addQueryParam, appendSearchParamsToUrl, mergeRouteParamsIntoQuery, parseQueryString, urlQueryToSearchParams };
//# sourceMappingURL=query.d.ts.map