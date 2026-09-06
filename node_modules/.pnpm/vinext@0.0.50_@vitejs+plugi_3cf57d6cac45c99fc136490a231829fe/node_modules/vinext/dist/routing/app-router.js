import { createValidFileMatcher } from "./file-matcher.js";
import { createRouteTrieCache, matchRouteWithTrie } from "./route-matching.js";
import { buildAppRouteGraph, computeRootParamNames } from "./app-route-graph.js";
//#region src/routing/app-router.ts
/**
* App Router file-system routing.
*
* Scans the app/ directory following Next.js App Router conventions:
* - app/page.tsx -> /
* - app/about/page.tsx -> /about
* - app/blog/[slug]/page.tsx -> /blog/:slug
* - app/[...catchAll]/page.tsx -> /:catchAll+
* - app/route.ts -> / (API route)
* - app/(group)/page.tsx -> / (route groups are transparent)
* - Layouts: app/layout.tsx wraps all children
* - Loading: app/loading.tsx -> Suspense fallback
* - Error: app/error.tsx -> ErrorBoundary
* - Not Found: app/not-found.tsx
*/
let cachedGraph = null;
let cachedAppDir = null;
let cachedPageExtensionsKey = null;
function invalidateAppRouteCache() {
	cachedGraph = null;
	cachedAppDir = null;
	cachedPageExtensionsKey = null;
}
/**
* Scan the app/ directory and return the route graph.
* TODO(#726): Layer 4 should consume this read model directly once the
* navigation planner owns route graph facts.
*
* @internal
*/
async function appRouteGraph(appDir, pageExtensions, matcher) {
	matcher ??= createValidFileMatcher(pageExtensions);
	const pageExtensionsKey = JSON.stringify(matcher.extensions);
	if (cachedGraph && cachedAppDir === appDir && cachedPageExtensionsKey === pageExtensionsKey) return cachedGraph;
	const graph = await buildAppRouteGraph(appDir, matcher);
	cachedGraph = graph;
	cachedAppDir = appDir;
	cachedPageExtensionsKey = pageExtensionsKey;
	return graph;
}
/**
* Scan the app/ directory and return a list of routes.
*/
async function appRouter(appDir, pageExtensions, matcher) {
	return (await appRouteGraph(appDir, pageExtensions, matcher)).routes;
}
const appTrieCache = createRouteTrieCache();
/**
* Match a URL against App Router routes.
*/
function matchAppRoute(url, routes) {
	return matchRouteWithTrie(url, routes, appTrieCache);
}
//#endregion
export { appRouteGraph, appRouter, computeRootParamNames, invalidateAppRouteCache, matchAppRoute };

//# sourceMappingURL=app-router.js.map