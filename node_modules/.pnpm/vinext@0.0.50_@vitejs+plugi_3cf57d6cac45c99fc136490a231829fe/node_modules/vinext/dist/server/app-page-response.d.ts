import { mergeMiddlewareResponseHeaders } from "./middleware-response-headers.js";

//#region src/server/app-page-response.d.ts
type AppPageMiddlewareContext = {
  headers: Headers | null;
  status: number | null;
};
type AppPageResponseTiming = {
  compileEnd?: number;
  handlerStart: number;
  renderEnd?: number;
  responseKind: "html" | "rsc";
};
type AppPageResponsePolicy = {
  cacheControl?: string;
  cacheState?: "MISS" | "STATIC";
};
type ResolveAppPageResponsePolicyBaseOptions = {
  isDraftMode: boolean;
  isDynamicError: boolean;
  isForceDynamic: boolean;
  isForceStatic: boolean;
  isProduction: boolean;
  expireSeconds?: number;
  revalidateSeconds: number | null;
};
type ResolveAppPageRscResponsePolicyOptions = {
  dynamicUsedDuringBuild: boolean;
} & ResolveAppPageResponsePolicyBaseOptions;
type ResolveAppPageHtmlResponsePolicyOptions = {
  dynamicUsedDuringRender: boolean;
  isProgressiveActionRender?: boolean;
  hasScriptNonce: boolean;
} & ResolveAppPageResponsePolicyBaseOptions;
type AppPageHtmlResponsePolicy = {
  shouldWriteToCache: boolean;
} & AppPageResponsePolicy;
type BuildAppPageRscResponseOptions = {
  middlewareContext: AppPageMiddlewareContext;
  mountedSlotsHeader?: string | null;
  params?: Record<string, unknown>;
  policy: AppPageResponsePolicy;
  timing?: AppPageResponseTiming;
};
type BuildAppPageHtmlResponseOptions = {
  draftCookie?: string | null;
  fontLinkHeader?: string;
  middlewareContext: AppPageMiddlewareContext;
  policy: AppPageResponsePolicy;
  timing?: AppPageResponseTiming;
};
declare function resolveAppPageRscResponsePolicy(options: ResolveAppPageRscResponsePolicyOptions): AppPageResponsePolicy;
declare function resolveAppPageHtmlResponsePolicy(options: ResolveAppPageHtmlResponsePolicyOptions): AppPageHtmlResponsePolicy;
declare function buildAppPageRscResponse(body: ReadableStream, options: BuildAppPageRscResponseOptions): Response;
declare function buildAppPageHtmlResponse(body: ReadableStream, options: BuildAppPageHtmlResponseOptions): Response;
//#endregion
export { AppPageMiddlewareContext, AppPageResponseTiming, buildAppPageHtmlResponse, buildAppPageRscResponse, mergeMiddlewareResponseHeaders, resolveAppPageHtmlResponsePolicy, resolveAppPageRscResponsePolicy };
//# sourceMappingURL=app-page-response.d.ts.map