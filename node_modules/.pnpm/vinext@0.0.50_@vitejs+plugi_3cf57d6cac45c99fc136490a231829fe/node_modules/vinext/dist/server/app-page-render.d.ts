import { CachedAppPageValue } from "../shims/cache.js";
import { AppOutgoingElements } from "./app-elements-wire.js";
import { AppPageFontPreload, AppPageSpecialError, LayoutClassificationOptions } from "./app-page-execution.js";
import { AppPageMiddlewareContext } from "./app-page-response.js";
import { AppPageSsrHandler } from "./app-page-stream.js";
import { AppRscRenderMode } from "./app-rsc-render-mode.js";
import { ReactNode } from "react";
import { ReactFormState } from "react-dom/client";

//#region src/server/app-page-render.d.ts
type AppPageBoundaryOnError = (error: unknown, requestInfo: unknown, errorContext: unknown) => unknown;
type AppPageDebugLogger = (event: string, detail: string) => void;
type AppPageCacheSetter = (key: string, data: CachedAppPageValue, revalidateSeconds: number, tags: string[], expireSeconds?: number) => Promise<void>;
type AppPageRequestCacheLife = {
  revalidate?: number;
  expire?: number;
};
type RenderAppPageLifecycleOptions = {
  cleanPathname: string;
  clearRequestContext: () => void;
  consumeDynamicUsage: () => boolean; /** Read and clear any invalid dynamic usage error recorded during render (dev-only). */
  consumeInvalidDynamicUsageError?: () => unknown;
  createRscOnErrorHandler: (pathname: string, routePath: string) => AppPageBoundaryOnError;
  getFontLinks: () => string[];
  getFontPreloads: () => AppPageFontPreload[];
  getFontStyles: () => string[];
  getNavigationContext: () => unknown;
  getPageTags: () => string[];
  getRequestCacheLife: () => AppPageRequestCacheLife | null;
  peekRequestCacheLife?: () => AppPageRequestCacheLife | null;
  getDraftModeCookieHeader: () => string | null | undefined;
  handlerStart: number;
  hasLoadingBoundary: boolean;
  isDynamicError: boolean;
  isDraftMode: boolean;
  isForceDynamic: boolean;
  isForceStatic: boolean;
  isProgressiveActionRender?: boolean;
  isPrerender?: boolean;
  isProduction: boolean;
  isRscRequest: boolean;
  isrDebug?: AppPageDebugLogger;
  isrHtmlKey: (pathname: string) => string;
  isrRscKey: (pathname: string, mountedSlotsHeader?: string | null, renderMode?: AppRscRenderMode) => string;
  isrSet: AppPageCacheSetter;
  layoutCount: number;
  loadSsrHandler: () => Promise<AppPageSsrHandler>;
  middlewareContext: AppPageMiddlewareContext;
  params: Record<string, unknown>;
  probeLayoutAt: (layoutIndex: number) => unknown;
  probePage: () => unknown;
  expireSeconds?: number;
  formState?: ReactFormState | null;
  revalidateSeconds: number | null;
  renderErrorBoundaryResponse: (error: unknown) => Promise<Response | null>;
  renderLayoutSpecialError: (specialError: AppPageSpecialError, layoutIndex: number) => Promise<Response>;
  renderPageSpecialError: (specialError: AppPageSpecialError) => Promise<Response>;
  renderToReadableStream: (element: ReactNode | AppOutgoingElements, options: {
    onError: AppPageBoundaryOnError;
  }) => ReadableStream<Uint8Array>;
  routeHasLocalBoundary: boolean;
  routePattern: string;
  runWithSuppressedHookWarning<T>(probe: () => Promise<T>): Promise<T>;
  scriptNonce?: string;
  mountedSlotsHeader?: string | null;
  renderMode?: AppRscRenderMode;
  waitUntil?: (promise: Promise<void>) => void;
  element: ReactNode | Readonly<Record<string, ReactNode>>;
  classification?: LayoutClassificationOptions | null;
};
declare function renderAppPageLifecycle(options: RenderAppPageLifecycleOptions): Promise<Response>;
//#endregion
export { renderAppPageLifecycle };
//# sourceMappingURL=app-page-render.d.ts.map