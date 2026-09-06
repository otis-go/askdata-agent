import { MetadataFileRoute } from "./metadata-routes.js";
import { AppElements } from "./app-elements-wire.js";
import { AppPageParams } from "./app-page-boundary.js";
import { AppPageFontPreload } from "./app-page-execution.js";
import { AppPageMiddlewareContext } from "./app-page-response.js";
import { AppPageSsrHandler } from "./app-page-stream.js";
import { AppPageBoundaryRoute } from "./app-page-boundary-render.js";
import * as _$react from "react";
import { ReactNode } from "react";

//#region src/server/app-fallback-renderer.d.ts
type AppPageComponent = _$react.ComponentType<any>;
type AppPageModule = Record<string, unknown> & {
  default?: AppPageComponent | null | undefined;
};
type AppPageBoundaryOnError = (error: unknown, requestInfo: unknown, errorContext: unknown) => unknown;
type AppFallbackRendererRootBoundaries<TModule extends AppPageModule = AppPageModule> = {
  rootForbiddenModule?: TModule | null;
  rootLayouts: readonly (TModule | null | undefined)[];
  rootNotFoundModule?: TModule | null;
  rootUnauthorizedModule?: TModule | null;
};
type AppFallbackRendererFontProviders = {
  buildFontLinkHeader: (preloads: readonly AppPageFontPreload[] | null | undefined) => string;
  getFontLinks: () => string[];
  getFontPreloads: () => AppPageFontPreload[];
  getFontStyles: () => string[];
};
type AppFallbackRendererOptions<TModule extends AppPageModule = AppPageModule> = {
  clearRequestContext: () => void;
  createRscOnErrorHandler: (request: Request, pathname: string, routePath: string) => AppPageBoundaryOnError;
  fontProviders: AppFallbackRendererFontProviders;
  getNavigationContext: () => unknown;
  globalErrorModule?: TModule | null;
  makeThenableParams: (params: AppPageParams) => unknown;
  metadataRoutes: MetadataFileRoute[];
  resolveChildSegments: (routeSegments: readonly string[], treePosition: number, params: AppPageParams) => string[];
  rootBoundaries: AppFallbackRendererRootBoundaries<TModule>;
  rscRenderer: (element: ReactNode | AppElements, options: {
    onError: AppPageBoundaryOnError;
  }) => ReadableStream<Uint8Array>;
  sanitizer: (error: Error) => Error;
  ssrLoader: () => Promise<AppPageSsrHandler>;
};
type AppFallbackRenderer<TModule extends AppPageModule = AppPageModule> = {
  renderErrorBoundary: (route: AppPageBoundaryRoute<TModule> | null, error: unknown, isRscRequest: boolean, request: Request, matchedParams: AppPageParams | undefined, scriptNonce: string | undefined, middlewareContext: AppPageMiddlewareContext) => Promise<Response | null>;
  renderHttpAccessFallback: (route: AppPageBoundaryRoute<TModule> | null, statusCode: number, isRscRequest: boolean, request: Request, opts: {
    boundaryComponent?: AppPageComponent | null;
    layouts?: readonly (TModule | null | undefined)[] | null;
    matchedParams?: AppPageParams;
  }, scriptNonce: string | undefined, middlewareContext: AppPageMiddlewareContext) => Promise<Response | null>;
  renderNotFound: (route: AppPageBoundaryRoute<TModule> | null, isRscRequest: boolean, request: Request, matchedParams: AppPageParams | undefined, scriptNonce: string | undefined, middlewareContext: AppPageMiddlewareContext) => Promise<Response | null>;
};
declare function createAppFallbackRenderer<TModule extends AppPageModule>(options: AppFallbackRendererOptions<TModule>): AppFallbackRenderer<TModule>;
//#endregion
export { createAppFallbackRenderer };
//# sourceMappingURL=app-fallback-renderer.d.ts.map