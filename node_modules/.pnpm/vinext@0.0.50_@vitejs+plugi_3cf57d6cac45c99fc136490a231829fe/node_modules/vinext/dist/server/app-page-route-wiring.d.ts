import { AppRouteSemanticIds } from "../routing/app-route-graph.js";
import { AppElements } from "./app-elements-wire.js";
import { AppPageParams } from "./app-page-boundary.js";
import { AppRscRenderMode } from "./app-rsc-render-mode.js";
import { Metadata, Viewport } from "../shims/metadata.js";
import { resolveAppPageChildSegments } from "./app-page-segment-state.js";
import { ComponentType, ReactNode } from "react";

//#region src/server/app-page-route-wiring.d.ts
type AppPageComponentProps = {
  children?: ReactNode;
  error?: unknown;
  params?: unknown;
  reset?: () => void;
} & Record<string, unknown>;
type AppPageComponent = ComponentType<AppPageComponentProps>;
type AppPageErrorComponent = ComponentType<{
  error: unknown;
  reset: () => void;
}>;
type AppPageModule = Record<string, unknown> & {
  default?: AppPageComponent | null | undefined;
};
type AppPageErrorModule = Record<string, unknown> & {
  default?: AppPageErrorComponent | null | undefined;
};
type AppPageRouteWiringSlot<TModule extends AppPageModule = AppPageModule, TErrorModule extends AppPageErrorModule = AppPageErrorModule> = {
  /** Graph-owned semantic slot identity. */id?: string | null; /** Slot prop name passed to the owning layout (e.g. "modal" from @modal). */
  name: string;
  default?: TModule | null;
  error?: TErrorModule | null;
  layout?: TModule | null;
  layoutIndex: number;
  loading?: TModule | null;
  page?: TModule | null;
  routeSegments?: readonly string[] | null;
  /**
   * Full URL pattern parts for the slot's mirrored sub-page. Set when the
   * slot's params may differ from the route's (e.g. inherited slot whose
   * dynamic markers have different names than the route's). The runtime
   * matches the request URL against these parts to extract slot params.
   */
  slotPatternParts?: readonly string[] | null; /** Param names captured by `slotPatternParts`, in order. */
  slotParamNames?: readonly string[] | null;
};
type AppPageRouteWiringRoute<TModule extends AppPageModule = AppPageModule, TErrorModule extends AppPageErrorModule = AppPageErrorModule> = {
  ids?: AppRouteSemanticIds | null;
  error?: TErrorModule | null;
  errorPaths?: readonly TErrorModule[] | null;
  errors?: readonly (TErrorModule | null | undefined)[] | null;
  errorTreePositions?: readonly number[] | null;
  layoutTreePositions?: readonly number[] | null;
  layouts: readonly (TModule | null | undefined)[];
  loading?: TModule | null;
  notFound?: TModule | null;
  notFounds?: readonly (TModule | null | undefined)[] | null;
  forbidden?: TModule | null;
  forbiddens?: readonly (TModule | null | undefined)[] | null;
  unauthorized?: TModule | null;
  unauthorizeds?: readonly (TModule | null | undefined)[] | null;
  routeSegments?: readonly string[];
  /**
   * Keyed by stable slot id (name + owner path), not necessarily the slot prop name.
   */
  slots?: Readonly<Record<string, AppPageRouteWiringSlot<TModule, TErrorModule>>> | null;
  templateTreePositions?: readonly number[] | null;
  templates?: readonly (TModule | null | undefined)[] | null;
};
type AppPageSlotOverride<TModule extends AppPageModule = AppPageModule> = {
  layoutModules?: readonly (TModule | null | undefined)[] | null;
  /**
   * The page module to render for this slot. Optional — when omitted, the
   * slot's existing `page` is used (e.g. when the override only changes the
   * slot's `params` for an inherited mirror with distinct param names).
   */
  pageModule?: TModule | null;
  params?: AppPageParams;
  props?: Readonly<Record<string, unknown>>;
};
type AppPageLayoutEntry<TModule extends AppPageModule = AppPageModule, TErrorModule extends AppPageErrorModule = AppPageErrorModule> = {
  errorModule?: TErrorModule | null | undefined;
  forbiddenModule?: TModule | null | undefined;
  id: string;
  layoutModule?: TModule | null | undefined;
  notFoundModule?: TModule | null | undefined;
  unauthorizedModule?: TModule | null | undefined;
  treePath: string;
  treePosition: number;
};
type BuildAppPageRouteElementOptions<TModule extends AppPageModule = AppPageModule, TErrorModule extends AppPageErrorModule = AppPageErrorModule> = {
  element: ReactNode;
  globalErrorModule?: TErrorModule | null;
  makeThenableParams: (params: AppPageParams) => unknown;
  matchedParams: AppPageParams;
  resolvedMetadata: Metadata | null;
  resolvedViewport: Viewport;
  rootForbiddenModule?: TModule | null;
  rootNotFoundModule?: TModule | null;
  rootUnauthorizedModule?: TModule | null;
  route: AppPageRouteWiringRoute<TModule, TErrorModule>;
  slotOverrides?: Readonly<Record<string, AppPageSlotOverride<TModule>>> | null;
};
type BuildAppPageElementsOptions<TModule extends AppPageModule = AppPageModule, TErrorModule extends AppPageErrorModule = AppPageErrorModule> = BuildAppPageRouteElementOptions<TModule, TErrorModule> & {
  interceptionContext?: string | null;
  isRscRequest?: boolean;
  mountedSlotIds?: ReadonlySet<string> | null;
  renderMode?: AppRscRenderMode;
  routePath: string;
};
declare function createAppPageTreePath(routeSegments: readonly string[] | null | undefined, treePosition: number): string;
declare function createAppPageLayoutEntries<TModule extends AppPageModule, TErrorModule extends AppPageErrorModule>(route: Pick<AppPageRouteWiringRoute<TModule, TErrorModule>, "errors" | "errorTreePositions" | "layoutTreePositions" | "layouts" | "notFounds" | "routeSegments"> & {
  forbiddens?: readonly (TModule | null | undefined)[] | null;
  unauthorizeds?: readonly (TModule | null | undefined)[] | null;
}): AppPageLayoutEntry<TModule, TErrorModule>[];
declare function buildAppPageElements<TModule extends AppPageModule, TErrorModule extends AppPageErrorModule>(options: BuildAppPageElementsOptions<TModule, TErrorModule>): AppElements;
//#endregion
export { AppPageErrorModule, AppPageModule, AppPageRouteWiringRoute, AppPageSlotOverride, buildAppPageElements, createAppPageLayoutEntries, createAppPageTreePath, resolveAppPageChildSegments };
//# sourceMappingURL=app-page-route-wiring.d.ts.map