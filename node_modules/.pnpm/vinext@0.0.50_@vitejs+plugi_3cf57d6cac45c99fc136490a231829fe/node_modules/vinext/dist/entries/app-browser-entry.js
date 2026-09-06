import { resolveRuntimeEntryModule } from "./runtime-entry-module.js";
//#region src/entries/app-browser-entry.ts
/**
* Generate the virtual browser entry module.
*
* This runs in the client (browser). It hydrates the page from the
* embedded RSC payload and handles client-side navigation by re-fetching
* RSC streams.
*/
function generateBrowserEntry(routes = []) {
	const entryPath = resolveRuntimeEntryModule("app-browser-entry");
	const prefetchRoutes = routes.filter((route) => isLinkPrefetchRoute(route)).map((route) => ({
		patternParts: [...route.patternParts],
		isDynamic: route.isDynamic
	}));
	return `window.__VINEXT_LINK_PREFETCH_ROUTES__ = ${JSON.stringify(prefetchRoutes)};
import ${JSON.stringify(entryPath)};`;
}
function isLinkPrefetchRoute(route) {
	if (route.pagePath !== null) return true;
	return route.routePath === null && route.layouts.length > 0;
}
//#endregion
export { generateBrowserEntry };

//# sourceMappingURL=app-browser-entry.js.map