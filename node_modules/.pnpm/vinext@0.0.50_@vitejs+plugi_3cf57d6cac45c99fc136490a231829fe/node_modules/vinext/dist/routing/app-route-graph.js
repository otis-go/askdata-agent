import { compareRoutes, decodeRouteSegment } from "./utils.js";
import { scanWithExtensions } from "./file-matcher.js";
import { validateRoutePatterns } from "./route-validation.js";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
//#region src/routing/app-route-graph.ts
/**
* App Router route graph construction.
*
* Scans app/ directories and materializes route metadata before the request-time
* matcher consumes it. Keep request matching and cache ownership in app-router.ts.
*/
function createAppRouteGraphRouteId(pattern) {
	return `route:${pattern}`;
}
function createAppRouteGraphPageId(pattern) {
	return `page:${pattern}`;
}
function createAppRouteGraphRouteHandlerId(pattern) {
	return `route-handler:${pattern}`;
}
function createAppRouteGraphLayoutId(treePath) {
	return `layout:${treePath}`;
}
function createAppRouteGraphTemplateId(treePath) {
	return `template:${treePath}`;
}
function createAppRouteGraphSlotId(slotName, ownerTreePath) {
	return `slot:${slotName}:${ownerTreePath}`;
}
function createAppRouteGraphDefaultId(slotId) {
	return `default:${slotId}`;
}
function createAppRouteGraphRootBoundaryId(treePath) {
	return `root-boundary:${treePath}`;
}
function compareStableStrings(left, right) {
	if (left < right) return -1;
	if (left > right) return 1;
	return 0;
}
function sortedMapValues(map) {
	return Array.from(map.entries()).sort(([left], [right]) => compareStableStrings(left, right)).map(([, value]) => value);
}
function createRouteManifest(routes) {
	const segmentGraph = createStaticSegmentGraph(routes);
	return {
		graphVersion: createRouteManifestGraphVersion(segmentGraph),
		segmentGraph
	};
}
function createStaticSegmentGraph(routes) {
	const routeEntries = /* @__PURE__ */ new Map();
	const pages = /* @__PURE__ */ new Map();
	const routeHandlers = /* @__PURE__ */ new Map();
	const layouts = /* @__PURE__ */ new Map();
	const templates = /* @__PURE__ */ new Map();
	const slots = /* @__PURE__ */ new Map();
	const defaults = /* @__PURE__ */ new Map();
	const slotBindings = /* @__PURE__ */ new Map();
	const boundaries = /* @__PURE__ */ new Map();
	const rootBoundaries = /* @__PURE__ */ new Map();
	for (const route of routes) {
		routeEntries.set(route.ids.route, {
			id: route.ids.route,
			pattern: route.pattern,
			patternParts: [...route.patternParts],
			isDynamic: route.isDynamic,
			paramNames: [...route.params],
			rootParamNames: [...route.rootParamNames],
			rootBoundaryId: route.ids.rootBoundary,
			pageId: route.ids.page,
			routeHandlerId: route.ids.routeHandler,
			layoutIds: [...route.ids.layouts],
			templateIds: [...route.ids.templates],
			slotIds: route.parallelSlots.map((slot) => slot.id).sort(compareStableStrings)
		});
		if (route.ids.page) pages.set(route.ids.page, {
			id: route.ids.page,
			routeId: route.ids.route,
			pattern: route.pattern
		});
		if (route.ids.routeHandler) routeHandlers.set(route.ids.routeHandler, {
			id: route.ids.routeHandler,
			routeId: route.ids.route,
			pattern: route.pattern
		});
		for (const [index, layoutId] of route.ids.layouts.entries()) {
			const treePosition = route.layoutTreePositions[index];
			assertRouteManifestTreePosition("layout", route, layoutId, treePosition);
			const treePath = createAppRouteGraphTreePath(route.routeSegments, treePosition);
			const existingLayout = layouts.get(layoutId);
			if (existingLayout) assertRouteManifestRootBoundary("layout", route, layoutId, existingLayout.rootBoundaryId);
			const layout = {
				id: layoutId,
				treePath,
				rootBoundaryId: route.ids.rootBoundary
			};
			layouts.set(layoutId, layout);
			addRouteManifestBoundaryFacts({
				boundaries,
				route,
				layoutId,
				treePath,
				layoutIndex: index
			});
			if (index === 0 && route.ids.rootBoundary) rootBoundaries.set(route.ids.rootBoundary, {
				id: route.ids.rootBoundary,
				layoutId,
				treePath
			});
		}
		addRouteManifestSegmentErrorBoundaryFacts({
			boundaries,
			route
		});
		for (const [index, templateId] of route.ids.templates.entries()) {
			const treePosition = route.templateTreePositions?.[index];
			assertRouteManifestTreePosition("template", route, templateId, treePosition);
			const treePath = createAppRouteGraphTreePath(route.routeSegments, treePosition);
			const existingTemplate = templates.get(templateId);
			if (existingTemplate) assertRouteManifestRootBoundary("template", route, templateId, existingTemplate.rootBoundaryId);
			templates.set(templateId, {
				id: templateId,
				treePath,
				rootBoundaryId: route.ids.rootBoundary,
				ownerLayoutId: findRouteManifestOwnerLayoutId(route, treePosition),
				reset: {
					kind: "remountSubtree",
					treePath
				}
			});
		}
		for (const slot of route.parallelSlots) {
			const ownerLayoutId = findSlotOwnerLayoutId(route, slot);
			const defaultId = slot.defaultPath ? createAppRouteGraphDefaultId(slot.id) : null;
			slots.set(slot.id, {
				id: slot.id,
				key: slot.key,
				name: slot.name,
				ownerTreePath: slot.ownerTreePath,
				ownerLayoutId,
				rootBoundaryId: ownerLayoutId ? route.ids.rootBoundary : null,
				defaultId,
				hasDefault: slot.defaultPath !== null,
				hasPage: slot.hasPage
			});
			if (defaultId) defaults.set(defaultId, {
				id: defaultId,
				slotId: slot.id,
				ownerTreePath: slot.ownerTreePath,
				ownerLayoutId,
				rootBoundaryId: ownerLayoutId ? route.ids.rootBoundary : null
			});
			const binding = createRouteManifestSlotBinding(route, slot, ownerLayoutId, defaultId);
			slotBindings.set(binding.id, binding);
		}
	}
	return {
		routes: routeEntries,
		pages,
		routeHandlers,
		layouts,
		templates,
		slots,
		defaults,
		slotBindings,
		boundaries,
		rootBoundaries
	};
}
function findRouteManifestOwnerLayoutId(route, treePosition) {
	const layoutIndex = route.layoutTreePositions.indexOf(treePosition);
	return route.ids.layouts[layoutIndex] ?? null;
}
function findSlotOwnerLayoutId(route, slot) {
	if (slot.layoutIndex < 0) return null;
	return route.ids.layouts[slot.layoutIndex] ?? null;
}
function createRouteManifestSlotBinding(route, slot, ownerLayoutId, defaultId) {
	const state = getRouteManifestSlotBindingState(slot);
	const binding = {
		id: `${route.ids.route}::${slot.id}`,
		routeId: route.ids.route,
		slotId: slot.id,
		ownerLayoutId,
		state,
		defaultId: state === "default" ? defaultId : null,
		routeSegments: slot.routeSegments ? [...slot.routeSegments] : null
	};
	if (slot.slotPatternParts) binding.slotPatternParts = [...slot.slotPatternParts];
	if (slot.slotParamNames) binding.slotParamNames = [...slot.slotParamNames];
	return binding;
}
function getRouteManifestSlotBindingState(slot) {
	if (slot.pagePath) return "active";
	if (slot.defaultPath) return "default";
	return "unmatched";
}
function addRouteManifestBoundaryFacts(input) {
	addRouteManifestBoundaryFact(input, "error", input.route.layoutErrorPaths[input.layoutIndex]);
	addRouteManifestBoundaryFact(input, "notFound", input.route.notFoundPaths[input.layoutIndex]);
	addRouteManifestBoundaryFact(input, "forbidden", input.route.forbiddenPaths[input.layoutIndex]);
	addRouteManifestBoundaryFact(input, "unauthorized", input.route.unauthorizedPaths[input.layoutIndex]);
}
function addRouteManifestSegmentErrorBoundaryFacts(input) {
	for (const [index, boundaryPath] of (input.route.errorPaths ?? []).entries()) {
		const treePosition = input.route.errorTreePositions?.[index];
		assertRouteManifestBoundaryTreePosition(input.route, boundaryPath, treePosition);
		const ownerLayoutId = findRouteManifestOwnerLayoutId(input.route, treePosition);
		if (ownerLayoutId !== null) continue;
		const treePath = createAppRouteGraphTreePath(input.route.routeSegments, treePosition);
		addRouteManifestBoundaryFact({
			boundaries: input.boundaries,
			route: input.route,
			layoutId: ownerLayoutId,
			treePath
		}, "error", boundaryPath);
	}
}
function addRouteManifestBoundaryFact(input, outcome, boundaryPath) {
	if (!boundaryPath) return;
	const id = `boundary:${outcome}:${input.treePath}`;
	input.boundaries.set(id, {
		id,
		outcome,
		treePath: input.treePath,
		ownerLayoutId: input.layoutId,
		rootBoundaryId: input.route.ids.rootBoundary
	});
}
function assertRouteManifestTreePosition(kind, route, id, treePosition) {
	if (treePosition !== void 0) return;
	throw new Error(`[vinext] App route graph invariant violated: missing ${kind} tree position for ${id} on ${route.pattern}`);
}
function assertRouteManifestBoundaryTreePosition(route, boundaryPath, treePosition) {
	if (treePosition !== void 0) return;
	throw new Error(`[vinext] App route graph invariant violated: missing boundary tree position for ${boundaryPath} on ${route.pattern}`);
}
function assertRouteManifestRootBoundary(kind, route, id, existingRootBoundaryId) {
	if (existingRootBoundaryId === route.ids.rootBoundary) return;
	throw new Error(`[vinext] App route graph invariant violated: ${kind} ${id} is shared across root boundaries (${existingRootBoundaryId ?? "none"} and ${route.ids.rootBoundary ?? "none"}) on ${route.pattern}`);
}
function createRouteManifestGraphVersion(segmentGraph) {
	const stableShape = {
		routes: sortedMapValues(segmentGraph.routes),
		pages: sortedMapValues(segmentGraph.pages),
		routeHandlers: sortedMapValues(segmentGraph.routeHandlers),
		layouts: sortedMapValues(segmentGraph.layouts),
		templates: sortedMapValues(segmentGraph.templates),
		slots: sortedMapValues(segmentGraph.slots),
		defaults: sortedMapValues(segmentGraph.defaults),
		slotBindings: sortedMapValues(segmentGraph.slotBindings),
		boundaries: sortedMapValues(segmentGraph.boundaries),
		rootBoundaries: sortedMapValues(segmentGraph.rootBoundaries)
	};
	return `graph:${createHash("sha256").update(JSON.stringify(stableShape)).digest("hex")}`;
}
async function buildAppRouteGraph(appDir, matcher) {
	const routes = [];
	const excludeDir = (name) => name.startsWith("@") || name.startsWith("_");
	for await (const file of scanWithExtensions("**/page", appDir, matcher.extensions, excludeDir)) {
		const route = fileToAppRoute(file, appDir, "page", matcher);
		if (route) routes.push(route);
	}
	for await (const file of scanWithExtensions("**/route", appDir, matcher.extensions, excludeDir)) {
		const route = fileToAppRoute(file, appDir, "route", matcher);
		if (route) routes.push(route);
	}
	const routePatterns = new Set(routes.map((route) => route.pattern));
	for await (const file of scanWithExtensions("**/layout", appDir, matcher.extensions, excludeDir)) {
		const dir = path.dirname(file);
		const routeDir = dir === "." ? appDir : path.join(appDir, dir);
		if (!hasParallelSlotDirectory(routeDir)) continue;
		if (discoverParallelSlots(routeDir, appDir, matcher).length === 0) continue;
		const route = directoryToAppRoute(dir, appDir, matcher, null, null);
		if (!route || routePatterns.has(route.pattern)) continue;
		routes.push(route);
		routePatterns.add(route.pattern);
	}
	const slotSubRoutes = discoverSlotSubRoutes(routes, matcher);
	routes.push(...slotSubRoutes);
	validatePageRouteConflicts(routes, appDir);
	validateRoutePatterns(routes.map((route) => route.pattern));
	validateRoutePatterns([...new Set(routes.flatMap((route) => route.parallelSlots.flatMap((slot) => slot.interceptingRoutes.map((intercept) => intercept.targetPattern))))]);
	routes.sort(compareRoutes);
	return {
		routes,
		routeManifest: createRouteManifest(routes)
	};
}
function hasParallelSlotDirectory(dir) {
	try {
		return fs.readdirSync(dir, { withFileTypes: true }).some((entry) => entry.isDirectory() && entry.name.startsWith("@"));
	} catch {
		return false;
	}
}
function validatePageRouteConflicts(routes, appDir) {
	const byPattern = /* @__PURE__ */ new Map();
	for (const route of routes) {
		const entry = byPattern.get(route.pattern);
		if (!entry) {
			byPattern.set(route.pattern, {
				pagePath: route.pagePath,
				routePath: route.routePath
			});
			continue;
		}
		if (!entry.pagePath && route.pagePath) entry.pagePath = route.pagePath;
		if (!entry.routePath && route.routePath) entry.routePath = route.routePath;
	}
	for (const [pattern, entry] of byPattern) {
		if (!entry.pagePath || !entry.routePath) continue;
		throw new Error(`Conflicting route and page at ${pattern}: route at ${formatAppFilePath(entry.routePath, appDir)} and page at ${formatAppFilePath(entry.pagePath, appDir)}`);
	}
}
function formatAppFilePath(filePath, appDir) {
	const relativePath = path.relative(appDir, filePath).replace(/\\/g, "/");
	const parsedPath = path.parse(relativePath);
	const withoutExtension = path.join(parsedPath.dir, parsedPath.name).replace(/\\/g, "/");
	return withoutExtension.startsWith("/") ? withoutExtension : `/${withoutExtension}`;
}
/**
* Discover sub-routes created by nested pages within parallel slots.
*
* In Next.js, pages nested inside @slot directories create additional URL routes.
* For example, given:
*   app/parallel-routes/@audience/demographics/page.tsx
* This creates a route at /parallel-routes/demographics where:
* - children slot → parent's default.tsx
* - @audience slot → @audience/demographics/page.tsx (matched)
* - other slots → their default.tsx (fallback)
*/
function discoverSlotSubRoutes(routes, matcher) {
	const syntheticRoutes = [];
	const routesByPattern = new Map(routes.map((r) => [r.pattern, r]));
	const applySlotSubPages = (route, slotPages, rawSegments) => {
		route.parallelSlots = route.parallelSlots.map((slot) => {
			const subPage = slotPages.get(slot.key);
			if (subPage !== void 0) return {
				...slot,
				pagePath: subPage,
				routeSegments: rawSegments
			};
			return slot;
		});
	};
	for (const parentRoute of routes) {
		if (parentRoute.parallelSlots.length === 0) continue;
		const isLayoutOnlyUiRoute = !parentRoute.pagePath && !parentRoute.routePath && parentRoute.layouts.length > 0;
		if (!parentRoute.pagePath && !isLayoutOnlyUiRoute) continue;
		const parentPageDir = parentRoute.pagePath ? path.dirname(parentRoute.pagePath) : path.dirname(parentRoute.layouts[parentRoute.layouts.length - 1]);
		const subPathMap = /* @__PURE__ */ new Map();
		for (const slot of parentRoute.parallelSlots) {
			if (path.dirname(slot.ownerDir) !== parentPageDir) continue;
			const slotDir = slot.ownerDir;
			if (!fs.existsSync(slotDir)) continue;
			const subPages = findSlotSubPages(slotDir, matcher);
			for (const { relativePath, pagePath } of subPages) {
				const subSegments = relativePath.split(path.sep);
				const convertedSubRoute = convertSegmentsToRouteParts(subSegments);
				if (!convertedSubRoute) continue;
				const { urlSegments } = convertedSubRoute;
				const normalizedSubPath = urlSegments.join("/");
				let subPathEntry = subPathMap.get(normalizedSubPath);
				if (!subPathEntry) {
					subPathEntry = {
						rawSegments: subSegments,
						converted: convertedSubRoute,
						slotPages: /* @__PURE__ */ new Map()
					};
					subPathMap.set(normalizedSubPath, subPathEntry);
				}
				if (subPathEntry.slotPages.get(slot.key)) {
					const pattern = joinRoutePattern(parentRoute.pattern, normalizedSubPath);
					throw new Error(`You cannot have two routes that resolve to the same path ("${pattern}").`);
				}
				subPathEntry.slotPages.set(slot.key, pagePath);
			}
		}
		if (subPathMap.size === 0) continue;
		const childrenDefault = findFile(parentPageDir, "default", matcher);
		if (parentRoute.pagePath && !childrenDefault) continue;
		for (const { rawSegments, converted: convertedSubRoute, slotPages } of subPathMap.values()) {
			const { urlSegments: urlParts, params: subParams, isDynamic: subIsDynamic } = convertedSubRoute;
			const subUrlPath = urlParts.join("/");
			const pattern = joinRoutePattern(parentRoute.pattern, subUrlPath);
			const existingRoute = routesByPattern.get(pattern);
			if (existingRoute) {
				if (existingRoute.routePath && !existingRoute.pagePath) throw new Error(`You cannot have two routes that resolve to the same path ("${pattern}").`);
				applySlotSubPages(existingRoute, slotPages, rawSegments);
				continue;
			}
			const syntheticParts = [...parentRoute.patternParts, ...urlParts];
			if (Array.from(routesByPattern.values()).some((r) => patternsStructurallyEquivalent(r.patternParts, syntheticParts))) continue;
			const subSlots = parentRoute.parallelSlots.map((slot) => {
				const subPage = slotPages.get(slot.key);
				return {
					...slot,
					pagePath: subPage || null,
					routeSegments: subPage ? rawSegments : null
				};
			});
			const newRoute = {
				ids: createAppRouteSemanticIds({
					pattern,
					pagePath: childrenDefault,
					routePath: null,
					routeSegments: [...parentRoute.routeSegments, ...rawSegments],
					layoutTreePositions: parentRoute.layoutTreePositions,
					templateTreePositions: parentRoute.templateTreePositions,
					slots: subSlots
				}),
				pattern,
				pagePath: childrenDefault,
				routePath: null,
				layouts: parentRoute.layouts,
				templates: parentRoute.templates,
				parallelSlots: subSlots,
				loadingPath: parentRoute.loadingPath,
				errorPath: parentRoute.errorPath,
				layoutErrorPaths: parentRoute.layoutErrorPaths,
				notFoundPath: parentRoute.notFoundPath,
				notFoundPaths: parentRoute.notFoundPaths,
				forbiddenPaths: parentRoute.forbiddenPaths,
				forbiddenPath: parentRoute.forbiddenPath,
				unauthorizedPath: parentRoute.unauthorizedPath,
				unauthorizedPaths: parentRoute.unauthorizedPaths,
				routeSegments: [...parentRoute.routeSegments, ...rawSegments],
				templateTreePositions: parentRoute.templateTreePositions,
				layoutTreePositions: parentRoute.layoutTreePositions,
				isDynamic: parentRoute.isDynamic || subIsDynamic,
				params: [...parentRoute.params, ...subParams],
				rootParamNames: parentRoute.rootParamNames,
				patternParts: [...parentRoute.patternParts, ...urlParts]
			};
			syntheticRoutes.push(newRoute);
			routesByPattern.set(pattern, newRoute);
		}
	}
	return syntheticRoutes;
}
const findSlotSubPagesCache = /* @__PURE__ */ new WeakMap();
function findSlotSubPages(slotDir, matcher) {
	let perMatcher = findSlotSubPagesCache.get(matcher);
	if (!perMatcher) {
		perMatcher = /* @__PURE__ */ new Map();
		findSlotSubPagesCache.set(matcher, perMatcher);
	}
	const cached = perMatcher.get(slotDir);
	if (cached) return cached;
	const results = [];
	function scan(dir) {
		if (!fs.existsSync(dir)) return;
		const entries = fs.readdirSync(dir, { withFileTypes: true });
		for (const entry of entries) {
			if (!entry.isDirectory()) continue;
			if (matchInterceptConvention(entry.name)) continue;
			if (entry.name.startsWith("_")) continue;
			const subDir = path.join(dir, entry.name);
			const page = findFile(subDir, "page", matcher);
			if (page) {
				const relativePath = path.relative(slotDir, subDir);
				results.push({
					relativePath,
					pagePath: page
				});
			}
			scan(subDir);
		}
	}
	scan(slotDir);
	perMatcher.set(slotDir, results);
	return results;
}
/**
* Convert a file path relative to app/ into an AppRoute.
*/
function fileToAppRoute(file, appDir, type, matcher) {
	return directoryToAppRoute(path.dirname(file), appDir, matcher, type === "page" ? path.join(appDir, file) : null, type === "route" ? path.join(appDir, file) : null);
}
function directoryToAppRoute(dir, appDir, matcher, pagePath, routePath) {
	const segments = dir === "." ? [] : dir.split(path.sep);
	const params = [];
	let isDynamic = false;
	const convertedRoute = convertSegmentsToRouteParts(segments);
	if (!convertedRoute) return null;
	const { urlSegments, params: routeParams, isDynamic: routeIsDynamic } = convertedRoute;
	params.push(...routeParams);
	isDynamic = routeIsDynamic;
	const pattern = "/" + urlSegments.join("/");
	const layouts = discoverLayouts(segments, appDir, matcher);
	const templates = discoverTemplates(segments, appDir, matcher);
	const templateTreePositions = computeLayoutTreePositions(appDir, templates);
	const layoutTreePositions = computeLayoutTreePositions(appDir, layouts);
	const layoutErrorPaths = discoverLayoutAlignedErrors(segments, appDir, matcher);
	const errorEntries = discoverSegmentErrors(segments, appDir, matcher);
	const errorPaths = errorEntries.map((entry) => entry.path);
	const errorTreePositions = errorEntries.map((entry) => entry.treePosition);
	const routeDir = dir === "." ? appDir : path.join(appDir, dir);
	const loadingPath = findFile(routeDir, "loading", matcher);
	const errorPath = findFile(routeDir, "error", matcher);
	const notFoundPath = discoverBoundaryFile(segments, appDir, "not-found", matcher);
	const forbiddenPath = discoverBoundaryFile(segments, appDir, "forbidden", matcher);
	const unauthorizedPath = discoverBoundaryFile(segments, appDir, "unauthorized", matcher);
	const notFoundPaths = discoverBoundaryFilePerLayout(layouts, "not-found", matcher);
	const forbiddenPaths = discoverBoundaryFilePerLayout(layouts, "forbidden", matcher);
	const unauthorizedPaths = discoverBoundaryFilePerLayout(layouts, "unauthorized", matcher);
	const parallelSlots = discoverInheritedParallelSlots(segments, appDir, routeDir, matcher);
	return {
		ids: createAppRouteSemanticIds({
			pattern: pattern === "/" ? "/" : pattern,
			pagePath,
			routePath,
			routeSegments: segments,
			layoutTreePositions,
			templateTreePositions,
			slots: parallelSlots
		}),
		pattern: pattern === "/" ? "/" : pattern,
		pagePath,
		routePath,
		layouts,
		templates,
		parallelSlots,
		loadingPath,
		errorPath,
		layoutErrorPaths,
		errorPaths,
		errorTreePositions,
		notFoundPath,
		notFoundPaths,
		forbiddenPaths,
		forbiddenPath,
		unauthorizedPath,
		unauthorizedPaths,
		routeSegments: segments,
		templateTreePositions,
		layoutTreePositions,
		isDynamic,
		params,
		rootParamNames: computeRootParamNames(segments, layoutTreePositions),
		patternParts: urlSegments
	};
}
function dynamicParamNameFromSegment(segment) {
	if (segment.startsWith("[[...") && segment.endsWith("]]")) return segment.slice(5, -2);
	if (segment.startsWith("[...") && segment.endsWith("]")) return segment.slice(4, -1);
	if (segment.startsWith("[") && segment.endsWith("]")) return segment.slice(1, -1);
	return null;
}
function computeRootParamNames(routeSegments, layoutTreePositions) {
	const rootLayoutPosition = layoutTreePositions[0];
	if (rootLayoutPosition == null || rootLayoutPosition <= 0) return [];
	const names = [];
	for (const segment of routeSegments.slice(0, rootLayoutPosition)) {
		const name = dynamicParamNameFromSegment(segment);
		if (name && !names.includes(name)) names.push(name);
	}
	return names;
}
function resolveRootBoundaryId(routeSegments, layoutTreePositions) {
	const rootLayoutPosition = layoutTreePositions[0];
	if (rootLayoutPosition === void 0) return null;
	return createAppRouteGraphRootBoundaryId(createAppRouteGraphTreePath(routeSegments, rootLayoutPosition));
}
function createAppRouteSemanticIds(input) {
	const slots = {};
	for (const slot of input.slots) slots[slot.key] = slot.id;
	return {
		route: createAppRouteGraphRouteId(input.pattern),
		page: input.pagePath ? createAppRouteGraphPageId(input.pattern) : null,
		routeHandler: input.routePath ? createAppRouteGraphRouteHandlerId(input.pattern) : null,
		rootBoundary: resolveRootBoundaryId(input.routeSegments, input.layoutTreePositions),
		layouts: input.layoutTreePositions.map((treePosition) => createAppRouteGraphLayoutId(createAppRouteGraphTreePath(input.routeSegments, treePosition))),
		templates: (input.templateTreePositions ?? []).map((treePosition) => createAppRouteGraphTemplateId(createAppRouteGraphTreePath(input.routeSegments, treePosition))),
		slots
	};
}
function createAppRouteGraphTreePath(routeSegments, treePosition) {
	const treePathSegments = routeSegments.slice(0, treePosition);
	if (treePathSegments.length === 0) return "/";
	return `/${treePathSegments.join("/")}`;
}
/**
* Compute the tree position (directory depth from app root) for each layout.
* Root layout = 0, a layout at app/blog/ = 1, app/blog/(group)/ = 2.
* Counts ALL directory levels including route groups and parallel slots.
*/
function computeLayoutTreePositions(appDir, layouts) {
	return layouts.map((layoutPath) => {
		const layoutDir = path.dirname(layoutPath);
		if (layoutDir === appDir) return 0;
		return path.relative(appDir, layoutDir).split(path.sep).length;
	});
}
/**
* Discover all layout files from root to the given directory.
* Each level of the directory tree may have a layout.tsx.
*/
function discoverLayouts(segments, appDir, matcher) {
	const layouts = [];
	const rootLayout = findFile(appDir, "layout", matcher);
	if (rootLayout) layouts.push(rootLayout);
	let currentDir = appDir;
	for (const segment of segments) {
		currentDir = path.join(currentDir, segment);
		const layout = findFile(currentDir, "layout", matcher);
		if (layout) layouts.push(layout);
	}
	return layouts;
}
/**
* Discover all template files from root to the given directory.
* Each level of the directory tree may have a template.tsx.
* Templates are like layouts but re-mount on navigation.
*/
function discoverTemplates(segments, appDir, matcher) {
	const templates = [];
	const rootTemplate = findFile(appDir, "template", matcher);
	if (rootTemplate) templates.push(rootTemplate);
	let currentDir = appDir;
	for (const segment of segments) {
		currentDir = path.join(currentDir, segment);
		const template = findFile(currentDir, "template", matcher);
		if (template) templates.push(template);
	}
	return templates;
}
/**
* Discover error.tsx files by segment tree position.
*
* Next.js stores conventions on every loader-tree segment; a route-group
* directory with error.tsx but no sibling layout.tsx must still wrap its
* descendants. Keeping positions explicit avoids conflating segment boundaries
* with layout component ownership.
*/
function discoverSegmentErrors(segments, appDir, matcher) {
	const errors = [];
	const rootError = findFile(appDir, "error", matcher);
	if (rootError) errors.push({
		path: rootError,
		treePosition: 0
	});
	let currentDir = appDir;
	for (let index = 0; index < segments.length; index++) {
		const segment = segments[index];
		currentDir = path.join(currentDir, segment);
		const error = findFile(currentDir, "error", matcher);
		if (error) errors.push({
			path: error,
			treePosition: index + 1
		});
	}
	return errors;
}
/**
* Discover error.tsx files aligned with the layouts array.
*
* Route manifests still model layout-owned boundary facts by layout index.
* Keep this layout-aligned compatibility shape separate from segment-owned
* error boundaries so route-group errors without layouts do not get attributed
* to unrelated layouts.
*/
function discoverLayoutAlignedErrors(segments, appDir, matcher) {
	const errors = [];
	if (findFile(appDir, "layout", matcher)) errors.push(findFile(appDir, "error", matcher));
	let currentDir = appDir;
	for (const segment of segments) {
		currentDir = path.join(currentDir, segment);
		if (findFile(currentDir, "layout", matcher)) errors.push(findFile(currentDir, "error", matcher));
	}
	return errors;
}
/**
* Discover the nearest boundary file (not-found, forbidden, unauthorized)
* by walking from the route's directory up to the app root.
* Returns the first (closest) file found, or null.
*/
function discoverBoundaryFile(segments, appDir, fileName, matcher) {
	const dirs = [];
	let dir = appDir;
	dirs.push(dir);
	for (const segment of segments) {
		dir = path.join(dir, segment);
		dirs.push(dir);
	}
	for (let i = dirs.length - 1; i >= 0; i--) {
		const f = findFile(dirs[i], fileName, matcher);
		if (f) return f;
	}
	return null;
}
/**
* Discover boundary files (not-found, forbidden, unauthorized) at each layout directory.
* Returns an array aligned with the layouts array, where each entry is the boundary
* file at that layout's directory, or null if none exists there.
*
* This is used for per-layout error boundaries. In Next.js, each layout level
* has its own boundary that wraps the layout's children. When notFound() is thrown
* from a layout, it propagates up to the parent layout's boundary.
*/
function discoverBoundaryFilePerLayout(layouts, fileName, matcher) {
	return layouts.map((layoutPath) => {
		return findFile(path.dirname(layoutPath), fileName, matcher);
	});
}
/**
* Discover parallel slots inherited from ancestor directories.
*
* In Next.js, parallel slots belong to the layout that defines them. When a
* child route is rendered, its parent layout's slots must still be present.
* If the child doesn't have matching content in a slot, the slot's default.tsx
* is rendered instead.
*
* Walk from appDir through each segment to the route's directory. At each level
* that has @slot dirs, collect them. Slots at the route's own directory level
* use page.tsx; slots at ancestor levels use default.tsx only.
*/
function discoverInheritedParallelSlots(segments, appDir, routeDir, matcher) {
	const slotMap = /* @__PURE__ */ new Map();
	let currentDir = appDir;
	const dirsToCheck = [];
	let layoutIdx = findFile(appDir, "layout", matcher) ? 0 : -1;
	dirsToCheck.push({
		dir: appDir,
		layoutIdx,
		segmentIndex: 0
	});
	for (let i = 0; i < segments.length; i++) {
		currentDir = path.join(currentDir, segments[i]);
		if (findFile(currentDir, "layout", matcher)) layoutIdx++;
		dirsToCheck.push({
			dir: currentDir,
			layoutIdx,
			segmentIndex: i + 1
		});
	}
	const routeHasLayout = layoutIdx >= 0;
	for (const { dir, layoutIdx: lvlLayoutIdx, segmentIndex } of dirsToCheck) {
		if (lvlLayoutIdx < 0 && routeHasLayout) continue;
		const isOwnDir = dir === routeDir;
		const slotLayoutIdx = Math.max(lvlLayoutIdx, 0);
		const slotsAtLevel = discoverParallelSlots(dir, appDir, matcher);
		const segmentsBelow = segments.slice(segmentIndex);
		for (const slot of slotsAtLevel) if (isOwnDir) {
			slot.layoutIndex = slotLayoutIdx;
			slotMap.set(slot.key, slot);
		} else {
			const mirror = findMirroredSlotPage(slot.ownerDir, segmentsBelow, matcher);
			let slotPatternParts;
			let slotParamNames;
			if (mirror) {
				const ownerUrl = convertSegmentsToRouteParts([...segments.slice(0, segmentIndex)]);
				slotPatternParts = [...ownerUrl?.urlSegments ?? [], ...mirror.slotUrlSegments];
				slotParamNames = [...ownerUrl?.params ?? [], ...mirror.slotParamNames];
			}
			const inheritedSlot = {
				...slot,
				pagePath: mirror?.pagePath ?? null,
				layoutIndex: slotLayoutIdx,
				routeSegments: mirror?.segments ?? null,
				slotPatternParts,
				slotParamNames
			};
			slotMap.set(slot.key, inheritedSlot);
		}
	}
	return Array.from(slotMap.values());
}
/**
* Look for a page file inside a parallel slot directory that mirrors the
* route's path below the slot's owner. The match falls through two tiers:
*   1. Literal filesystem path — fast path when route and slot share shape.
*   2. Scored pattern compatibility — enumerate sub-pages, accept those
*      whose URL pattern can match the route's URL space (slot dynamic
*      markers may have different names than the route's, and slot
*      catch-alls may subsume the route), and pick the most-specific via
*      `scoreSlotPattern`. Exact URL-parts equality (e.g. through route
*      groups appearing on only one side, like `(marketing)/about` ↔
*      `@breadcrumbs/about`) naturally wins because all literal segments
*      score highest.
*
* Returns the slot sub-page's absolute path, its raw filesystem segments
* (for `routeSegments`), and its URL parts / param names (for
* `slotPatternParts` / `slotParamNames`). Returns null when no mirror matches.
*/
function findMirroredSlotPage(slotDir, segmentsBelow, matcher) {
	if (segmentsBelow.length === 0) return null;
	const routeUrl = convertSegmentsToRouteParts([...segmentsBelow]);
	const literalPage = findFile(path.join(slotDir, ...segmentsBelow), "page", matcher);
	if (literalPage) return {
		pagePath: literalPage,
		segments: [...segmentsBelow],
		slotUrlSegments: routeUrl?.urlSegments ?? [],
		slotParamNames: routeUrl?.params ?? []
	};
	if (!routeUrl || routeUrl.urlSegments.length === 0) return null;
	let best = null;
	for (const { relativePath, pagePath } of findSlotSubPages(slotDir, matcher)) {
		const slotSegments = relativePath.split(path.sep);
		const slotUrl = convertSegmentsToRouteParts(slotSegments);
		if (!slotUrl) continue;
		if (!patternsCompatible(slotUrl.urlSegments, routeUrl.urlSegments)) continue;
		const score = scoreSlotPattern(slotUrl.urlSegments);
		if (!best || score > best.score) best = {
			pagePath,
			segments: slotSegments,
			slotUrlSegments: slotUrl.urlSegments,
			slotParamNames: slotUrl.params,
			score
		};
	}
	return best;
}
/**
* Whether a slot pattern can match the same URL space as the route's URL
* parts (where the route's parts are themselves a pattern, since a route
* file like `[id]/page.tsx` produces `:id`).
*
* - `:name+` (catch-all) consumes one-or-more remaining segments.
* - `:name*` (optional catch-all) consumes zero-or-more.
* - `:name` (single dynamic) consumes exactly one segment, matching any
*   route segment (literal or dynamic).
* - Literal slot segments must equal the route's segment exactly; a literal
*   slot segment paired with a dynamic route segment is rejected because we
*   can't know statically whether the runtime value will equal the literal.
*   This also means a literal slot sub-page never matches a catch-all route
*   (e.g. slot `about/page.tsx` is not bound to a route `[...slug]`) — the
*   catch-all might or might not resolve to "about" at request time.
*/
function patternsCompatible(slotParts, routeParts) {
	let i = 0;
	let j = 0;
	while (i < slotParts.length) {
		const sp = slotParts[i];
		if (sp.endsWith("+")) return j < routeParts.length;
		if (sp.endsWith("*")) return true;
		if (j >= routeParts.length) return false;
		const rp = routeParts[j];
		if (sp.startsWith(":")) {
			i++;
			j++;
			continue;
		}
		if (rp.startsWith(":")) return false;
		if (sp !== rp) return false;
		i++;
		j++;
	}
	return j === routeParts.length;
}
/**
* Score a slot pattern by specificity so the most-specific match wins:
*   literal > single dynamic > catch-all > optional catch-all.
*
* Required catch-all (`:name+`, ≥1 segment) is more constrained than the
* optional variant (`:name*`, ≥0 segments), so it scores higher.
*/
function scoreSlotPattern(urlSegments) {
	let score = 0;
	for (const seg of urlSegments) if (seg.endsWith("*")) score += 1;
	else if (seg.endsWith("+")) score += 2;
	else if (seg.startsWith(":")) score += 3;
	else score += 4;
	return score;
}
/**
* Map a pattern segment to the tree-node type used by Next.js' route
* validator. Two segments are structurally equivalent iff they share the
* same tree-node type.
*/
function segmentTreeNodeType(seg) {
	if (!seg.startsWith(":")) return `literal:${seg}`;
	if (seg.endsWith("*")) return "optionalCatchAll";
	if (seg.endsWith("+")) return "catchAll";
	return "dynamic";
}
function patternsStructurallyEquivalent(a, b) {
	if (a.length !== b.length) return false;
	for (let i = 0; i < a.length; i++) if (segmentTreeNodeType(a[i]) !== segmentTreeNodeType(b[i])) return false;
	return true;
}
/**
* Discover parallel route slots (@team, @analytics, etc.) in a directory.
* Returns a ParallelSlot for each @-prefixed subdirectory that has a page or default component.
*/
function discoverParallelSlots(dir, appDir, matcher) {
	if (!fs.existsSync(dir)) return [];
	const entries = fs.readdirSync(dir, { withFileTypes: true });
	const slots = [];
	for (const entry of entries) {
		if (!entry.isDirectory() || !entry.name.startsWith("@")) continue;
		const slotName = entry.name.slice(1);
		const slotDir = path.join(dir, entry.name);
		const pagePath = findFile(slotDir, "page", matcher);
		const defaultPath = findFile(slotDir, "default", matcher);
		const interceptingRoutes = discoverInterceptingRoutes(slotDir, dir, appDir, matcher);
		if (!pagePath && !defaultPath && interceptingRoutes.length === 0) continue;
		const ownerSegments = path.relative(appDir, dir).split(path.sep).filter((segment) => segment.length > 0);
		const ownerTreePath = createAppRouteGraphTreePath(ownerSegments, ownerSegments.length);
		slots.push({
			id: createAppRouteGraphSlotId(slotName, ownerTreePath),
			key: `${slotName}@${path.relative(appDir, slotDir).replace(/\\/g, "/")}`,
			name: slotName,
			ownerDir: slotDir,
			ownerTreePath,
			hasPage: pagePath !== null,
			pagePath,
			defaultPath,
			layoutPath: findFile(slotDir, "layout", matcher),
			loadingPath: findFile(slotDir, "loading", matcher),
			errorPath: findFile(slotDir, "error", matcher),
			interceptingRoutes,
			layoutIndex: -1,
			routeSegments: pagePath ? [] : null
		});
	}
	return slots;
}
/**
* The interception convention prefix patterns.
* (.) — same level, (..) — one level up, (..)(..)" — two levels up, (...) — root
*/
const INTERCEPT_PATTERNS = [
	{
		prefix: "(...)",
		convention: "..."
	},
	{
		prefix: "(..)(..)",
		convention: "../.."
	},
	{
		prefix: "(..)",
		convention: ".."
	},
	{
		prefix: "(.)",
		convention: "."
	}
];
/**
* Discover intercepting routes inside a parallel slot directory.
*
* Intercepting routes use conventions like (.)photo, (..)feed, (...), etc.
* They intercept navigation to another route and render within the slot instead.
*
* @param slotDir - The parallel slot directory (e.g. app/feed/@modal)
* @param routeDir - The directory of the route that owns this slot (e.g. app/feed)
* @param appDir - The root app directory
*/
function discoverInterceptingRoutes(slotDir, routeDir, appDir, matcher) {
	if (!fs.existsSync(slotDir)) return [];
	const results = [];
	scanForInterceptingPages(slotDir, routeDir, appDir, results, matcher);
	return results;
}
/**
* Recursively scan a directory tree for page.tsx files that are inside
* intercepting route directories.
*/
function scanForInterceptingPages(currentDir, routeDir, appDir, results, matcher) {
	if (!fs.existsSync(currentDir)) return;
	const entries = fs.readdirSync(currentDir, { withFileTypes: true });
	for (const entry of entries) {
		if (!entry.isDirectory()) continue;
		if (entry.name.startsWith("_")) continue;
		const interceptMatch = matchInterceptConvention(entry.name);
		if (interceptMatch) {
			const restOfName = entry.name.slice(interceptMatch.prefix.length);
			const interceptDir = path.join(currentDir, entry.name);
			collectInterceptingPages(interceptDir, interceptDir, interceptMatch.convention, restOfName, routeDir, appDir, results, matcher);
		} else scanForInterceptingPages(path.join(currentDir, entry.name), routeDir, appDir, results, matcher);
	}
}
/**
* Match a directory name against interception convention prefixes.
*/
function matchInterceptConvention(name) {
	for (const pattern of INTERCEPT_PATTERNS) if (name.startsWith(pattern.prefix)) return pattern;
	return null;
}
/**
* Collect page.tsx files inside an intercepting route directory tree
* and compute their target URL patterns.
*/
function collectInterceptingPages(currentDir, interceptRoot, convention, interceptSegment, routeDir, appDir, results, matcher, parentLayoutPaths = []) {
	const currentLayoutPath = findFile(currentDir, "layout", matcher);
	const layoutPaths = currentLayoutPath ? [...parentLayoutPaths, currentLayoutPath] : parentLayoutPaths;
	const page = findFile(currentDir, "page", matcher);
	if (page) {
		const targetPattern = computeInterceptTarget(convention, interceptSegment, currentDir, interceptRoot, routeDir, appDir);
		if (targetPattern) results.push({
			convention,
			layoutPaths: [...layoutPaths],
			targetPattern: targetPattern.pattern,
			pagePath: page,
			params: targetPattern.params
		});
	}
	if (!fs.existsSync(currentDir)) return;
	const entries = fs.readdirSync(currentDir, { withFileTypes: true });
	for (const entry of entries) {
		if (!entry.isDirectory()) continue;
		if (entry.name.startsWith("_")) continue;
		collectInterceptingPages(path.join(currentDir, entry.name), interceptRoot, convention, interceptSegment, routeDir, appDir, results, matcher, layoutPaths);
	}
}
/**
* Check whether a path segment is invisible in the URL (route groups, parallel slots, ".").
*
* Used by computeInterceptTarget, convertSegmentsToRouteParts, and
* hasRemainingVisibleSegments — keep this the single source of truth.
*/
function isInvisibleSegment(segment) {
	if (segment === ".") return true;
	if (segment.startsWith("(") && segment.endsWith(")")) return true;
	if (segment.startsWith("@")) return true;
	return false;
}
/**
* Compute the target URL pattern for an intercepting route.
*
* Interception conventions (..), (..)(..)" climb by *visible route segments*
* (not filesystem directories). Route groups like (marketing) and parallel
* slots like @modal are invisible and must be skipped when counting levels.
*
* - (.) same level: resolve relative to routeDir
* - (..) one level up: climb 1 visible segment
* - (..)(..) two levels up: climb 2 visible segments
* - (...) root: resolve from appDir
*/
function computeInterceptTarget(convention, interceptSegment, currentDir, interceptRoot, routeDir, appDir) {
	const routeSegments = path.relative(appDir, routeDir).split(path.sep).filter(Boolean);
	let baseParts;
	switch (convention) {
		case ".":
			baseParts = routeSegments;
			break;
		case "..":
		case "../..": {
			const levelsToClimb = convention === ".." ? 1 : 2;
			let climbed = 0;
			let cutIndex = routeSegments.length;
			while (cutIndex > 0 && climbed < levelsToClimb) {
				cutIndex--;
				if (!isInvisibleSegment(routeSegments[cutIndex])) climbed++;
			}
			if (climbed < levelsToClimb) {
				const interceptionRoute = formatInterceptionRoutePath(routeSegments, convention, interceptSegment, path.relative(interceptRoot, currentDir).split(path.sep).filter(Boolean));
				if (convention === "..") throw new Error(`Invalid interception route: ${interceptionRoute}. Cannot use (..) marker at the root level, use (.) instead.`);
				throw new Error(`Invalid interception route: ${interceptionRoute}. Cannot use (..)(..) marker at the root level or one level up.`);
			}
			baseParts = routeSegments.slice(0, cutIndex);
			break;
		}
		case "...":
			baseParts = [];
			break;
		default: return null;
	}
	const nestedParts = path.relative(interceptRoot, currentDir).split(path.sep).filter(Boolean);
	const convertedTarget = convertSegmentsToRouteParts([
		...baseParts,
		interceptSegment,
		...nestedParts
	]);
	if (!convertedTarget) return null;
	const { urlSegments, params } = convertedTarget;
	const pattern = "/" + urlSegments.join("/");
	return {
		pattern: pattern === "/" ? "/" : pattern,
		params
	};
}
function formatInterceptionRoutePath(routeSegments, convention, interceptSegment, nestedParts) {
	const marker = markerForInterceptionConvention(convention);
	const convertedRoute = convertSegmentsToRouteParts(routeSegments);
	const routePath = [
		...convertedRoute ? convertedRoute.urlSegments : routeSegments.filter((segment) => !isInvisibleSegment(segment)),
		`${marker}${interceptSegment}`,
		...nestedParts
	].filter(Boolean).join("/");
	return routePath ? `/${routePath}` : "/";
}
function markerForInterceptionConvention(convention) {
	switch (convention) {
		case ".": return "(.)";
		case "..": return "(..)";
		case "../..": return "(..)(..)";
		case "...": return "(...)";
		default: return "";
	}
}
/**
* Find a file by name (without extension) in a directory.
* Checks configured pageExtensions.
*/
function findFile(dir, name, matcher) {
	for (const ext of matcher.dottedExtensions) {
		const filePath = path.join(dir, name + ext);
		if (fs.existsSync(filePath)) return filePath;
	}
	return null;
}
/**
* Convert filesystem path segments to URL route parts, skipping invisible segments
* (route groups, @slots, ".") and converting dynamic segment syntax to Express-style
* patterns (e.g. "[id]" → ":id", "[...slug]" → ":slug+").
*/
function convertSegmentsToRouteParts(segments) {
	const urlSegments = [];
	const params = [];
	let isDynamic = false;
	for (let i = 0; i < segments.length; i++) {
		const segment = segments[i];
		if (isInvisibleSegment(segment)) continue;
		const catchAllMatch = segment.match(/^\[\.\.\.([^\]]+)\]$/);
		if (catchAllMatch) {
			if (hasRemainingVisibleSegments(segments, i + 1)) return null;
			if (catchAllMatch[1].endsWith("+") || catchAllMatch[1].endsWith("*")) return null;
			isDynamic = true;
			params.push(catchAllMatch[1]);
			urlSegments.push(`:${catchAllMatch[1]}+`);
			continue;
		}
		const optionalCatchAllMatch = segment.match(/^\[\[\.\.\.([^\]]+)\]\]$/);
		if (optionalCatchAllMatch) {
			if (hasRemainingVisibleSegments(segments, i + 1)) return null;
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
	return {
		urlSegments,
		params,
		isDynamic
	};
}
function hasRemainingVisibleSegments(segments, startIndex) {
	for (let i = startIndex; i < segments.length; i++) if (!isInvisibleSegment(segments[i])) return true;
	return false;
}
function joinRoutePattern(basePattern, subPath) {
	if (!subPath) return basePattern;
	return basePattern === "/" ? `/${subPath}` : `${basePattern}/${subPath}`;
}
//#endregion
export { buildAppRouteGraph, computeRootParamNames };

//# sourceMappingURL=app-route-graph.js.map