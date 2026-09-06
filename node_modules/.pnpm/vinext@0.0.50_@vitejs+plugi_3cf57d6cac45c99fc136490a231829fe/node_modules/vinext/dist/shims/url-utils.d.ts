//#region src/shims/url-utils.d.ts
/**
 * If `url` is an absolute same-origin URL, return the local path
 * (pathname + search + hash). Returns null for truly external URLs
 * or on the server (where origin is unknown).
 */
declare function toSameOriginPath(url: string): string | null;
/**
 * If `url` is an absolute same-origin URL, return the app-relative path
 * (basePath stripped from the pathname, if configured). Returns null for
 * truly external URLs or on the server.
 */
declare function toSameOriginAppPath(url: string, basePath: string): string | null;
/**
 * Prepend basePath to a local path for browser URLs / fetches.
 */
declare function withBasePath(path: string, basePath: string): string;
/**
 * Resolve a potentially relative href against the current URL.
 * Handles: "#hash", "?query", "?query#hash", and relative paths.
 */
declare function resolveRelativeHref(href: string, currentUrl?: string, basePath?: string): string;
/**
 * Convert a local navigation target into the browser URL that should be used
 * for history entries, fetches, and onNavigate callbacks.
 */
declare function toBrowserNavigationHref(href: string, currentUrl?: string, basePath?: string): string;
declare function isHashOnlyBrowserUrlChange(href: string, currentHref: string, basePath?: string): boolean;
//#endregion
export { isHashOnlyBrowserUrlChange, resolveRelativeHref, toBrowserNavigationHref, toSameOriginAppPath, toSameOriginPath, withBasePath };
//# sourceMappingURL=url-utils.d.ts.map