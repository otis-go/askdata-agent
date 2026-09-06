import { compareRoutes, decodeRouteSegment } from "./utils.js";
import { createValidFileMatcher, scanWithExtensions } from "./file-matcher.js";
import { patternToNextFormat, validateRoutePatterns } from "./route-validation.js";
import { createRouteTrieCache, matchRouteWithTrie } from "./route-matching.js";
import path from "node:path";
//#region src/routing/pages-router.ts
const routeCache = /* @__PURE__ */ new Map();
/**
* Invalidate cached routes for a given pages directory.
* Called by the file watcher when pages are added/removed.
*/
function invalidateRouteCache(pagesDir) {
	for (const key of routeCache.keys()) if (key.startsWith(`pages:${pagesDir}:`) || key.startsWith(`api:${pagesDir}:`)) routeCache.delete(key);
}
/**
* Scan the pages/ directory and return a list of routes.
* Results are cached — call invalidateRouteCache() when files change.
*
* Follows Next.js Pages Router conventions:
* - pages/index.tsx -> /
* - pages/about.tsx -> /about
* - pages/posts/[id].tsx -> /posts/:id
* - pages/[...slug].tsx -> /:slug+
* - Ignores _app.tsx, _document.tsx, _error.tsx, files starting with _
* - Ignores pages/api/ (handled separately later)
*/
async function pagesRouter(pagesDir, pageExtensions, matcher) {
	matcher ??= createValidFileMatcher(pageExtensions);
	const cacheKey = `pages:${pagesDir}:${JSON.stringify(matcher.extensions)}`;
	const cached = routeCache.get(cacheKey);
	if (cached) return cached.promise;
	const promise = scanPageRoutes(pagesDir, matcher);
	routeCache.set(cacheKey, {
		routes: [],
		promise
	});
	const routes = await promise;
	routeCache.set(cacheKey, {
		routes,
		promise
	});
	return routes;
}
async function scanPageRoutes(pagesDir, matcher) {
	const routes = [];
	for await (const file of scanWithExtensions("**/*", pagesDir, matcher.extensions, (name) => name === "api" || name.startsWith("_"))) {
		const route = fileToRoute(file, pagesDir, matcher);
		if (route) routes.push(route);
	}
	validateRoutePatterns(routes.map((route) => route.pattern));
	routes.sort(compareRoutes);
	return routes;
}
/**
* Convert a file path relative to pages/ into a Route.
*/
function fileToRoute(file, pagesDir, matcher) {
	const withoutExt = matcher.stripExtension(file);
	if (withoutExt === file) return null;
	const segments = withoutExt.split(path.sep);
	if (segments[segments.length - 1] === "index") segments.pop();
	const params = [];
	let isDynamic = false;
	const urlSegments = [];
	for (let i = 0; i < segments.length; i++) {
		const segment = segments[i];
		const catchAllMatch = segment.match(/^\[\.\.\.([^\]]+)\]$/);
		if (catchAllMatch) {
			if (i !== segments.length - 1) return null;
			if (catchAllMatch[1].endsWith("+") || catchAllMatch[1].endsWith("*")) return null;
			isDynamic = true;
			params.push(catchAllMatch[1]);
			urlSegments.push(`:${catchAllMatch[1]}+`);
			continue;
		}
		const optionalCatchAllMatch = segment.match(/^\[\[\.\.\.([^\]]+)\]\]$/);
		if (optionalCatchAllMatch) {
			if (i !== segments.length - 1) return null;
			if (optionalCatchAllMatch[1].endsWith("+") || optionalCatchAllMatch[1].endsWith("*")) return null;
			isDynamic = true;
			params.push(optionalCatchAllMatch[1]);
			urlSegments.push(`:${optionalCatchAllMatch[1]}*`);
			continue;
		}
		const dynamicMatch = segment.match(/^\[([^\]]+)\]$/);
		if (dynamicMatch) {
			if (dynamicMatch[1].endsWith("+") || dynamicMatch[1].endsWith("*")) return null;
			isDynamic = true;
			params.push(dynamicMatch[1]);
			urlSegments.push(`:${dynamicMatch[1]}`);
			continue;
		}
		urlSegments.push(decodeRouteSegment(segment));
	}
	const pattern = "/" + urlSegments.join("/");
	return {
		pattern: pattern === "/" ? "/" : pattern,
		patternParts: urlSegments.filter(Boolean),
		filePath: path.join(pagesDir, file),
		isDynamic,
		params
	};
}
const trieCache = createRouteTrieCache();
/**
* Match a URL path against a route pattern.
* Returns the matched params or null if no match.
*/
function matchRoute(url, routes) {
	return matchRouteWithTrie(url, routes, trieCache);
}
/**
* Scan the pages/api/ directory and return API routes.
* Results are cached — call invalidateRouteCache() when files change.
*
* Follows Next.js conventions:
* - pages/api/hello.ts -> /api/hello
* - pages/api/users/[id].ts -> /api/users/:id
*/
async function apiRouter(pagesDir, pageExtensions, matcher) {
	matcher ??= createValidFileMatcher(pageExtensions);
	const cacheKey = `api:${pagesDir}:${JSON.stringify(matcher.extensions)}`;
	const cached = routeCache.get(cacheKey);
	if (cached) return cached.promise;
	const promise = scanApiRoutes(pagesDir, matcher);
	routeCache.set(cacheKey, {
		routes: [],
		promise
	});
	const routes = await promise;
	routeCache.set(cacheKey, {
		routes,
		promise
	});
	return routes;
}
async function scanApiRoutes(pagesDir, matcher) {
	const apiDir = path.join(pagesDir, "api");
	let files;
	try {
		files = [];
		for await (const file of scanWithExtensions("**/*", apiDir, matcher.extensions, (name) => name.startsWith("_"))) files.push(file);
	} catch {
		files = [];
	}
	const routes = [];
	for (const file of files) {
		const route = fileToRoute(path.join("api", file), pagesDir, matcher);
		if (route) routes.push(route);
	}
	validateRoutePatterns(routes.map((route) => route.pattern));
	routes.sort(compareRoutes);
	return routes;
}
//#endregion
export { apiRouter, invalidateRouteCache, matchRoute, pagesRouter, patternToNextFormat };

//# sourceMappingURL=pages-router.js.map