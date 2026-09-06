import { AppPageParams } from "./app-page-boundary.js";

//#region src/server/app-page-segment-state.d.ts
declare function resolveAppPageChildSegments(routeSegments: readonly string[], treePosition: number, params: AppPageParams): string[];
declare function resolveAppPageSegmentStateKey(routeSegments: readonly string[], treePosition: number, params: AppPageParams): string;
declare function resolveAppPageRouteStateKey(routeSegments: readonly string[], params: AppPageParams): string;
declare function resolveAppPageLeafSegmentStateKey(routeSegments: readonly string[], params: AppPageParams): string;
//#endregion
export { resolveAppPageChildSegments, resolveAppPageLeafSegmentStateKey, resolveAppPageRouteStateKey, resolveAppPageSegmentStateKey };
//# sourceMappingURL=app-page-segment-state.d.ts.map