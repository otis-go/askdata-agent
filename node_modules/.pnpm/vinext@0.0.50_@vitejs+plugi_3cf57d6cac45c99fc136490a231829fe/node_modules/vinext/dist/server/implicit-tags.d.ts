//#region src/server/implicit-tags.d.ts
type AppCacheLeafKind = "page" | "route";
declare function buildPageCacheTags(pathname: string, extraTags: string[], routeSegments: string[], leafKind: AppCacheLeafKind): string[];
//#endregion
export { buildPageCacheTags };
//# sourceMappingURL=implicit-tags.d.ts.map