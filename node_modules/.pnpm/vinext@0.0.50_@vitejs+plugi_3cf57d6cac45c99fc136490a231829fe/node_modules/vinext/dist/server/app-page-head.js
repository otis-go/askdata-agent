import { runWithFetchDedupe } from "../shims/fetch-cache.js";
import { mergeMetadataEntries, mergeViewport, postProcessMetadata, resolveModuleMetadata, resolveModuleViewport } from "../shims/metadata.js";
import { resolveAppPageSegmentParams } from "./app-page-params.js";
import { applyFileBasedMetadata } from "./file-based-metadata.js";
//#region src/server/app-page-head.ts
function resolveActiveParallelRouteHeadInputs(options) {
	return Object.entries(options.slots ?? {}).map(([slotKey, slot]) => {
		if (options.interceptSlotKey === slotKey && options.interceptPage) return {
			layoutModules: options.interceptLayouts ?? [],
			pageModule: options.interceptPage,
			params: options.interceptParams ?? options.params,
			routeSegments: options.routeSegments
		};
		return {
			layoutModules: slot.layout ? [slot.layout] : [],
			pageModule: slot.page,
			params: options.params,
			routeSegments: options.routeSegments
		};
	});
}
function isPresent(value) {
	return value !== null && value !== void 0;
}
function collectAppPageSearchParams(searchParams) {
	const pageSearchParams = Object.create(null);
	let hasSearchParams = false;
	searchParams?.forEach((value, key) => {
		hasSearchParams = true;
		const currentValue = pageSearchParams[key];
		if (Array.isArray(currentValue)) {
			pageSearchParams[key] = [...currentValue, value];
			return;
		}
		if (currentValue !== void 0) {
			pageSearchParams[key] = [currentValue, value];
			return;
		}
		pageSearchParams[key] = value;
	});
	return {
		hasSearchParams,
		pageSearchParams
	};
}
function createMetadataSources(metadataResults, routeSegments, layoutTreePositions, pageMetadata, includePageSource) {
	const metadataSources = metadataResults.map((metadata, index) => ({
		routeSegments: routeSegments.slice(0, layoutTreePositions[index] ?? 0),
		metadata
	}));
	if (includePageSource) metadataSources.push({
		routeSegments,
		metadata: pageMetadata
	});
	return metadataSources;
}
function createLayoutInputs(layoutModules, layoutTreePositions) {
	const layoutInputs = [];
	for (let index = 0; index < layoutModules.length; index++) {
		const layoutModule = layoutModules[index];
		if (!isPresent(layoutModule)) continue;
		layoutInputs.push({
			module: layoutModule,
			treePosition: layoutTreePositions[index] ?? 0
		});
	}
	return layoutInputs;
}
async function resolveLayoutMetadata(layoutInputs, params, routeSegments) {
	const layoutMetadataPromises = [];
	let accumulatedMetadata = Promise.resolve({});
	for (const layoutInput of layoutInputs) {
		const parentForLayout = accumulatedMetadata;
		const layoutParams = resolveAppPageSegmentParams(routeSegments, layoutInput.treePosition, params);
		const metadataPromise = resolveModuleMetadata(layoutInput.module, layoutParams, void 0, parentForLayout);
		layoutMetadataPromises.push(metadataPromise);
		metadataPromise.catch(() => null);
		accumulatedMetadata = metadataPromise.then(async (metadataResult) => {
			if (metadataResult) return mergeMetadataEntries([{ metadata: await parentForLayout }, { metadata: metadataResult }]);
			return parentForLayout;
		});
		accumulatedMetadata.catch(() => null);
	}
	return Promise.all(layoutMetadataPromises);
}
async function resolveLayoutViewport(layoutInputs, params, routeSegments) {
	return Promise.all(layoutInputs.map((layoutInput) => {
		const layoutParams = resolveAppPageSegmentParams(routeSegments, layoutInput.treePosition, params);
		return resolveModuleViewport(layoutInput.module, layoutParams);
	}));
}
async function resolveParallelRouteHead(parallelRoute, fallbackParams, fallbackRouteSegments, pageSearchParams, parent) {
	const params = parallelRoute.params ?? fallbackParams;
	const routeSegments = parallelRoute.routeSegments ?? fallbackRouteSegments;
	const metadataResults = [];
	const viewportResults = [];
	const metadataSources = [];
	let accumulatedMetadata = parent;
	const layoutModules = [...parallelRoute.layoutModules ?? [], parallelRoute.layoutModule].filter(isPresent);
	const layoutViewportPromises = layoutModules.map((layoutModule) => resolveModuleViewport(layoutModule, params));
	const pageViewportPromise = parallelRoute.pageModule ? resolveModuleViewport(parallelRoute.pageModule, params) : Promise.resolve(null);
	for (const layoutViewportPromise of layoutViewportPromises) layoutViewportPromise.catch(() => null);
	pageViewportPromise.catch(() => null);
	for (const layoutModule of layoutModules) {
		const layoutMetadata = await resolveModuleMetadata(layoutModule, params, void 0, accumulatedMetadata);
		metadataResults.push(layoutMetadata);
		metadataSources.push({
			metadata: layoutMetadata,
			routeSegments
		});
		if (layoutMetadata) {
			accumulatedMetadata = accumulatedMetadata.then(async (parentMetadata) => mergeMetadataEntries([{ metadata: parentMetadata }, { metadata: layoutMetadata }]));
			accumulatedMetadata.catch(() => null);
		}
	}
	if (parallelRoute.pageModule) {
		const pageMetadata = await resolveModuleMetadata(parallelRoute.pageModule, params, pageSearchParams, accumulatedMetadata);
		metadataResults.push(pageMetadata);
		metadataSources.push({
			metadata: pageMetadata,
			routeSegments
		});
	}
	viewportResults.push(...await Promise.all(layoutViewportPromises));
	const pageViewport = await pageViewportPromise;
	if (parallelRoute.pageModule) viewportResults.push(pageViewport);
	return {
		metadataResults,
		metadataSources,
		viewportResults
	};
}
async function resolveAppPageHead(options) {
	return await runWithFetchDedupe(() => resolveAppPageHeadInner(options));
}
async function resolveAppPageHeadInner(options) {
	const routeSegments = options.routeSegments ?? [];
	const layoutTreePositions = options.layoutTreePositions ?? [];
	const layoutInputs = createLayoutInputs(options.layoutModules, layoutTreePositions);
	const layoutSourcePositions = layoutInputs.map((input) => input.treePosition);
	const { hasSearchParams, pageSearchParams } = collectAppPageSearchParams(options.searchParams);
	const layoutMetadataPromise = resolveLayoutMetadata(layoutInputs, options.params, routeSegments);
	const layoutViewportPromise = resolveLayoutViewport(layoutInputs, options.params, routeSegments);
	const layoutMetadataResultsForParent = layoutMetadataPromise.then((metadataResults) => metadataResults.filter(isPresent));
	layoutMetadataResultsForParent.catch(() => null);
	const pageParentPromise = layoutMetadataResultsForParent.then((metadataResults) => metadataResults.length > 0 ? mergeMetadataEntries(metadataResults.map((metadata) => ({ metadata }))) : {});
	pageParentPromise.catch(() => null);
	const pageMetadataPromise = options.pageModule ? resolveModuleMetadata(options.pageModule, options.params, pageSearchParams, pageParentPromise) : Promise.resolve(null);
	const pageViewportPromise = options.pageModule ? resolveModuleViewport(options.pageModule, options.params) : Promise.resolve(null);
	const parallelRouteHeadPromise = Promise.all((options.parallelRoutes ?? []).map((parallelRoute) => resolveParallelRouteHead(parallelRoute, options.params, routeSegments, pageSearchParams, pageParentPromise)));
	const [layoutMetadataResults, layoutViewportResults, pageMetadata, pageViewport, parallelRouteHeads] = await Promise.all([
		layoutMetadataPromise,
		layoutViewportPromise,
		pageMetadataPromise,
		pageViewportPromise,
		parallelRouteHeadPromise
	]);
	const parallelMetadataResults = parallelRouteHeads.flatMap((head) => head.metadataResults);
	const parallelViewportResults = parallelRouteHeads.flatMap((head) => head.viewportResults);
	const parallelMetadataSources = parallelRouteHeads.flatMap((head) => head.metadataSources);
	const metadataEntries = [
		...layoutMetadataResults.filter(isPresent).map((metadata) => ({ metadata })),
		...pageMetadata ? [{
			isPage: true,
			metadata: pageMetadata
		}] : [],
		...parallelMetadataResults.filter(isPresent).map((metadata) => ({
			contributesTitle: false,
			metadata
		}))
	];
	const viewportList = [
		...layoutViewportResults.filter(isPresent),
		...pageViewport ? [pageViewport] : [],
		...parallelViewportResults.filter(isPresent)
	];
	const resolvedMetadataBase = metadataEntries.length > 0 ? mergeMetadataEntries(metadataEntries) : null;
	const metadataSources = createMetadataSources(layoutMetadataResults, routeSegments, layoutSourcePositions, pageMetadata, Boolean(options.pageModule));
	metadataSources.push(...parallelMetadataSources);
	let metadata = resolvedMetadataBase;
	try {
		metadata = await applyFileBasedMetadata(resolvedMetadataBase, options.routePath, options.params, options.metadataRoutes, {
			routeSegments,
			metadataSources
		});
	} catch (error) {
		if (!options.fallbackOnFileMetadataError) throw error;
		console.error(`[vinext] File-based metadata resolution failed while rendering error boundary for ${options.routePath}:`, error);
	}
	if (metadata) metadata = postProcessMetadata(metadata);
	return {
		hasSearchParams,
		metadata,
		pageSearchParams,
		viewport: mergeViewport(viewportList)
	};
}
//#endregion
export { collectAppPageSearchParams, resolveActiveParallelRouteHeadInputs, resolveAppPageHead };

//# sourceMappingURL=app-page-head.js.map