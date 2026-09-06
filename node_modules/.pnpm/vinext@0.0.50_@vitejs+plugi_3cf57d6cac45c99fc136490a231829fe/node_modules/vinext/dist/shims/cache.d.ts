import { CacheContext } from "./cache-runtime.js";
import { ExecutionContextLike, getRequestExecutionContext, runWithExecutionContext } from "./request-context.js";

//#region src/shims/cache.d.ts
/**
 * next/cache shim
 *
 * Provides the Next.js caching API surface: revalidateTag, revalidatePath,
 * unstable_cache. Backed by a pluggable CacheHandler that defaults to
 * in-memory but can be swapped for Cloudflare KV, Redis, DynamoDB, etc.
 *
 * The CacheHandler interface matches Next.js 16's CacheHandler class, so
 * existing community adapters (@neshca/cache-handler, @opennextjs/aws, etc.)
 * can be used directly.
 *
 * Configuration (in vite.config.ts or next.config.js):
 *   vinext({ cacheHandler: './my-cache-handler.ts' })
 *
 * Or set at runtime:
 *   import { setCacheHandler } from 'next/cache';
 *   setCacheHandler(new MyCacheHandler());
 */
type CacheContextLike = {
  tags: string[];
  lifeConfigs: CacheContext["lifeConfigs"];
  variant: string;
};
/**
 * Register the cache context accessor. Called by cache-runtime.ts on load.
 * @internal
 */
declare function _registerCacheContextAccessor(fn: () => CacheContextLike | null): void;
type CacheHandlerValue = {
  lastModified: number;
  age?: number;
  cacheState?: string;
  cacheControl?: CacheControlMetadata;
  value: IncrementalCacheValue | null;
};
type CacheControlMetadata = {
  revalidate: number;
  expire?: number;
};
/** Discriminated union of cache value types. */
type IncrementalCacheValue = CachedFetchValue | CachedAppPageValue | CachedPagesValue | CachedRouteValue | CachedRedirectValue | CachedImageValue;
type CachedFetchValue = {
  kind: "FETCH";
  data: {
    headers: Record<string, string>;
    body: string;
    url: string;
    status?: number;
  };
  tags?: string[];
  revalidate: number | false;
};
type CachedAppPageValue = {
  kind: "APP_PAGE";
  html: string;
  rscData: ArrayBuffer | undefined;
  headers: Record<string, string | string[]> | undefined;
  postponed: string | undefined;
  status: number | undefined;
};
type CachedPagesValue = {
  kind: "PAGES";
  html: string;
  pageData: object;
  headers: Record<string, string | string[]> | undefined;
  status: number | undefined;
};
type CachedRouteValue = {
  kind: "APP_ROUTE";
  body: ArrayBuffer;
  status: number;
  headers: Record<string, string | string[]>;
};
type CachedRedirectValue = {
  kind: "REDIRECT";
  props: object;
};
type CachedImageValue = {
  kind: "IMAGE";
  etag: string;
  buffer: ArrayBuffer;
  extension: string;
  revalidate?: number;
};
type CacheHandlerContext = {
  dev?: boolean;
  maxMemoryCacheSize?: number;
  revalidatedTags?: string[];
  [key: string]: unknown;
};
type CacheHandler = {
  get(key: string, ctx?: Record<string, unknown>): Promise<CacheHandlerValue | null>;
  set(key: string, data: IncrementalCacheValue | null, ctx?: Record<string, unknown>): Promise<void>;
  revalidateTag(tags: string | string[], durations?: {
    expire?: number;
  }): Promise<void>;
  resetRequestCache?(): void;
};
declare class NoOpCacheHandler implements CacheHandler {
  get(_key: string, _ctx?: Record<string, unknown>): Promise<CacheHandlerValue | null>;
  set(_key: string, _data: IncrementalCacheValue | null, _ctx?: Record<string, unknown>): Promise<void>;
  revalidateTag(_tags: string | string[], _durations?: {
    expire?: number;
  }): Promise<void>;
}
declare class MemoryCacheHandler implements CacheHandler {
  private store;
  private tagRevalidatedAt;
  get(key: string, _ctx?: Record<string, unknown>): Promise<CacheHandlerValue | null>;
  set(key: string, data: IncrementalCacheValue | null, ctx?: Record<string, unknown>): Promise<void>;
  revalidateTag(tags: string | string[], _durations?: {
    expire?: number;
  }): Promise<void>;
  resetRequestCache(): void;
}
/**
 * Set a custom CacheHandler. Call this during server startup to
 * plug in Cloudflare KV, Redis, DynamoDB, or any other backend.
 *
 * The handler must implement the CacheHandler interface (same shape
 * as Next.js 16's CacheHandler class).
 */
declare function setCacheHandler(handler: CacheHandler): void;
/**
 * Get the active CacheHandler (for internal use or testing).
 */
declare function getCacheHandler(): CacheHandler;
/**
 * Revalidate cached data associated with a specific cache tag.
 *
 * Works with both `fetch(..., { next: { tags: ['myTag'] } })` and
 * `unstable_cache(fn, keys, { tags: ['myTag'] })`.
 *
 * Next.js 16 updated signature: accepts a cacheLife profile as second argument
 * for stale-while-revalidate (SWR) behavior. The single-argument form is
 * deprecated but still supported for backward compatibility.
 *
 * @param tag - Cache tag to revalidate
 * @param profile - cacheLife profile name (e.g. 'max', 'hours') or inline { expire: number }
 */
declare function revalidateTag(tag: string, profile?: string | {
  expire?: number;
}): Promise<void>;
/**
 * Revalidate cached data associated with a specific path.
 *
 * Invalidation works through implicit tags generated at render time by
 * `buildAppPageCacheTags`, matching Next.js's getDerivedTags:
 *
 * - `type: "layout"` → invalidates `_N_T_<path>/layout`, cascading to all
 *   descendant pages (they carry ancestor layout tags from render time).
 * - `type: "page"` → invalidates `_N_T_<path>/page`, targeting only the
 *   exact route's page component.
 * - No type → invalidates `_N_T_<path>` (broader, exact path).
 *
 * The `type` parameter is App Router only — Pages Router does not generate
 * layout/page hierarchy tags, so only no-type invalidation applies there.
 */
declare function revalidatePath(path: string, type?: "page" | "layout"): Promise<void>;
/**
 * No-op shim for API compatibility.
 *
 * In Next.js, calling `refresh()` inside a Server Action triggers a
 * client-side router refresh so the user immediately sees updated data.
 * vinext reports the dynamic-only invalidation through the Server Action
 * response header that the client router already understands.
 */
declare function refresh(): void;
/**
 * Expire a cache tag immediately (Next.js 16).
 *
 * Server Actions-only API that expires a tag so the next request
 * fetches fresh data. Unlike `revalidateTag`, which uses stale-while-revalidate,
 * `updateTag` invalidates synchronously within the same request context.
 */
declare function updateTag(tag: string): Promise<void>;
/**
 * Opt out of static rendering and indicate a particular component should not be cached.
 *
 * In Next.js, calling noStore() inside a Server Component ensures the component
 * is dynamically rendered. In our implementation, this is a no-op since we don't
 * have the same static/dynamic rendering split — all server rendering is on-demand.
 * It's provided for API compatibility so apps importing it don't break.
 */
declare function unstable_noStore(): void;
/**
 * Marks an IO boundary in server components by returning a resolved promise
 * during requests and a hanging promise during prerendering.
 *
 * See: https://github.com/vercel/next.js/pull/92521
 * Guard removed: https://github.com/vercel/next.js/pull/92923
 * Stabilized (renamed from unstable_io): https://github.com/vercel/next.js/pull/93621
 *
 * Ported from Next.js: packages/next/src/server/request/io.ts
 * https://github.com/vercel/next.js/blob/canary/packages/next/src/server/request/io.ts
 *
 * Behavior by work unit type:
 * - request → resolve immediately (no delay needed for dynamic SSR)
 * - prerender / prerender-client / prerender-runtime → hang (prevent
 *   execution past IO boundary during static generation)
 * - cache / private-cache / unstable-cache → resolve immediately
 *   (caches capture IO results at fill time)
 * - generate-static-params → resolve immediately (build time, no prerender to stall)
 * - prerender-legacy → resolve immediately (no cache components)
 *
 * When no work unit store is present (e.g. client-side, standalone script),
 * resolves immediately — matching the browser/client implementation.
 */
declare function io(): Promise<void>;
/**
 * @deprecated Use `io` instead. Kept as a transitional alias since vinext
 * shipped the unstable name longer than upstream Next.js (see #805). Will be
 * removed in a future minor.
 */
declare function unstable_io(): Promise<void>;
type UnstableCacheRevalidationMode = "foreground" | "background";
type ActionRevalidationKind = 0 | 1 | 2;
type CacheState = {
  actionRevalidationKind: ActionRevalidationKind;
  requestScopedCacheLife: CacheLifeConfig | null;
  unstableCacheRevalidation: UnstableCacheRevalidationMode;
};
/**
 * Run a function within a cache state ALS scope.
 * Ensures per-request isolation for request-scoped cacheLife config
 * on concurrent runtimes.
 * @internal
 */
declare function _runWithCacheState<T>(fn: () => Promise<T>): Promise<T>;
declare function _runWithCacheState<T>(fn: () => T | Promise<T>): T | Promise<T>;
/**
 * Initialize cache ALS for a new request. Call at request entry.
 * Only needed when not using _runWithCacheState() (legacy path).
 * @internal
 */
declare function _initRequestScopedCacheState(): void;
declare function getAndClearActionRevalidationKind(): ActionRevalidationKind;
/**
 * Set a request-scoped cache life config. Called by cacheLife() so the route
 * render can inherit cache policy from file-level and nested "use cache" work.
 * @internal
 */
declare function _setRequestScopedCacheLife(config: CacheLifeConfig): void;
/**
 * Read the request-scoped cache life without clearing it. Prerender response
 * shaping needs the metadata before the manifest writer consumes it after the
 * body has been fully rendered.
 * @internal
 */
declare function _peekRequestScopedCacheLife(): CacheLifeConfig | null;
/**
 * Consume and reset the request-scoped cache life. Returns null if none was set.
 * @internal
 */
declare function _consumeRequestScopedCacheLife(): CacheLifeConfig | null;
/**
 * Cache life configuration. Controls stale-while-revalidate behavior.
 */
type CacheLifeConfig = {
  /** How long (seconds) the client can cache without checking the server */stale?: number; /** How frequently (seconds) the server cache refreshes */
  revalidate?: number; /** Max staleness (seconds) before deoptimizing to dynamic */
  expire?: number;
};
/**
 * Built-in cache life profiles matching Next.js 16.
 */
declare const cacheLifeProfiles: Record<string, CacheLifeConfig>;
/**
 * Set the cache lifetime for a "use cache" function.
 *
 * Accepts either a built-in profile name (e.g., "hours", "days") or a custom
 * configuration object. In Next.js, this only works inside "use cache" functions.
 *
 * When called inside a "use cache" function, this sets the cache TTL.
 * The "minimum-wins" rule applies: if called multiple times, the shortest
 * duration for each field wins.
 *
 * When called outside a "use cache" context, this is a validated no-op.
 */
declare function cacheLife(profile: string | CacheLifeConfig): void;
/**
 * Tag a "use cache" function's cached result for on-demand revalidation.
 *
 * Tags set here can be invalidated via revalidateTag(). In Next.js, this only
 * works inside "use cache" functions.
 *
 * When called inside a "use cache" function, tags are attached to the cached
 * entry. They can later be invalidated via revalidateTag().
 *
 * When called outside a "use cache" context, this is a no-op.
 */
declare function cacheTag(...tags: string[]): void;
declare function unstable_cacheLife(profile: string | CacheLifeConfig): void;
declare function unstable_cacheTag(...tags: string[]): void;
/**
 * Check if the current execution context is inside an unstable_cache() callback.
 * Used by headers(), cookies(), and connection() to throw errors when
 * dynamic request APIs are called inside a cache scope.
 */
declare function isInsideUnstableCacheScope(): boolean;
type UnstableCacheOptions = {
  revalidate?: number | false;
  tags?: string[];
};
/**
 * Wrap an async function with caching.
 *
 * Returns a new function that caches results. The cache key is derived
 * from keyParts + serialized arguments.
 */
declare function unstable_cache<T extends (...args: any[]) => Promise<any>>(fn: T, keyParts?: string[], options?: UnstableCacheOptions): T;
//#endregion
export { ActionRevalidationKind, CacheControlMetadata, CacheHandler, CacheHandlerContext, CacheHandlerValue, CacheLifeConfig, CacheState, CachedAppPageValue, CachedFetchValue, CachedImageValue, CachedPagesValue, CachedRedirectValue, CachedRouteValue, type ExecutionContextLike, IncrementalCacheValue, MemoryCacheHandler, NoOpCacheHandler, UnstableCacheRevalidationMode, _consumeRequestScopedCacheLife, _initRequestScopedCacheState, _peekRequestScopedCacheLife, _registerCacheContextAccessor, _runWithCacheState, _setRequestScopedCacheLife, cacheLife, cacheLifeProfiles, cacheTag, getAndClearActionRevalidationKind, getCacheHandler, getRequestExecutionContext, io, isInsideUnstableCacheScope, unstable_noStore as noStore, unstable_noStore, refresh, revalidatePath, revalidateTag, runWithExecutionContext, setCacheHandler, unstable_cache, unstable_cacheLife, unstable_cacheTag, unstable_io, updateTag };
//# sourceMappingURL=cache.d.ts.map