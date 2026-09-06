import { AppPageFontPreload } from "./app-page-execution.js";
import { ReactFormState } from "react-dom/client";

//#region src/server/app-page-stream.d.ts
type AppPageFontData = {
  links: string[];
  preloads: readonly AppPageFontPreload[];
  styles: string[];
};
type CreateAppPageFontDataOptions = {
  getLinks: () => string[];
  getPreloads: () => AppPageFontPreload[];
  getStyles: () => string[];
};
type AppPageSsrHandler = {
  handleSsr: (rscStream: ReadableStream<Uint8Array>, navigationContext: unknown, fontData: AppPageFontData, options?: {
    formState?: ReactFormState | null;
    scriptNonce?: string;
    sideStream?: ReadableStream<Uint8Array>;
    capturedRscDataRef?: {
      value: Promise<ArrayBuffer> | null;
    }; /** When true, wait for the full React tree before emitting bytes. */
    waitForAllReady?: boolean;
  }) => Promise<ReadableStream<Uint8Array>>;
};
type RenderAppPageHtmlStreamOptions = {
  fontData: AppPageFontData;
  formState?: ReactFormState | null;
  navigationContext: unknown;
  rscStream: ReadableStream<Uint8Array>;
  scriptNonce?: string;
  ssrHandler: AppPageSsrHandler;
  /** Pre-split side stream for fused embed+capture (#981). When set,
   *  handleSsr skips its internal tee and accumulates raw RSC bytes. */
  sideStream?: ReadableStream<Uint8Array>; /** Out-parameter filled with accumulated raw RSC bytes after stream consumption. */
  capturedRscDataRef?: {
    value: Promise<ArrayBuffer> | null;
  }; /** When true, wait for the full React tree before emitting bytes. */
  waitForAllReady?: boolean;
};
type RenderAppPageHtmlResponseOptions = {
  clearRequestContext: () => void;
  fontLinkHeader?: string;
  middlewareHeaders?: Headers | null;
  status: number;
} & RenderAppPageHtmlStreamOptions;
type AppPageHtmlStreamRecoveryResult = {
  htmlStream: ReadableStream<Uint8Array> | null;
  response: Response | null;
};
type RenderAppPageHtmlStreamWithRecoveryOptions<TSpecialError> = {
  onShellRendered?: () => void;
  renderErrorBoundaryResponse: (error: unknown) => Promise<Response | null>;
  renderHtmlStream: () => Promise<ReadableStream<Uint8Array>>;
  renderSpecialErrorResponse: (specialError: TSpecialError) => Promise<Response>;
  resolveSpecialError: (error: unknown) => TSpecialError | null;
};
type AppPageRscErrorTracker = {
  getCapturedError: () => unknown;
  /**
   * Returns a NEXT_REDIRECT or NEXT_HTTP_ERROR_FALLBACK error captured during
   * the RSC render. Read after the SSR shell promise resolves to swap a
   * 307/404 in place of the streamed body when redirect()/notFound() throws
   * synchronously inside a route-level Suspense boundary (loading.tsx).
   */
  getCapturedSpecialError: () => unknown;
  onRenderError: (error: unknown, requestInfo: unknown, errorContext: unknown) => unknown;
};
type ShouldRerenderAppPageWithGlobalErrorOptions = {
  capturedError: unknown;
  hasLocalBoundary: boolean;
};
declare function createAppPageFontData(options: CreateAppPageFontDataOptions): AppPageFontData;
declare function renderAppPageHtmlStream(options: RenderAppPageHtmlStreamOptions): Promise<ReadableStream<Uint8Array>>;
/**
 * Wraps a stream so that `onFlush` is called when the last byte has been read
 * by the downstream consumer (i.e. when the HTTP layer finishes draining the
 * response body). This is the correct place to clear per-request context,
 * because the RSC/SSR pipeline is lazy — components execute while the stream
 * is being consumed, not when the stream handle is first obtained.
 */
declare function deferUntilStreamConsumed(stream: ReadableStream<Uint8Array>, onFlush: () => void): ReadableStream<Uint8Array>;
declare function renderAppPageHtmlResponse(options: RenderAppPageHtmlResponseOptions): Promise<Response>;
declare function renderAppPageHtmlStreamWithRecovery<TSpecialError>(options: RenderAppPageHtmlStreamWithRecoveryOptions<TSpecialError>): Promise<AppPageHtmlStreamRecoveryResult>;
declare function createAppPageRscErrorTracker(baseOnError: (error: unknown, requestInfo: unknown, errorContext: unknown) => unknown): AppPageRscErrorTracker;
declare function shouldRerenderAppPageWithGlobalError(options: ShouldRerenderAppPageWithGlobalErrorOptions): boolean;
//#endregion
export { AppPageFontData, AppPageSsrHandler, createAppPageFontData, createAppPageRscErrorTracker, deferUntilStreamConsumed, renderAppPageHtmlResponse, renderAppPageHtmlStream, renderAppPageHtmlStreamWithRecovery, shouldRerenderAppPageWithGlobalError };
//# sourceMappingURL=app-page-stream.d.ts.map