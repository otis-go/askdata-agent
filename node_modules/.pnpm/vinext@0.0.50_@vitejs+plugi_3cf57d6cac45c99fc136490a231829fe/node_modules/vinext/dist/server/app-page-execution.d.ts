import { ClassificationReason } from "../build/layout-classification-types.js";
import { LayoutFlags } from "./app-elements-wire.js";
//#region src/server/app-page-execution.d.ts
type AppPageSpecialError = {
  kind: "redirect";
  location: string;
  statusCode: number;
} | {
  kind: "http-access-fallback";
  statusCode: number;
};
type AppPageFontPreload = {
  href: string;
  type: string;
};
type AppPageRscStreamCapture = {
  /** Stream for createFromReadableStream (SSR). Always set. */ssrStream: ReadableStream<Uint8Array>; /** When capturing, the combined embed+capture stream. handleSsr consumes this. */
  sideStream?: ReadableStream<Uint8Array>;
};
type BuildAppPageSpecialErrorResponseOptions = {
  /**
   * Optional configured basePath (e.g. "/blog"). When set, redirect Locations
   * pointing at app-internal paths get prefixed so callers see e.g.
   * `Location: /blog/about` for `redirect("/about")`. Mirrors Next.js's
   * `addPathPrefix(getURLFromRedirectError(err), basePath)` in app-render.tsx.
   * External URLs (those that resolve to a different origin than the request)
   * are left untouched.
   */
  basePath?: string;
  clearRequestContext: () => void;
  /**
   * Drains and returns Set-Cookie header values that were accumulated during
   * this render via cookies().set() / cookies().delete(). Appended to redirect
   * responses so an auth flow that does `cookies().set("session", "...");
   * redirect("/")` preserves the cookie on the 307. Mirrors Next.js's
   * `appendMutableCookies(headers, requestStore.mutableCookies)` in
   * app-render.tsx. Only applied to redirect responses to match Next.js;
   * the http-access-fallback path leaves cookies to the rendered boundary.
   */
  getAndClearPendingCookies?: () => string[];
  isRscRequest: boolean;
  middlewareContext?: {
    headers: Headers | null;
  };
  renderFallbackPage?: (statusCode: number) => Promise<Response | null>;
  request: Request;
  specialError: AppPageSpecialError;
};
type ProbeAppPageLayoutsResult = {
  response: Response | null;
  layoutFlags: LayoutFlags;
};
type LayoutClassificationOptions = {
  /** Build-time classifications from segment config or module graph, keyed by layout index. */buildTimeClassifications?: ReadonlyMap<number, "static" | "dynamic"> | null;
  /**
   * Per-layout classification reasons keyed by layout index. Requires
   * `VINEXT_DEBUG_CLASSIFICATION` at BOTH lifecycle points: at build time so
   * the plugin patches the `__VINEXT_CLASS_REASONS` dispatch stub, and at
   * runtime so the route object actually calls it. Setting the flag only at
   * runtime leaves the stub returning `null`, and every build-time classified
   * layout will fall through to `{ layer: "no-classifier" }` in the debug
   * channel. The hot path never reads this and the wire payload is unchanged.
   */
  buildTimeReasons?: ReadonlyMap<number, ClassificationReason> | null;
  /**
   * Emits one log line per layout with the classification reason, keyed by
   * layout ID. Set by the generator when `VINEXT_DEBUG_CLASSIFICATION` is
   * active. When undefined, the probe loop skips debug emission entirely.
   */
  debugClassification?: (layoutId: string, reason: ClassificationReason) => void; /** Maps layout index to its layout ID (e.g. "layout:/blog"). */
  getLayoutId: (layoutIndex: number) => string; /** Runs a function with isolated dynamic usage tracking per layout. */
  runWithIsolatedDynamicScope: <T>(fn: () => T) => Promise<{
    result: T;
    dynamicDetected: boolean;
  }>;
};
type ProbeAppPageLayoutsOptions = {
  layoutCount: number;
  onLayoutError: (error: unknown, layoutIndex: number) => Promise<Response | null>;
  probeLayoutAt: (layoutIndex: number) => unknown;
  runWithSuppressedHookWarning<T>(probe: () => Promise<T>): Promise<T>; /** When provided, enables per-layout static/dynamic classification. */
  classification?: LayoutClassificationOptions | null;
};
type ProbeAppPageComponentOptions = {
  awaitAsyncResult: boolean;
  onError: (error: unknown) => Promise<Response | null>;
  probePage: () => unknown;
  runWithSuppressedHookWarning<T>(probe: () => Promise<T>): Promise<T>;
};
declare function resolveAppPageSpecialError(error: unknown): AppPageSpecialError | null;
declare function buildAppPageSpecialErrorResponse(options: BuildAppPageSpecialErrorResponseOptions): Promise<Response>;
/** See `LayoutFlags` type docblock in app-elements.ts for lifecycle. */
declare function probeAppPageLayouts(options: ProbeAppPageLayoutsOptions): Promise<ProbeAppPageLayoutsResult>;
declare function probeAppPageComponent(options: ProbeAppPageComponentOptions): Promise<Response | null>;
declare function readAppPageBinaryStream(stream: ReadableStream<Uint8Array>): Promise<ArrayBuffer>;
declare function teeAppPageRscStreamForCapture(stream: ReadableStream<Uint8Array>, shouldCapture: boolean): AppPageRscStreamCapture;
declare function buildAppPageFontLinkHeader(preloads: readonly AppPageFontPreload[] | null | undefined): string;
//#endregion
export { AppPageFontPreload, AppPageSpecialError, type ClassificationReason, LayoutClassificationOptions, type LayoutFlags, buildAppPageFontLinkHeader, buildAppPageSpecialErrorResponse, probeAppPageComponent, probeAppPageLayouts, readAppPageBinaryStream, resolveAppPageSpecialError, teeAppPageRscStreamForCapture };
//# sourceMappingURL=app-page-execution.d.ts.map