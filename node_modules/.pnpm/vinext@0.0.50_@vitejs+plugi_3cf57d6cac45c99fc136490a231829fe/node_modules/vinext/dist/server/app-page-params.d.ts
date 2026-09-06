import { AppPageParams } from "./app-page-boundary.js";

//#region src/server/app-page-params.d.ts
declare function getAppPageSegmentParamName(segment: string): string | null;
declare function resolveAppPageSegmentParams(routeSegments: readonly string[] | null | undefined, treePosition: number, matchedParams: AppPageParams): AppPageParams;
//#endregion
export { getAppPageSegmentParamName, resolveAppPageSegmentParams };
//# sourceMappingURL=app-page-params.d.ts.map