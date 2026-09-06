import { FetchCacheMode } from "../shims/fetch-cache.js";

//#region src/server/app-segment-config.d.ts
type AppRouteSegmentDynamic = "auto" | "error" | "force-dynamic" | "force-static";
type AppRouteSegmentConfigModule = {
  dynamic?: unknown;
  dynamicParams?: unknown;
  fetchCache?: unknown;
  revalidate?: unknown;
};
type EffectiveAppPageSegmentConfig = {
  dynamicConfig?: AppRouteSegmentDynamic;
  dynamicParamsConfig?: boolean;
  fetchCache?: FetchCacheMode;
  revalidateSeconds: number | null;
};
type ResolveAppPageSegmentConfigOptions = {
  layouts?: readonly (AppRouteSegmentConfigModule | null | undefined)[];
  page?: AppRouteSegmentConfigModule | null;
};
/**
 * Resolve the route segment config that applies to an App page route.
 *
 * Next.js collects config from every segment in the loader tree and reduces it
 * into the effective route config. The generated vinext entry already knows
 * the concrete layout/page modules for a route, so it should only describe
 * those modules and delegate the behavior to this helper.
 */
declare function resolveAppPageSegmentConfig(options: ResolveAppPageSegmentConfigOptions): EffectiveAppPageSegmentConfig;
declare function resolveAppPageFetchCacheMode(options: ResolveAppPageSegmentConfigOptions): FetchCacheMode | null;
//#endregion
export { resolveAppPageFetchCacheMode, resolveAppPageSegmentConfig };
//# sourceMappingURL=app-segment-config.d.ts.map