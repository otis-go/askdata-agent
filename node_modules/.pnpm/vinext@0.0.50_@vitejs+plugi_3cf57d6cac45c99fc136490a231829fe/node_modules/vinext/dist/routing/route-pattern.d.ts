//#region src/routing/route-pattern.d.ts
type RoutePatternParams = Record<string, string | string[]>;
declare function routePatternParts(pathname: string): string[];
declare function routePattern(pathname: string): string;
declare function fillRoutePatternSegments(pathname: string, params: RoutePatternParams): string | null;
declare function matchRoutePattern(urlParts: readonly string[], patternParts: readonly string[]): RoutePatternParams | null;
//#endregion
export { RoutePatternParams, fillRoutePatternSegments, matchRoutePattern, routePattern, routePatternParts };
//# sourceMappingURL=route-pattern.d.ts.map