import { AppRscRenderMode } from "./app-rsc-render-mode.js";
import { FetchCacheMode } from "../shims/fetch-cache.js";
import { HeadersAccessPhase } from "../shims/headers.js";
import { ReactFormState } from "react-dom/client";

//#region src/server/app-server-action-execution.d.ts
type AppPageParams = Record<string, string | string[]>;
type AppServerActionErrorReporter = (error: Error, request: {
  path: string;
  method: string;
  headers: Record<string, string>;
}, route: {
  routerKind: "App Router";
  routePath: string;
  routeType: "action";
}) => void;
type AppServerActionDecoder = (body: FormData) => Promise<unknown>;
type AppServerActionFormStateDecoder = (actionResult: unknown, body: FormData) => Promise<ReactFormState | undefined>;
type ReadFormDataWithLimit = (request: Request, maxBytes: number) => Promise<FormData>;
type ReadBodyWithLimit = (request: Request, maxBytes: number) => Promise<string>;
type AppServerActionReturnValue = {
  data: unknown;
  ok: true;
} | {
  data: unknown;
  ok: false;
};
type AppServerActionRoute = {
  pattern: string;
};
type ProgressiveServerActionResult = {
  formState: ReactFormState | null;
  kind: "form-state";
};
type AppServerActionMatch<TRoute extends AppServerActionRoute> = {
  params: AppPageParams;
  route: TRoute;
};
type AppServerActionIntercept<TPage = unknown> = {
  matchedParams: AppPageParams;
  page: TPage;
  slotKey: string;
  sourceRouteIndex: number;
};
type BuildServerActionPageElementOptions<TRoute extends AppServerActionRoute, TInterceptOpts> = {
  cleanPathname: string;
  interceptOpts: TInterceptOpts | undefined;
  isRscRequest: boolean;
  mountedSlotsHeader: string | null;
  params: AppPageParams;
  request: Request;
  route: TRoute;
  searchParams: URLSearchParams;
  renderMode: AppRscRenderMode;
};
type AppServerActionRscModel<TElement> = {
  /**
   * Omitted when the action did not invalidate page data. This mirrors Next.js'
   * empty Flight payload for non-revalidating fetch actions: the client resolves
   * the action value without committing a visible router update.
   */
  root?: TElement;
  returnValue: AppServerActionReturnValue;
};
type RenderServerActionRscStreamOptions<TTemporaryReferences> = {
  onError: (error: unknown) => unknown;
  temporaryReferences: TTemporaryReferences;
};
type DecodeServerActionReplyOptions<TTemporaryReferences> = {
  temporaryReferences: TTemporaryReferences;
};
type HandleProgressiveServerActionRequestOptions = {
  actionId: string | null;
  allowedOrigins: string[];
  cleanPathname: string;
  clearRequestContext: () => void;
  contentType: string;
  decodeAction: AppServerActionDecoder;
  decodeFormState: AppServerActionFormStateDecoder;
  getAndClearPendingCookies: () => string[];
  getDraftModeCookieHeader: () => string | null | undefined;
  maxActionBodySize: number;
  middlewareHeaders: Headers | null;
  readFormDataWithLimit: ReadFormDataWithLimit;
  reportRequestError: AppServerActionErrorReporter;
  request: Request;
  setHeadersAccessPhase: (phase: HeadersAccessPhase) => HeadersAccessPhase;
};
type HandleServerActionRscRequestOptions<TElement, TRoute extends AppServerActionRoute, TInterceptOpts, TTemporaryReferences, TPage = unknown> = {
  actionId: string | null;
  allowedOrigins: string[];
  buildPageElement: (options: BuildServerActionPageElementOptions<TRoute, TInterceptOpts>) => TElement;
  cleanPathname: string;
  clearRequestContext: () => void;
  contentType: string;
  createNotFoundElement: (routeId: string) => TElement;
  createPayloadRouteId: (pathname: string, interceptionContext: string | null) => string;
  createRscOnErrorHandler: (request: Request, pathname: string, pattern: string) => (error: unknown) => unknown;
  createTemporaryReferenceSet: () => TTemporaryReferences;
  decodeReply: (body: string | FormData, options: DecodeServerActionReplyOptions<TTemporaryReferences>) => Promise<unknown[]> | unknown[];
  findIntercept: (pathname: string) => AppServerActionIntercept<TPage> | null;
  getAndClearPendingCookies: () => string[];
  getDraftModeCookieHeader: () => string | null | undefined;
  getRouteParamNames: (route: TRoute) => readonly string[];
  getSourceRoute: (sourceRouteIndex: number) => TRoute | undefined;
  isRscRequest: boolean;
  loadServerAction: (actionId: string) => Promise<unknown>;
  matchRoute: (pathname: string) => AppServerActionMatch<TRoute> | null;
  maxActionBodySize: number;
  middlewareHeaders: Headers | null;
  middlewareStatus: number | null | undefined;
  mountedSlotsHeader: string | null;
  readBodyWithLimit: ReadBodyWithLimit;
  readFormDataWithLimit: ReadFormDataWithLimit;
  renderToReadableStream: (model: AppServerActionRscModel<TElement>, options: RenderServerActionRscStreamOptions<TTemporaryReferences>) => BodyInit | null | Promise<BodyInit | null>;
  reportRequestError: AppServerActionErrorReporter;
  resolveRouteFetchCacheMode?: (route: TRoute) => FetchCacheMode | null;
  request: Request;
  sanitizeErrorForClient: (error: unknown) => unknown;
  searchParams: URLSearchParams;
  setHeadersAccessPhase: (phase: HeadersAccessPhase) => HeadersAccessPhase;
  setNavigationContext: (context: {
    params: AppPageParams;
    pathname: string;
    searchParams: URLSearchParams;
  }) => void;
  toInterceptOpts: (intercept: AppServerActionIntercept<TPage>) => TInterceptOpts;
};
declare function readActionBodyWithLimit(request: Request, maxBytes: number): Promise<string>;
declare function readActionFormDataWithLimit(request: Request, maxBytes: number): Promise<FormData>;
declare function isProgressiveServerActionRequest(request: Pick<Request, "method">, contentType: string, actionId: string | null): boolean;
declare function handleProgressiveServerActionRequest(options: HandleProgressiveServerActionRequestOptions): Promise<Response | ProgressiveServerActionResult | null>;
declare function handleServerActionRscRequest<TElement, TRoute extends AppServerActionRoute, TInterceptOpts, TTemporaryReferences, TPage = unknown>(options: HandleServerActionRscRequestOptions<TElement, TRoute, TInterceptOpts, TTemporaryReferences, TPage>): Promise<Response | null>;
//#endregion
export { HandleProgressiveServerActionRequestOptions, HandleServerActionRscRequestOptions, handleProgressiveServerActionRequest, handleServerActionRscRequest, isProgressiveServerActionRequest, readActionBodyWithLimit, readActionFormDataWithLimit };
//# sourceMappingURL=app-server-action-execution.d.ts.map