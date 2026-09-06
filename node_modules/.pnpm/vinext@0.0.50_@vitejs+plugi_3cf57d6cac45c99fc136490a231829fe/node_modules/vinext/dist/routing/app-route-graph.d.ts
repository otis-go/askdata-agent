import { ValidFileMatcher } from "./file-matcher.js";

//#region src/routing/app-route-graph.d.ts
type InterceptingRoute = {
  /** The interception convention: "." | ".." | "../.." | "..." */convention: string; /** The URL pattern this intercepts (e.g. "/photos/:id") */
  targetPattern: string; /** Absolute path to the intercepting page component */
  pagePath: string; /** Absolute layout paths inside the intercepting route tree, outermost to innermost */
  layoutPaths: string[]; /** Parameter names for dynamic segments */
  params: string[];
};
type ParallelSlot = {
  /** Graph-owned semantic slot identity. Required on AppRouteGraphParallelSlot. */id?: string; /** Stable slot identity (name + owning directory), used for route serialization keys. */
  key: string; /** Slot name (e.g. "team" from @team) */
  name: string; /** Absolute path to the @slot directory that owns this slot. Internal routing metadata. */
  ownerDir: string; /** Stable tree path for the directory whose layout owns this slot. */
  ownerTreePath: string; /** Whether the slot owner directory declares its own page component. */
  hasPage: boolean; /** Absolute path to the slot's page component */
  pagePath: string | null; /** Absolute path to the slot's default.tsx fallback */
  defaultPath: string | null; /** Absolute path to the slot's layout component (wraps slot content) */
  layoutPath: string | null; /** Absolute path to the slot's loading component */
  loadingPath: string | null; /** Absolute path to the slot's error component */
  errorPath: string | null; /** Intercepting routes within this slot */
  interceptingRoutes: InterceptingRoute[];
  /**
   * The layout index (0-based, in route.layouts[]) that this slot belongs to.
   * Slots are passed as props to the layout at their directory level, not
   * necessarily the innermost layout. -1 means "innermost" (legacy default).
   */
  layoutIndex: number;
  /**
   * Filesystem segments from the slot's root directory to its active page.
   * Used at render time to compute segments for useSelectedLayoutSegment(slotName).
   * For a page at the slot root (@team/page.tsx), this is [].
   * For a sub-page (@team/members/page.tsx), this is ["members"].
   * null when the slot has no active page (showing default.tsx fallback).
   */
  routeSegments: string[] | null;
  /**
   * Full URL pattern parts for the slot's active page (owner prefix +
   * slot-relative pattern). Set when an inherited slot mirrors a sub-page
   * whose param names may differ from the route's. The runtime matches the
   * request URL against these parts to extract slot-specific params.
   */
  slotPatternParts?: string[];
  /**
   * Param names captured by `slotPatternParts`, in order of appearance.
   * Used at runtime to decide whether to extract slot-specific params or
   * reuse the route's matched params.
   */
  slotParamNames?: string[];
};
type AppRoute = {
  /** Graph-owned semantic identities. Required on AppRouteGraphRoute. */ids?: AppRouteSemanticIds; /** URL pattern, e.g. "/" or "/about" or "/blog/:slug" */
  pattern: string; /** Absolute file path to the page component */
  pagePath: string | null; /** Absolute file path to the route handler (route.ts) */
  routePath: string | null; /** Ordered list of layout files from root to leaf */
  layouts: string[]; /** Ordered list of all discovered template files from root to leaf (not necessarily aligned 1:1 with layouts) */
  templates: string[]; /** Parallel route slots (from @slot directories at the route's directory level) */
  parallelSlots: ParallelSlot[]; /** Loading component path */
  loadingPath: string | null; /** Error component path (leaf directory only) */
  errorPath: string | null;
  /**
   * Per-layout error boundary paths, aligned with the layouts array.
   * Each entry is the error.tsx at the same directory level as the
   * corresponding layout (or null if that level has no error.tsx).
   */
  layoutErrorPaths: (string | null)[]; /** Per-segment error boundary paths, aligned with errorTreePositions. */
  errorPaths?: string[]; /** Tree position (directory depth from app/ root) for each error boundary. */
  errorTreePositions?: number[]; /** Not-found component path (nearest, walking up from page dir) */
  notFoundPath: string | null;
  /**
   * Not-found component paths per layout level (aligned with layouts array).
   * Each entry is the not-found.tsx at that layout's directory, or null.
   * Used to create per-layout NotFoundBoundary so that notFound() thrown from
   * a layout is caught by the parent layout's boundary (matching Next.js behavior).
   */
  notFoundPaths: (string | null)[];
  /**
   * Forbidden component paths per layout level (aligned with layouts array).
   * Each entry is the forbidden.tsx at that layout's directory, or null.
   * Used to create per-layout ForbiddenBoundary.
   */
  forbiddenPaths: (string | null)[]; /** Forbidden component path (403) at the route's directory level */
  forbiddenPath: string | null; /** Unauthorized component path (401) at the route's directory level */
  unauthorizedPath: string | null; /** Unauthorized component paths per layout level (aligned with layouts array). */
  unauthorizedPaths: (string | null)[];
  /**
   * Filesystem segments from app/ root to the route's directory.
   * Includes route groups and dynamic segments (as template strings like "[id]").
   * Used at render time to compute the child segments for useSelectedLayoutSegments().
   */
  routeSegments: string[]; /** Tree position (directory depth from app/ root) for each template. */
  templateTreePositions?: number[];
  /**
   * Tree position (directory depth from app/ root) for each layout.
   * Used to slice routeSegments and determine which segments are below each layout.
   * For example, root layout = 0, a layout at app/blog/ = 1, app/blog/(group)/ = 2.
   * Unlike the old layoutSegmentDepths, this counts ALL directory levels including
   * route groups and parallel slots.
   */
  layoutTreePositions: number[]; /** Whether this is a dynamic route */
  isDynamic: boolean; /** Parameter names for dynamic segments */
  params: string[]; /** Dynamic parameter names captured by the route's root layout. */
  rootParamNames?: string[]; /** Pre-split pattern segments (computed once at scan time, reused per request) */
  patternParts: string[];
};
type AppRouteSemanticIds = {
  route: string;
  page: string | null;
  routeHandler: string | null;
  rootBoundary: RootBoundaryId | null;
  layouts: readonly string[];
  templates: readonly string[];
  /**
   * Bridge map for the current route metadata shape: keyed by `slot.key`
   * (`name@relative/path` infrastructure id), value is the graph-owned semantic slot id.
   */
  slots: Readonly<Record<string, string>>;
};
type AppRouteGraphParallelSlot = ParallelSlot & {
  id: string;
};
type AppRouteGraphRoute = Omit<AppRoute, "ids" | "parallelSlots" | "rootParamNames"> & {
  ids: AppRouteSemanticIds;
  parallelSlots: AppRouteGraphParallelSlot[];
  rootParamNames: string[];
};
type Flavor<T, Brand extends string> = T & {
  readonly __flavor?: Brand;
};
type GraphVersion = Flavor<string, "GraphVersion">;
type RootBoundaryId = Flavor<string, "RootBoundaryId">;
type RouteManifestRoute = {
  id: string;
  pattern: string;
  patternParts: readonly string[];
  isDynamic: boolean;
  paramNames: readonly string[];
  rootParamNames: readonly string[];
  rootBoundaryId: RootBoundaryId | null;
  pageId: string | null;
  routeHandlerId: string | null;
  layoutIds: readonly string[];
  templateIds: readonly string[];
  slotIds: readonly string[];
};
type RouteManifestPage = {
  id: string;
  routeId: string;
  pattern: string;
};
type RouteManifestRouteHandler = {
  id: string;
  routeId: string;
  pattern: string;
};
type RouteManifestLayout = {
  id: string;
  treePath: string;
  rootBoundaryId: RootBoundaryId | null;
};
type RouteManifestTemplate = {
  id: string;
  treePath: string;
  rootBoundaryId: RootBoundaryId | null;
  ownerLayoutId: string | null;
  reset: {
    kind: "remountSubtree";
    treePath: string;
  };
};
type RouteManifestSlot = {
  id: string;
  key: string;
  name: string;
  ownerTreePath: string;
  ownerLayoutId: string | null;
  rootBoundaryId: RootBoundaryId | null;
  defaultId: string | null;
  hasDefault: boolean;
  hasPage: boolean;
};
type RouteManifestDefault = {
  id: string;
  slotId: string;
  ownerTreePath: string;
  ownerLayoutId: string | null;
  rootBoundaryId: RootBoundaryId | null;
};
type RouteManifestSlotBindingState = "active" | "default" | "unmatched";
type RouteManifestSlotBinding = {
  id: string;
  routeId: string;
  slotId: string;
  ownerLayoutId: string | null;
  state: RouteManifestSlotBindingState;
  defaultId: string | null;
  routeSegments: readonly string[] | null;
  slotPatternParts?: readonly string[];
  slotParamNames?: readonly string[];
};
type RouteManifestBoundaryOutcome = "error" | "forbidden" | "notFound" | "unauthorized";
type RouteManifestBoundary = {
  id: string;
  outcome: RouteManifestBoundaryOutcome;
  treePath: string;
  ownerLayoutId: string | null;
  rootBoundaryId: RootBoundaryId | null;
};
type RouteManifestRootBoundary = {
  id: RootBoundaryId;
  layoutId: string;
  treePath: string;
};
type StaticSegmentGraph = {
  routes: ReadonlyMap<string, RouteManifestRoute>;
  pages: ReadonlyMap<string, RouteManifestPage>;
  routeHandlers: ReadonlyMap<string, RouteManifestRouteHandler>;
  layouts: ReadonlyMap<string, RouteManifestLayout>;
  templates: ReadonlyMap<string, RouteManifestTemplate>;
  slots: ReadonlyMap<string, RouteManifestSlot>;
  defaults: ReadonlyMap<string, RouteManifestDefault>;
  slotBindings: ReadonlyMap<string, RouteManifestSlotBinding>;
  boundaries: ReadonlyMap<string, RouteManifestBoundary>;
  rootBoundaries: ReadonlyMap<RootBoundaryId, RouteManifestRootBoundary>;
};
type RouteManifest = {
  graphVersion: GraphVersion;
  segmentGraph: StaticSegmentGraph;
};
declare function buildAppRouteGraph(appDir: string, matcher: ValidFileMatcher): Promise<{
  routes: AppRouteGraphRoute[];
  routeManifest: RouteManifest;
}>;
declare function computeRootParamNames(routeSegments: readonly string[], layoutTreePositions: readonly number[]): string[];
//#endregion
export { AppRoute, AppRouteGraphParallelSlot, AppRouteGraphRoute, AppRouteSemanticIds, GraphVersion, InterceptingRoute, ParallelSlot, RootBoundaryId, RouteManifest, RouteManifestBoundary, RouteManifestBoundaryOutcome, RouteManifestDefault, RouteManifestLayout, RouteManifestPage, RouteManifestRootBoundary, RouteManifestRoute, RouteManifestRouteHandler, RouteManifestSlot, RouteManifestSlotBinding, RouteManifestSlotBindingState, RouteManifestTemplate, StaticSegmentGraph, buildAppRouteGraph, computeRootParamNames };
//# sourceMappingURL=app-route-graph.d.ts.map