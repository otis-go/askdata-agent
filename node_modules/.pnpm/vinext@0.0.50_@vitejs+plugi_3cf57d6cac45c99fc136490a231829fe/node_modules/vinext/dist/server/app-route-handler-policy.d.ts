import { RouteHandlerHttpMethod, RouteHandlerModule } from "./app-route-handler-runtime.js";

//#region src/server/app-route-handler-policy.d.ts
type AppRouteHandlerModule = {
  dynamic?: string;
  revalidate?: unknown;
} & RouteHandlerModule;
type AppRouteHandlerFunction = (...args: unknown[]) => unknown;
type ResolvedAppRouteHandlerMethod = {
  allowHeaderForOptions: string;
  exportedMethods: RouteHandlerHttpMethod[];
  handlerFn: AppRouteHandlerFunction | undefined;
  isAutoHead: boolean;
  shouldAutoRespondToOptions: boolean;
};
type AppRouteHandlerCacheReadOptions = {
  dynamicConfig?: string;
  handlerFn: unknown;
  isAutoHead: boolean;
  isKnownDynamic: boolean;
  isProduction: boolean;
  method: string;
  revalidateSeconds: number | null;
};
type AppRouteHandlerResponseCacheOptions = {
  dynamicConfig?: string;
  dynamicUsedInHandler: boolean;
  handlerSetCacheControl: boolean;
  isAutoHead: boolean;
  isProduction: boolean;
  method: string;
  revalidateSeconds: number | null;
};
type AppRouteHandlerSpecialError = {
  kind: "redirect";
  location: string;
  statusCode: number;
} | {
  kind: "status";
  statusCode: number;
};
type AppRouteHandlerSpecialErrorOptions = {
  isAction: boolean;
};
declare function isPossibleAppRouteActionRequest(request: Pick<Request, "headers" | "method">): boolean;
declare function getAppRouteHandlerRevalidateSeconds(handler: Pick<AppRouteHandlerModule, "revalidate">): number | null;
declare function hasAppRouteHandlerDefaultExport(handler: RouteHandlerModule): boolean;
declare function resolveAppRouteHandlerMethod(handler: AppRouteHandlerModule, method: string): ResolvedAppRouteHandlerMethod;
declare function shouldReadAppRouteHandlerCache(options: AppRouteHandlerCacheReadOptions): boolean;
declare function shouldApplyAppRouteHandlerRevalidateHeader(options: Omit<AppRouteHandlerResponseCacheOptions, "dynamicConfig" | "isProduction">): boolean;
declare function shouldWriteAppRouteHandlerCache(options: AppRouteHandlerResponseCacheOptions): boolean;
declare function resolveAppRouteHandlerSpecialError(error: unknown, requestUrl: string, options?: AppRouteHandlerSpecialErrorOptions): AppRouteHandlerSpecialError | null;
//#endregion
export { AppRouteHandlerModule, getAppRouteHandlerRevalidateSeconds, hasAppRouteHandlerDefaultExport, isPossibleAppRouteActionRequest, resolveAppRouteHandlerMethod, resolveAppRouteHandlerSpecialError, shouldApplyAppRouteHandlerRevalidateHeader, shouldReadAppRouteHandlerCache, shouldWriteAppRouteHandlerCache };
//# sourceMappingURL=app-route-handler-policy.d.ts.map