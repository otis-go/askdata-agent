import { RoutePatternParams } from "../routing/route-pattern.js";

//#region src/server/app-rsc-route-matching.d.ts
type AppRscRouteParams = RoutePatternParams;
type AppRscInterceptForMatching = {
  targetPattern: string;
  interceptLayouts: readonly unknown[];
  page: unknown;
  params: readonly string[];
};
type AppRscSlotForMatching = {
  intercepts?: readonly AppRscInterceptForMatching[];
};
type AppRscRouteForMatching = {
  patternParts: string[];
  slots?: Record<string, AppRscSlotForMatching>;
};
type AppRscInterceptMatch = AppRscInterceptLookupEntry & {
  matchedParams: AppRscRouteParams;
};
type AppRscInterceptLookupEntry = {
  sourceRouteIndex: number;
  slotKey: string;
  targetPattern: string;
  targetPatternParts: string[];
  interceptLayouts: readonly unknown[];
  page: unknown;
  params: readonly string[];
};
declare function createAppRscRouteMatcher<Route extends AppRscRouteForMatching>(routes: Route[]): {
  matchRoute(url: string): {
    route: Route;
    params: AppRscRouteParams;
  } | null;
  findIntercept(pathname: string, sourcePathname?: string | null): AppRscInterceptMatch | null;
};
declare function matchAppRscRoutePattern(urlParts: string[], patternParts: string[]): AppRscRouteParams | null;
//#endregion
export { createAppRscRouteMatcher, matchAppRscRoutePattern };
//# sourceMappingURL=app-rsc-route-matching.d.ts.map