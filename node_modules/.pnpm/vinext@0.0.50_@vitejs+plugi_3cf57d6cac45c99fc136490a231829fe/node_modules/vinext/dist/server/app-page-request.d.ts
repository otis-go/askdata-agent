import { AppPageSpecialError } from "./app-page-execution.js";

//#region src/server/app-page-request.d.ts
type AppPageParams = Record<string, string | string[]>;
type GenerateStaticParams = (args: {
  params: AppPageParams;
}) => unknown;
type GenerateStaticParamsModule = {
  generateStaticParams?: GenerateStaticParams | null;
};
type GenerateStaticParamsSource = {
  generateStaticParams: GenerateStaticParams;
  parentParamNames: readonly string[];
};
type ValidateAppPageDynamicParamsOptions = {
  clearRequestContext: () => void;
  enforceStaticParamsOnly: boolean;
  generateStaticParams?: GenerateStaticParams | GenerateStaticParamsSource | readonly (GenerateStaticParams | GenerateStaticParamsSource | null | undefined)[] | null;
  isDynamicRoute: boolean;
  params: AppPageParams;
};
type ResolveAppPageGenerateStaticParamsSourcesOptions = {
  layouts?: readonly (GenerateStaticParamsModule | null | undefined)[];
  layoutTreePositions?: readonly number[];
  page?: GenerateStaticParamsModule | null;
  routeSegments: readonly string[];
};
type BuildAppPageElementOptions<TElement> = {
  buildPageElement: () => Promise<TElement>;
  renderErrorBoundaryPage: (error: unknown) => Promise<Response | null>;
  renderSpecialError: (specialError: AppPageSpecialError) => Promise<Response>;
  resolveSpecialError: (error: unknown) => AppPageSpecialError | null;
};
type BuildAppPageElementResult<TElement> = {
  element: TElement | null;
  response: Response | null;
};
type AppPageInterceptMatch<TPage = unknown> = {
  matchedParams: AppPageParams;
  page: TPage;
  slotKey: string;
  sourceRouteIndex: number;
};
type ResolveAppPageInterceptMatchOptions<TRoute, TPage, TInterceptOpts> = {
  cleanPathname: string;
  currentRoute: TRoute;
  findIntercept: (pathname: string) => AppPageInterceptMatch<TPage> | null;
  getRouteParamNames: (route: TRoute) => readonly string[];
  getSourceRoute: (sourceRouteIndex: number) => TRoute | undefined;
  isRscRequest: boolean;
  toInterceptOpts: (intercept: AppPageInterceptMatch<TPage>) => TInterceptOpts;
};
type ResolveAppPageInterceptMatchResult<TRoute, TInterceptOpts> = {
  interceptOpts: TInterceptOpts;
  matchedParams: AppPageParams;
  sourceParams: AppPageParams;
  sourceRoute: TRoute;
};
type ResolveAppPageActionRerenderTargetOptions<TRoute, TPage, TInterceptOpts> = {
  cleanPathname: string;
  currentParams: AppPageParams;
  currentRoute: TRoute;
  findIntercept: (pathname: string) => AppPageInterceptMatch<TPage> | null;
  getRouteParamNames: (route: TRoute) => readonly string[];
  getSourceRoute: (sourceRouteIndex: number) => TRoute | undefined;
  isRscRequest: boolean;
  toInterceptOpts: (intercept: AppPageInterceptMatch<TPage>) => TInterceptOpts;
};
type ResolveAppPageActionRerenderTargetResult<TRoute, TInterceptOpts> = {
  interceptOpts: TInterceptOpts | undefined;
  navigationParams: AppPageParams;
  params: AppPageParams;
  route: TRoute;
};
type ResolveAppPageInterceptOptions<TRoute, TPage, TInterceptOpts, TElement> = {
  buildPageElement: (route: TRoute, params: AppPageParams, interceptOpts: TInterceptOpts | undefined, searchParams: URLSearchParams) => Promise<TElement>;
  cleanPathname: string;
  currentRoute: TRoute;
  findIntercept: (pathname: string) => AppPageInterceptMatch<TPage> | null;
  getRouteParamNames: (route: TRoute) => readonly string[];
  getSourceRoute: (sourceRouteIndex: number) => TRoute | undefined;
  isRscRequest: boolean;
  renderInterceptResponse: (route: TRoute, element: TElement) => Promise<Response> | Response;
  searchParams: URLSearchParams;
  setNavigationContext: (context: {
    params: AppPageParams;
    pathname: string;
    searchParams: URLSearchParams;
  }) => void;
  toInterceptOpts: (intercept: AppPageInterceptMatch<TPage>) => TInterceptOpts;
};
type ResolveAppPageInterceptResult<TInterceptOpts> = {
  interceptOpts: TInterceptOpts | undefined;
  response: Response | null;
};
declare function resolveAppPageGenerateStaticParamsSources(options: ResolveAppPageGenerateStaticParamsSourcesOptions): GenerateStaticParamsSource[];
declare function validateAppPageDynamicParams(options: ValidateAppPageDynamicParamsOptions): Promise<Response | null>;
/**
 * Pure: decides whether the incoming request should re-render an intercepted
 * source-route tree, and if so returns the source route, the source-route's
 * param slice, the full matched param set (the URL params the client sees),
 * and an opaque `interceptOpts` bag for the caller's render pipeline.
 *
 * Returns `null` in three decision-fallthrough cases:
 *   - non-RSC requests (server rendering the direct page for a full HTML load)
 *   - no intercepting route matches the path
 *   - the match's source route IS the current route (the same branch today
 *     returns `interceptOpts` for the direct render)
 *
 * Shared by both the GET path (resolveAppPageIntercept, which layers on
 * `setNavigationContext` + element build + Response wrap) and the server-action
 * POST path (entries/app-rsc-entry.ts), which runs its own response pipeline.
 */
declare function resolveAppPageInterceptMatch<TRoute, TPage, TInterceptOpts>(options: ResolveAppPageInterceptMatchOptions<TRoute, TPage, TInterceptOpts>): ResolveAppPageInterceptMatchResult<TRoute, TInterceptOpts> | null;
declare function resolveAppPageActionRerenderTarget<TRoute, TPage, TInterceptOpts>(options: ResolveAppPageActionRerenderTargetOptions<TRoute, TPage, TInterceptOpts>): ResolveAppPageActionRerenderTargetResult<TRoute, TInterceptOpts>;
declare function resolveAppPageIntercept<TRoute, TPage, TInterceptOpts, TElement>(options: ResolveAppPageInterceptOptions<TRoute, TPage, TInterceptOpts, TElement>): Promise<ResolveAppPageInterceptResult<TInterceptOpts>>;
declare function buildAppPageElement<TElement>(options: BuildAppPageElementOptions<TElement>): Promise<BuildAppPageElementResult<TElement>>;
//#endregion
export { ValidateAppPageDynamicParamsOptions, buildAppPageElement, resolveAppPageActionRerenderTarget, resolveAppPageGenerateStaticParamsSources, resolveAppPageIntercept, resolveAppPageInterceptMatch, validateAppPageDynamicParams };
//# sourceMappingURL=app-page-request.d.ts.map