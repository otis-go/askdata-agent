import { ClassificationReason } from "../build/layout-classification-types.js";
import { CachedAppPageValue } from "../shims/cache.js";
import { AppOutgoingElements } from "./app-elements-wire.js";
import { AppPageFontPreload, LayoutClassificationOptions } from "./app-page-execution.js";
import { AppPageMiddlewareContext } from "./app-page-response.js";
import { AppPageSsrHandler } from "./app-page-stream.js";
import { AppRscRenderMode } from "./app-rsc-render-mode.js";
import { ISRCacheEntry } from "./isr-cache.js";
import { FetchCacheMode } from "../shims/fetch-cache.js";
import { ValidateAppPageDynamicParamsOptions } from "./app-page-request.js";
import { ReactNode } from "react";
import { ReactFormState } from "react-dom/client";

//#region src/server/app-page-dispatch.d.ts
type AppPageParams = Record<string, string | string[]>;
type AppPageElement = ReactNode | Readonly<Record<string, ReactNode>>;
type AppPageRenderableElement = ReactNode | AppOutgoingElements;
type AppPageBoundaryOnError = (error: unknown, requestInfo: unknown, errorContext: unknown) => unknown;
type AppPageDebugLogger = (event: string, detail: string) => void;
type AppPageCacheSetter = (key: string, data: CachedAppPageValue, revalidateSeconds: number, tags: string[], expireSeconds?: number) => Promise<void>;
type AppPageCacheGetter = (key: string) => Promise<ISRCacheEntry | null>;
type AppPageBackgroundRegenerationErrorContext = {
  routerKind: "App Router";
  routePath: string;
  routeType: "render";
};
type AppPageBackgroundRegenerator = (key: string, renderFn: () => Promise<void>, errorContext?: AppPageBackgroundRegenerationErrorContext) => void;
type AppPageDispatchIntercept<TPage = unknown> = {
  interceptLayouts?: readonly AppPageModule[] | null;
  matchedParams: AppPageParams;
  page: TPage;
  slotKey: string;
  sourceRouteIndex: number;
};
type AppPageDispatchInterceptOptions<TPage = unknown> = {
  interceptionContext: string | null;
  interceptLayouts?: readonly AppPageModule[] | null;
  interceptPage: TPage;
  interceptParams: AppPageParams;
  interceptSlotKey: string;
};
type AppPageModule = {
  default?: unknown;
};
type AppPageDispatchRoute = {
  __buildTimeClassifications?: LayoutClassificationOptions["buildTimeClassifications"];
  __buildTimeReasons?: LayoutClassificationOptions["buildTimeReasons"];
  error?: AppPageModule | null;
  errors?: readonly (AppPageModule | null | undefined)[];
  forbiddens?: readonly (AppPageModule | null | undefined)[];
  isDynamic: boolean;
  layouts: readonly AppPageModule[];
  layoutTreePositions?: readonly number[];
  loading?: AppPageModule | null;
  notFounds?: readonly (AppPageModule | null | undefined)[];
  params: readonly string[];
  pattern: string;
  routeSegments: readonly string[];
  unauthorizeds?: readonly (AppPageModule | null | undefined)[];
};
type DispatchAppPageOptions<TRoute extends AppPageDispatchRoute> = {
  /** Configured basePath (e.g. "/blog"). Used to prefix redirect Locations. */basePath?: string;
  buildPageElement: (route: TRoute, params: AppPageParams, opts: AppPageDispatchInterceptOptions | undefined, searchParams: URLSearchParams) => Promise<AppPageElement>;
  cleanPathname: string;
  clearRequestContext: () => void;
  createRscOnErrorHandler: (pathname: string, routePath: string) => AppPageBoundaryOnError;
  debugClassification?: (layoutId: string, reason: ClassificationReason) => void;
  dynamicConfig?: string;
  dynamicParamsConfig?: boolean;
  fetchCache?: FetchCacheMode | null;
  findIntercept: (pathname: string) => AppPageDispatchIntercept | null;
  formState?: ReactFormState | null;
  generateStaticParams?: ValidateAppPageDynamicParamsOptions["generateStaticParams"];
  getFontLinks: () => string[];
  getFontPreloads: () => AppPageFontPreload[];
  getFontStyles: () => string[];
  getNavigationContext: () => unknown;
  getSourceRoute: (sourceRouteIndex: number) => TRoute | undefined;
  hasGenerateStaticParams: boolean;
  hasPageDefaultExport: boolean;
  hasPageModule: boolean;
  handlerStart: number;
  interceptionContext: string | null;
  isProgressiveActionRender?: boolean;
  isProduction: boolean;
  isRscRequest: boolean;
  isrDebug?: AppPageDebugLogger;
  isrGet: AppPageCacheGetter;
  isrHtmlKey: (pathname: string) => string;
  isrRscKey: (pathname: string, mountedSlotsHeader?: string | null, renderMode?: AppRscRenderMode) => string;
  isrSet: AppPageCacheSetter;
  loadSsrHandler: () => Promise<AppPageSsrHandler>;
  middlewareContext: AppPageMiddlewareContext;
  mountedSlotsHeader?: string | null;
  params: AppPageParams;
  probeLayoutAt: (layoutIndex: number) => unknown;
  probePage: () => unknown;
  expireSeconds?: number;
  renderErrorBoundaryPage: (error: unknown) => Promise<Response | null>;
  renderHttpAccessFallbackPage: (statusCode: number, opts: {
    boundaryComponent?: unknown;
    layouts?: readonly AppPageModule[];
    matchedParams: AppPageParams;
  }, middlewareContext: AppPageMiddlewareContext | null) => Promise<Response | null>;
  renderToReadableStream: (element: AppPageRenderableElement, options: {
    onError: AppPageBoundaryOnError;
  }) => ReadableStream<Uint8Array>;
  request: Request;
  revalidateSeconds: number | null;
  resolveRouteFetchCacheMode?: (route: TRoute) => FetchCacheMode | null;
  rootForbiddenModule?: AppPageModule | null;
  rootNotFoundModule?: AppPageModule | null;
  rootUnauthorizedModule?: AppPageModule | null;
  route: TRoute;
  runWithSuppressedHookWarning<T>(probe: () => Promise<T>): Promise<T>;
  scheduleBackgroundRegeneration: AppPageBackgroundRegenerator;
  scriptNonce?: string;
  searchParams: URLSearchParams;
  setNavigationContext: (context: {
    params: AppPageParams;
    pathname: string;
    searchParams: URLSearchParams;
  }) => void;
  renderMode?: AppRscRenderMode;
};
declare function dispatchAppPage<TRoute extends AppPageDispatchRoute>(options: DispatchAppPageOptions<TRoute>): Promise<Response>;
//#endregion
export { dispatchAppPage };
//# sourceMappingURL=app-page-dispatch.d.ts.map