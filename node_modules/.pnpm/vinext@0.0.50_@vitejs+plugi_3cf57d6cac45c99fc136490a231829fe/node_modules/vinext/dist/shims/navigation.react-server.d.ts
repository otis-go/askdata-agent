import { ReadonlyURLSearchParams } from "./readonly-url-search-params.js";
import { GLOBAL_ACCESSORS_KEY, HTTP_ERROR_FALLBACK_ERROR_CODE, NavigationContext, RedirectType, SegmentMap, ServerInsertedHTMLContext, _registerStateAccessors, clearServerInsertedHTML, flushServerInsertedHTML, forbidden, getAccessFallbackHTTPStatus, getLayoutSegmentContext, getNavigationContext, isHTTPAccessFallbackError, notFound, permanentRedirect, redirect, renderServerInsertedHTML, setNavigationContext, unauthorized } from "./navigation.js";

//#region src/shims/navigation.react-server.d.ts
declare function usePathname(): never;
declare function useSearchParams(): never;
declare function useParams(): never;
declare function useRouter(): never;
declare function useSelectedLayoutSegment(): never;
declare function useSelectedLayoutSegments(): never;
declare function useServerInsertedHTML(): never;
//#endregion
export { GLOBAL_ACCESSORS_KEY, HTTP_ERROR_FALLBACK_ERROR_CODE, type NavigationContext, ReadonlyURLSearchParams, RedirectType, type SegmentMap, ServerInsertedHTMLContext, _registerStateAccessors, clearServerInsertedHTML, flushServerInsertedHTML, forbidden, getAccessFallbackHTTPStatus, getLayoutSegmentContext, getNavigationContext, isHTTPAccessFallbackError, notFound, permanentRedirect, redirect, renderServerInsertedHTML, setNavigationContext, unauthorized, useParams, usePathname, useRouter, useSearchParams, useSelectedLayoutSegment, useSelectedLayoutSegments, useServerInsertedHTML };
//# sourceMappingURL=navigation.react-server.d.ts.map