import { MetadataFileRoute } from "./metadata-routes.js";
import { AppPageParams } from "./app-page-boundary.js";
import { Metadata, Viewport } from "../shims/metadata.js";

//#region src/server/app-page-head.d.ts
type AppPageSearchParams = Record<string, string | string[]>;
type AppPageHeadModule = Record<string, unknown>;
type AppPageHeadParallelRoute<TModule extends AppPageHeadModule = AppPageHeadModule> = {
  layoutModule?: TModule | null;
  layoutModules?: readonly (TModule | null | undefined)[] | null;
  pageModule?: TModule | null;
  params?: AppPageParams | null;
  routeSegments?: readonly string[] | null;
};
type AppPageHeadSlot<TModule extends AppPageHeadModule = AppPageHeadModule> = {
  layout?: TModule | null;
  page?: TModule | null;
};
type ResolveActiveParallelRouteHeadInputsOptions<TModule extends AppPageHeadModule = AppPageHeadModule> = {
  interceptLayouts?: readonly (TModule | null | undefined)[] | null;
  interceptPage?: TModule | null;
  interceptParams?: AppPageParams | null;
  interceptSlotKey?: string | null;
  params: AppPageParams;
  routeSegments: readonly string[];
  slots?: Record<string, AppPageHeadSlot<TModule>> | null;
};
type ResolveAppPageHeadOptions<TModule extends AppPageHeadModule = AppPageHeadModule> = {
  fallbackOnFileMetadataError?: boolean;
  layoutModules: readonly (TModule | null | undefined)[];
  layoutTreePositions?: readonly number[] | null;
  metadataRoutes: readonly MetadataFileRoute[];
  pageModule?: TModule | null;
  parallelRoutes?: readonly AppPageHeadParallelRoute<TModule>[] | null;
  params: AppPageParams;
  routePath: string;
  routeSegments?: readonly string[] | null;
  searchParams?: URLSearchParams | null;
};
type ResolveAppPageHeadResult = {
  hasSearchParams: boolean;
  metadata: Metadata | null;
  pageSearchParams: AppPageSearchParams;
  viewport: Viewport;
};
type AppPageSearchParamsCollection = {
  hasSearchParams: boolean;
  pageSearchParams: AppPageSearchParams;
};
declare function resolveActiveParallelRouteHeadInputs<TModule extends AppPageHeadModule>(options: ResolveActiveParallelRouteHeadInputsOptions<TModule>): AppPageHeadParallelRoute<TModule>[];
declare function collectAppPageSearchParams(searchParams: URLSearchParams | null | undefined): AppPageSearchParamsCollection;
declare function resolveAppPageHead<TModule extends AppPageHeadModule>(options: ResolveAppPageHeadOptions<TModule>): Promise<ResolveAppPageHeadResult>;
//#endregion
export { collectAppPageSearchParams, resolveActiveParallelRouteHeadInputs, resolveAppPageHead };
//# sourceMappingURL=app-page-head.d.ts.map