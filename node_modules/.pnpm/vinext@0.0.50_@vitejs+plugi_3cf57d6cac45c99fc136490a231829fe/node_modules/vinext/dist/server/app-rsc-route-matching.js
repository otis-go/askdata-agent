import { normalizePathnameForRouteMatch } from "../routing/utils.js";
import { buildRouteTrie, trieMatch } from "../routing/route-trie.js";
import { matchRoutePattern } from "../routing/route-pattern.js";
//#region src/server/app-rsc-route-matching.ts
function createRouteParams() {
	return Object.create(null);
}
function appRscPathnameParts(pathname) {
	const pathOnly = pathname.split("?")[0];
	return normalizePathnameForRouteMatch(pathOnly === "/" ? "/" : pathOnly.replace(/\/$/, "")).split("/").filter(Boolean);
}
function createAppRscRouteMatcher(routes) {
	const routeTrie = buildRouteTrie(routes);
	const interceptLookup = createInterceptLookup(routes);
	return {
		matchRoute(url) {
			return trieMatch(routeTrie, appRscPathnameParts(url));
		},
		findIntercept(pathname, sourcePathname = null) {
			const urlParts = appRscPathnameParts(pathname);
			for (const entry of interceptLookup) {
				const params = matchAppRscRoutePattern(urlParts, entry.targetPatternParts);
				if (params !== null) {
					let sourceParams = createRouteParams();
					if (sourcePathname !== null) {
						const sourceRoute = routes[entry.sourceRouteIndex];
						const sourceParts = appRscPathnameParts(sourcePathname);
						const matchedSourceParams = sourceRoute ? matchAppRscRoutePattern(sourceParts, sourceRoute.patternParts) : null;
						if (matchedSourceParams !== null) sourceParams = matchedSourceParams;
					}
					return {
						...entry,
						matchedParams: mergeMatchedParams(sourceParams, params)
					};
				}
			}
			return null;
		}
	};
}
function createInterceptLookup(routes) {
	const interceptLookup = [];
	for (let routeIndex = 0; routeIndex < routes.length; routeIndex++) {
		const route = routes[routeIndex];
		if (!route.slots) continue;
		for (const [slotKey, slotModule] of Object.entries(route.slots)) {
			if (!slotModule.intercepts) continue;
			for (const intercept of slotModule.intercepts) interceptLookup.push({
				sourceRouteIndex: routeIndex,
				slotKey,
				targetPattern: intercept.targetPattern,
				targetPatternParts: intercept.targetPattern.split("/").filter(Boolean),
				interceptLayouts: intercept.interceptLayouts,
				page: intercept.page,
				params: intercept.params
			});
		}
	}
	return interceptLookup;
}
function matchAppRscRoutePattern(urlParts, patternParts) {
	return matchRoutePattern(urlParts, patternParts);
}
function mergeMatchedParams(sourceParams, targetParams) {
	return Object.assign(createRouteParams(), sourceParams, targetParams);
}
//#endregion
export { createAppRscRouteMatcher, matchAppRscRoutePattern };

//# sourceMappingURL=app-rsc-route-matching.js.map