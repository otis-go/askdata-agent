import { MetadataFileRoute } from "./metadata-routes.js";
import { AppElements } from "./app-elements-wire.js";
import { AppPageParams } from "./app-page-boundary.js";
import { AppPageFontPreload } from "./app-page-execution.js";
import { AppPageMiddlewareContext } from "./app-page-response.js";
import { AppPageSsrHandler } from "./app-page-stream.js";
import { ComponentType, ReactNode } from "react";

//#region src/server/app-page-boundary-render.d.ts
type AppPageComponent = ComponentType<any>;
type AppPageModule = Record<string, unknown> & {
  default?: AppPageComponent | null | undefined;
};
type AppPageBoundaryOnError = (error: unknown, requestInfo: unknown, errorContext: unknown) => unknown;
type AppPageBoundaryRoute<TModule extends AppPageModule = AppPageModule> = {
  error?: TModule | null;
  errorPaths?: readonly TModule[] | null;
  errors?: readonly (TModule | null | undefined)[] | null;
  forbidden?: TModule | null;
  layoutTreePositions?: readonly number[] | null;
  layouts?: readonly (TModule | null | undefined)[];
  notFound?: TModule | null;
  params?: AppPageParams;
  pattern?: string;
  routeSegments?: readonly string[];
  unauthorized?: TModule | null;
};
type AppPageBoundaryRenderCommonOptions<TModule extends AppPageModule = AppPageModule> = {
  buildFontLinkHeader: (preloads: readonly AppPageFontPreload[] | null | undefined) => string;
  clearRequestContext: () => void;
  createRscOnErrorHandler: (pathname: string, routePath: string) => AppPageBoundaryOnError;
  getFontLinks: () => string[];
  getFontPreloads: () => AppPageFontPreload[];
  getFontStyles: () => string[];
  getNavigationContext: () => unknown;
  globalErrorModule?: TModule | null;
  isRscRequest: boolean;
  loadSsrHandler: () => Promise<AppPageSsrHandler>;
  makeThenableParams: (params: AppPageParams) => unknown;
  middlewareContext: AppPageMiddlewareContext;
  metadataRoutes: MetadataFileRoute[];
  renderToReadableStream: (element: ReactNode | AppElements, options: {
    onError: AppPageBoundaryOnError;
  }) => ReadableStream<Uint8Array>;
  requestUrl: string;
  resolveChildSegments: (routeSegments: readonly string[], treePosition: number, params: AppPageParams) => string[];
  rootLayouts: readonly (TModule | null | undefined)[];
  scriptNonce?: string;
};
type RenderAppPageHttpAccessFallbackOptions<TModule extends AppPageModule = AppPageModule> = {
  boundaryComponent?: AppPageComponent | null;
  layoutModules?: readonly (TModule | null | undefined)[] | null;
  matchedParams: AppPageParams;
  rootForbiddenModule?: TModule | null;
  rootNotFoundModule?: TModule | null;
  rootUnauthorizedModule?: TModule | null;
  route?: AppPageBoundaryRoute<TModule> | null;
  statusCode: number;
} & AppPageBoundaryRenderCommonOptions<TModule>;
type RenderAppPageErrorBoundaryOptions<TModule extends AppPageModule = AppPageModule> = {
  error: unknown;
  matchedParams?: AppPageParams | null;
  route?: AppPageBoundaryRoute<TModule> | null;
  sanitizeErrorForClient: (error: Error) => Error;
} & AppPageBoundaryRenderCommonOptions<TModule>;
declare function renderAppPageHttpAccessFallback<TModule extends AppPageModule>(options: RenderAppPageHttpAccessFallbackOptions<TModule>): Promise<Response | null>;
declare function renderAppPageErrorBoundary<TModule extends AppPageModule>(options: RenderAppPageErrorBoundaryOptions<TModule>): Promise<Response | null>;
//#endregion
export { AppPageBoundaryRoute, renderAppPageErrorBoundary, renderAppPageHttpAccessFallback };
//# sourceMappingURL=app-page-boundary-render.d.ts.map