import { NextI18nConfig } from "../config/next-config.js";
import { ExecutionContextLike } from "../shims/request-context.js";
import { CachedRouteValue } from "../shims/cache.js";
import { NextRequest } from "../shims/server.js";
import { HeadersAccessPhase } from "../shims/headers.js";
import { RouteHandlerMiddlewareContext } from "./app-route-handler-response.js";
import { AppRouteHandlerModule } from "./app-route-handler-policy.js";

//#region src/server/app-route-handler-execution.d.ts
type AppRouteParams = Record<string, string | string[]>;
type AppRouteDynamicUsageFn = () => boolean;
type MarkAppRouteDynamicUsageFn = () => void;
type AppRouteHandlerFunction = (request: NextRequest, context: {
  params: AppRouteParams;
}) => Response | Promise<Response>;
type RouteHandlerCacheSetter = (key: string, data: CachedRouteValue, revalidateSeconds: number, tags: string[], expireSeconds?: number) => Promise<void>;
type AppRouteErrorReporter = (error: Error, request: {
  path: string;
  method: string;
  headers: Record<string, string>;
}, route: {
  routerKind: "App Router";
  routePath: string;
  routeType: "route";
}) => void;
type AppRouteDebugLogger = (event: string, detail: string) => void;
type RunAppRouteHandlerOptions = {
  basePath?: string;
  consumeDynamicUsage: AppRouteDynamicUsageFn;
  dynamicConfig?: string;
  handlerFn: AppRouteHandlerFunction;
  i18n?: NextI18nConfig | null;
  markDynamicUsage: MarkAppRouteDynamicUsageFn;
  middlewareRequestHeaders?: Headers | null;
  params: AppRouteParams;
  request: Request;
  routePattern?: string;
  setHeadersAccessPhase?: (phase: HeadersAccessPhase) => HeadersAccessPhase;
};
type RunAppRouteHandlerResult = {
  dynamicUsedInHandler: boolean;
  response: Response;
};
type ExecuteAppRouteHandlerOptions = {
  buildPageCacheTags: (pathname: string, extraTags: string[]) => string[];
  clearRequestContext: () => void;
  cleanPathname: string;
  executionContext: ExecutionContextLike | null;
  getAndClearPendingCookies: () => string[];
  getCollectedFetchTags: () => string[];
  getDraftModeCookieHeader: () => string | null | undefined;
  handler: AppRouteHandlerModule;
  isAutoHead: boolean;
  isProduction: boolean;
  isrDebug?: AppRouteDebugLogger;
  isrRouteKey: (pathname: string) => string;
  isrSet: RouteHandlerCacheSetter;
  method: string;
  middlewareContext: RouteHandlerMiddlewareContext;
  reportRequestError: AppRouteErrorReporter;
  expireSeconds?: number;
  revalidateSeconds: number | null;
  routePattern: string;
  setHeadersAccessPhase: (phase: HeadersAccessPhase) => HeadersAccessPhase;
} & RunAppRouteHandlerOptions;
declare function runAppRouteHandler(options: RunAppRouteHandlerOptions): Promise<RunAppRouteHandlerResult>;
declare function executeAppRouteHandler(options: ExecuteAppRouteHandlerOptions): Promise<Response>;
//#endregion
export { AppRouteDebugLogger, AppRouteDynamicUsageFn, AppRouteHandlerFunction, AppRouteParams, MarkAppRouteDynamicUsageFn, RouteHandlerCacheSetter, executeAppRouteHandler, runAppRouteHandler };
//# sourceMappingURL=app-route-handler-execution.d.ts.map