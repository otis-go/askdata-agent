import { VINEXT_RSC_RENDER_MODE_HEADER } from "./headers.js";
import { AppRscRenderMode } from "./app-rsc-render-mode.js";

//#region src/server/app-rsc-cache-busting.d.ts
/**
 * RSC cache-busting hashes cover the headers that make a `.rsc` payload vary.
 * Client-side variant headers must survive transit through CDNs and reverse
 * proxies; stripping them changes the server hash and turns stale URLs into
 * repeated canonicalization redirects.
 */
declare const VINEXT_RSC_CACHE_BUSTING_SEARCH_PARAM = "_rsc";
declare const VINEXT_RSC_CONTENT_TYPE = "text/x-component";
declare const VINEXT_RSC_VARY_HEADER: string;
type CreateRscRequestHeadersOptions = {
  interceptionContext?: string | null;
  mountedSlotsHeader?: string | null;
  renderMode?: AppRscRenderMode;
};
type ResolveInvalidRscCacheBustingRequestOptions = {
  isRscRequest: boolean;
  request: Request;
};
declare function computeRscCacheBustingSearchParam(headers: Headers): Promise<string>;
declare function setRscCacheBustingSearchParam(url: URL, hash: string): void;
declare function stripRscCacheBustingSearchParam(url: URL): void;
/**
 * Remove a trailing `.rsc` suffix from a pathname. Returns the pathname
 * unchanged when the suffix is absent.
 */
declare function stripRscSuffix(pathname: string): string;
declare function createRscRequestHeaders(options?: CreateRscRequestHeadersOptions): Headers;
declare function createRscRequestUrl(href: string, headers: Headers): Promise<string>;
declare function createRscRedirectLocation(location: string, request: Request): Promise<string>;
declare function resolveInvalidRscCacheBustingRequest(options: ResolveInvalidRscCacheBustingRequestOptions): Promise<Response | null>;
//#endregion
export { VINEXT_RSC_CACHE_BUSTING_SEARCH_PARAM, VINEXT_RSC_CONTENT_TYPE, VINEXT_RSC_RENDER_MODE_HEADER, VINEXT_RSC_VARY_HEADER, computeRscCacheBustingSearchParam, createRscRedirectLocation, createRscRequestHeaders, createRscRequestUrl, resolveInvalidRscCacheBustingRequest, setRscCacheBustingSearchParam, stripRscCacheBustingSearchParam, stripRscSuffix };
//# sourceMappingURL=app-rsc-cache-busting.d.ts.map