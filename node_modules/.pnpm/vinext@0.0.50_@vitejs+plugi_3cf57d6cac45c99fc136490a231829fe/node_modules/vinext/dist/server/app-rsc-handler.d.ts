import { NextHeader, NextI18nConfig, NextRedirect, NextRewrite } from "../config/next-config.js";
import { MiddlewareModule } from "./middleware-runtime.js";
import { AppMiddlewareContext } from "./app-middleware.js";
import { AppRscRenderMode } from "./app-rsc-render-mode.js";
import { handleAppPrerenderEndpoint } from "./app-prerender-endpoints.js";
import { handleMetadataRouteRequest } from "./metadata-route-response.js";
import { ReactFormState } from "react-dom/client";

//#region src/server/app-rsc-handler.d.ts
type AppPageParams = Record<string, string | string[]>;
type MetadataRoutes = Parameters<typeof handleMetadataRouteRequest>[0]["metadataRoutes"];
type MakeThenableParams = Parameters<typeof handleMetadataRouteRequest>[0]["makeThenableParams"];
type StaticParamsMap = Parameters<typeof handleAppPrerenderEndpoint>[1]["staticParamsMap"];
type RootParamNamesMap = Parameters<typeof handleAppPrerenderEndpoint>[1]["rootParamNamesByPattern"];
type AppRscMiddlewareContext = AppMiddlewareContext;
type AppRscHandlerRoute = {
  isDynamic: boolean;
  page?: unknown;
  pattern: string;
  rootParamNames?: readonly string[];
  routeHandler?: unknown;
  routeSegments: readonly string[];
};
type AppRscRouteMatch<TRoute> = {
  params: AppPageParams;
  route: TRoute;
};
type DispatchMatchedPageOptions<TRoute> = {
  cleanPathname: string;
  formState: ReactFormState | null;
  handlerStart: number;
  interceptionContext: string | null;
  isProgressiveActionRender: boolean;
  isRscRequest: boolean;
  middlewareContext: AppRscMiddlewareContext;
  mountedSlotsHeader: string | null;
  params: AppPageParams;
  request: Request;
  route: TRoute;
  scriptNonce?: string;
  searchParams: URLSearchParams;
  renderMode: AppRscRenderMode;
};
type DispatchMatchedRouteHandlerOptions<TRoute> = {
  cleanPathname: string;
  middlewareContext: AppRscMiddlewareContext;
  params: AppPageParams;
  request: Request;
  route: TRoute;
  searchParams: URLSearchParams;
};
type HandleProgressiveActionRequestOptions = {
  actionId: string | null;
  cleanPathname: string;
  contentType: string;
  middlewareContext: AppRscMiddlewareContext;
  request: Request;
};
type HandleServerActionRequestOptions = {
  actionId: string | null;
  cleanPathname: string;
  contentType: string;
  interceptionContext: string | null;
  isRscRequest: boolean;
  middlewareContext: AppRscMiddlewareContext;
  mountedSlotsHeader: string | null;
  request: Request;
  searchParams: URLSearchParams;
};
type RenderNotFoundOptions<TRoute> = {
  isRscRequest: boolean;
  matchedParams?: AppPageParams;
  middlewareContext: AppRscMiddlewareContext;
  request: Request;
  route: TRoute | null;
  scriptNonce?: string;
};
type RenderPagesFallbackOptions = {
  isRscRequest: boolean;
  middlewareContext: AppRscMiddlewareContext;
  request: Request;
  url: URL;
};
type NavigationContextValue = {
  params: AppPageParams;
  pathname: string;
  searchParams: URLSearchParams;
};
type CreateAppRscHandlerOptions<TRoute extends AppRscHandlerRoute> = {
  basePath: string;
  clearRequestContext: () => void;
  configHeaders: NextHeader[];
  configRedirects: NextRedirect[];
  configRewrites: {
    afterFiles: NextRewrite[];
    beforeFiles: NextRewrite[];
    fallback: NextRewrite[];
  };
  dispatchMatchedPage: (options: DispatchMatchedPageOptions<TRoute>) => Promise<Response>;
  dispatchMatchedRouteHandler: (options: DispatchMatchedRouteHandlerOptions<TRoute>) => Promise<Response>;
  ensureInstrumentation?: () => Promise<void>;
  handleProgressiveActionRequest: (options: HandleProgressiveActionRequestOptions) => Promise<Response | {
    formState: ReactFormState | null;
    kind: "form-state";
  } | null>;
  handleServerActionRequest: (options: HandleServerActionRequestOptions) => Promise<Response | null>;
  i18nConfig: NextI18nConfig | null;
  isMiddlewareProxy: boolean;
  loadPrerenderPagesRoutes?: () => Promise<unknown>;
  makeThenableParams: MakeThenableParams;
  matchRoute: (pathname: string) => AppRscRouteMatch<TRoute> | null;
  metadataRoutes: MetadataRoutes;
  middlewareModule: MiddlewareModule | null;
  publicFiles: ReadonlySet<string>;
  renderNotFound: (options: RenderNotFoundOptions<TRoute>) => Promise<Response | null>;
  renderPagesFallback?: (options: RenderPagesFallbackOptions) => Promise<Response | null>;
  rootParamNamesByPattern?: RootParamNamesMap;
  setNavigationContext: (context: NavigationContextValue) => void;
  staticParamsMap: StaticParamsMap;
  trailingSlash: boolean;
  validateDevRequestOrigin?: (request: Request) => Response | null;
};
declare function createAppRscHandler<TRoute extends AppRscHandlerRoute>(options: CreateAppRscHandlerOptions<TRoute>): (request: Request, ctx: unknown) => Promise<Response>;
//#endregion
export { createAppRscHandler };
//# sourceMappingURL=app-rsc-handler.d.ts.map