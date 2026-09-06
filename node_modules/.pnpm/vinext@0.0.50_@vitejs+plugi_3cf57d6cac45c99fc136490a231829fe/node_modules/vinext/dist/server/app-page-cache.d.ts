import { CacheControlMetadata, CachedAppPageValue } from "../shims/cache.js";
import { AppRscRenderMode } from "./app-rsc-render-mode.js";
import { ISRCacheEntry } from "./isr-cache.js";

//#region src/server/app-page-cache.d.ts
type AppPageDebugLogger = (event: string, detail: string) => void;
type AppPageCacheGetter = (key: string) => Promise<ISRCacheEntry | null>;
type AppPageCacheSetter = (key: string, data: CachedAppPageValue, revalidateSeconds: number, tags: string[], expireSeconds?: number) => Promise<void>;
type AppPageBackgroundRegenerator = (key: string, renderFn: () => Promise<void>) => void;
type AppPageRequestCacheLife = {
  revalidate?: number;
  expire?: number;
};
type AppPageCacheRenderResult = {
  cacheControl?: CacheControlMetadata;
  html: string;
  rscData: ArrayBuffer;
  tags: string[];
};
type BuildAppPageCachedResponseOptions = {
  cacheControl?: CacheControlMetadata;
  cacheState: "HIT" | "STALE";
  expireSeconds?: number;
  isRscRequest: boolean;
  middlewareHeaders?: Headers | null;
  middlewareStatus?: number | null;
  mountedSlotsHeader?: string | null;
  revalidateSeconds: number;
};
type ReadAppPageCacheResponseOptions = {
  cleanPathname: string;
  clearRequestContext: () => void;
  isRscRequest: boolean;
  isrDebug?: AppPageDebugLogger;
  isrGet: AppPageCacheGetter;
  isrHtmlKey: (pathname: string) => string;
  isrRscKey: (pathname: string, mountedSlotsHeader?: string | null, renderMode?: AppRscRenderMode) => string;
  isrSet: AppPageCacheSetter;
  middlewareHeaders?: Headers | null;
  middlewareStatus?: number | null;
  mountedSlotsHeader?: string | null;
  renderMode?: AppRscRenderMode;
  expireSeconds?: number;
  revalidateSeconds: number;
  renderFreshPageForCache: () => Promise<AppPageCacheRenderResult>;
  scheduleBackgroundRegeneration: AppPageBackgroundRegenerator;
};
type FinalizeAppPageHtmlCacheResponseOptions = {
  capturedDynamicUsageBeforeContextCleanup?: () => boolean;
  capturedRscDataPromise: Promise<ArrayBuffer> | null;
  cleanPathname: string;
  consumeDynamicUsage: () => boolean;
  getPageTags: () => string[];
  getRequestCacheLife?: () => AppPageRequestCacheLife | null;
  isrDebug?: AppPageDebugLogger;
  isrHtmlKey: (pathname: string) => string;
  isrRscKey: (pathname: string, mountedSlotsHeader?: string | null, renderMode?: AppRscRenderMode) => string;
  isrSet: AppPageCacheSetter;
  preserveClientResponseHeaders?: boolean;
  expireSeconds?: number;
  revalidateSeconds: number | null;
  waitUntil?: (promise: Promise<void>) => void;
};
type ScheduleAppPageRscCacheWriteOptions = {
  capturedRscDataPromise: Promise<ArrayBuffer> | null;
  cleanPathname: string;
  consumeDynamicUsage: () => boolean;
  dynamicUsedDuringBuild: boolean;
  getPageTags: () => string[];
  getRequestCacheLife?: () => AppPageRequestCacheLife | null;
  isrDebug?: AppPageDebugLogger;
  isrRscKey: (pathname: string, mountedSlotsHeader?: string | null, renderMode?: AppRscRenderMode) => string;
  isrSet: AppPageCacheSetter;
  mountedSlotsHeader?: string | null;
  renderMode?: AppRscRenderMode;
  preserveClientResponseHeaders?: boolean;
  expireSeconds?: number;
  revalidateSeconds: number | null;
  waitUntil?: (promise: Promise<void>) => void;
};
declare function buildAppPageCacheTags(pathname: string, extraTags: readonly string[]): string[];
declare function buildAppPageCachedResponse(cachedValue: CachedAppPageValue, options: BuildAppPageCachedResponseOptions): Response | null;
declare function readAppPageCacheResponse(options: ReadAppPageCacheResponseOptions): Promise<Response | null>;
declare function finalizeAppPageHtmlCacheResponse(response: Response, options: FinalizeAppPageHtmlCacheResponseOptions): Response;
declare function finalizeAppPageRscCacheResponse(response: Response, options: ScheduleAppPageRscCacheWriteOptions): Response;
declare function scheduleAppPageRscCacheWrite(options: ScheduleAppPageRscCacheWriteOptions): boolean;
//#endregion
export { buildAppPageCacheTags, buildAppPageCachedResponse, finalizeAppPageHtmlCacheResponse, finalizeAppPageRscCacheResponse, readAppPageCacheResponse, scheduleAppPageRscCacheWrite };
//# sourceMappingURL=app-page-cache.d.ts.map