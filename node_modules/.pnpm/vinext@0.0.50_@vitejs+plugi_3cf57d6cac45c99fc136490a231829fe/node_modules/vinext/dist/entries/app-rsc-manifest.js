import { normalizePathSeparators } from "./runtime-entry-module.js";
import { createMetadataRouteEntriesSource } from "../server/metadata-route-build-data.js";
//#region src/entries/app-rsc-manifest.ts
function createImportAllocator() {
	const imports = [];
	const importMap = /* @__PURE__ */ new Map();
	let importIdx = 0;
	return {
		importMap,
		imports,
		getImportVar(filePath) {
			const existing = importMap.get(filePath);
			if (existing) return existing;
			const varName = `mod_${importIdx++}`;
			const absPath = normalizePathSeparators(filePath);
			imports.push(`import * as ${varName} from ${JSON.stringify(absPath)};`);
			importMap.set(filePath, varName);
			return varName;
		}
	};
}
function registerRouteModules(routes, imports) {
	for (const route of routes) {
		if (route.pagePath) imports.getImportVar(route.pagePath);
		if (route.routePath) imports.getImportVar(route.routePath);
		for (const layout of route.layouts) imports.getImportVar(layout);
		for (const tmpl of route.templates) imports.getImportVar(tmpl);
		if (route.loadingPath) imports.getImportVar(route.loadingPath);
		if (route.errorPath) imports.getImportVar(route.errorPath);
		if (route.layoutErrorPaths) {
			for (const ep of route.layoutErrorPaths) if (ep) imports.getImportVar(ep);
		}
		if (route.errorPaths) for (const ep of route.errorPaths) imports.getImportVar(ep);
		if (route.notFoundPath) imports.getImportVar(route.notFoundPath);
		if (route.notFoundPaths) {
			for (const nfp of route.notFoundPaths) if (nfp) imports.getImportVar(nfp);
		}
		if (route.forbiddenPath) imports.getImportVar(route.forbiddenPath);
		if (route.forbiddenPaths) {
			for (const fp of route.forbiddenPaths) if (fp) imports.getImportVar(fp);
		}
		if (route.unauthorizedPath) imports.getImportVar(route.unauthorizedPath);
		if (route.unauthorizedPaths) {
			for (const up of route.unauthorizedPaths) if (up) imports.getImportVar(up);
		}
		for (const slot of route.parallelSlots) {
			if (slot.pagePath) imports.getImportVar(slot.pagePath);
			if (slot.defaultPath) imports.getImportVar(slot.defaultPath);
			if (slot.layoutPath) imports.getImportVar(slot.layoutPath);
			if (slot.loadingPath) imports.getImportVar(slot.loadingPath);
			if (slot.errorPath) imports.getImportVar(slot.errorPath);
			for (const ir of slot.interceptingRoutes) {
				imports.getImportVar(ir.pagePath);
				for (const layoutPath of ir.layoutPaths) imports.getImportVar(layoutPath);
			}
		}
	}
}
function buildRouteEntries(routes, imports) {
	return routes.map((route, routeIdx) => {
		const layoutVars = route.layouts.map((l) => imports.getImportVar(l));
		const templateVars = route.templates.map((t) => imports.getImportVar(t));
		const notFoundVars = (route.notFoundPaths ?? []).map((nf) => nf ? imports.getImportVar(nf) : "null");
		const forbiddenVars = (route.forbiddenPaths ?? []).map((fp) => fp ? imports.getImportVar(fp) : "null");
		const unauthorizedVars = (route.unauthorizedPaths ?? []).map((up) => up ? imports.getImportVar(up) : "null");
		const slotEntries = route.parallelSlots.map((slot) => {
			const interceptEntries = slot.interceptingRoutes.map((ir) => `        {
          convention: ${JSON.stringify(ir.convention)},
          targetPattern: ${JSON.stringify(ir.targetPattern)},
          interceptLayouts: [${ir.layoutPaths.map((layoutPath) => imports.getImportVar(layoutPath)).join(", ")}],
          page: ${imports.getImportVar(ir.pagePath)},
          params: ${JSON.stringify(ir.params)},
        }`);
			return `      ${JSON.stringify(slot.key)}: {
        id: ${JSON.stringify(slot.id ?? null)},
        name: ${JSON.stringify(slot.name)},
        page: ${slot.pagePath ? imports.getImportVar(slot.pagePath) : "null"},
        default: ${slot.defaultPath ? imports.getImportVar(slot.defaultPath) : "null"},
        layout: ${slot.layoutPath ? imports.getImportVar(slot.layoutPath) : "null"},
        loading: ${slot.loadingPath ? imports.getImportVar(slot.loadingPath) : "null"},
        error: ${slot.errorPath ? imports.getImportVar(slot.errorPath) : "null"},
        layoutIndex: ${slot.layoutIndex},
        routeSegments: ${JSON.stringify(slot.routeSegments)},
        slotPatternParts: ${slot.slotPatternParts ? JSON.stringify(slot.slotPatternParts) : "null"},
        slotParamNames: ${slot.slotParamNames ? JSON.stringify(slot.slotParamNames) : "null"},
        intercepts: [
${interceptEntries.join(",\n")}
        ],
      }`;
		});
		const layoutErrorVars = (route.layoutErrorPaths || []).map((ep) => ep ? imports.getImportVar(ep) : "null");
		const errorVars = (route.errorPaths ?? []).map((ep) => imports.getImportVar(ep));
		return `  {
    __buildTimeClassifications: __VINEXT_CLASS(${routeIdx}), // evaluated once at module load
    __buildTimeReasons: __classDebug ? __VINEXT_CLASS_REASONS(${routeIdx}) : null,
    ids: ${JSON.stringify(route.ids ?? null)},
    pattern: ${JSON.stringify(route.pattern)},
    patternParts: ${JSON.stringify(route.patternParts)},
    isDynamic: ${route.isDynamic},
    params: ${JSON.stringify(route.params)},
    rootParamNames: ${JSON.stringify(route.rootParamNames ?? [])},
    page: ${route.pagePath ? imports.getImportVar(route.pagePath) : "null"},
    routeHandler: ${route.routePath ? imports.getImportVar(route.routePath) : "null"},
    layouts: [${layoutVars.join(", ")}],
    routeSegments: ${JSON.stringify(route.routeSegments)},
    templateTreePositions: ${JSON.stringify(route.templateTreePositions)},
    layoutTreePositions: ${JSON.stringify(route.layoutTreePositions)},
    templates: [${templateVars.join(", ")}],
    errors: [${layoutErrorVars.join(", ")}],
    errorPaths: [${errorVars.join(", ")}],
    errorTreePositions: ${JSON.stringify(route.errorTreePositions ?? null)},
    slots: {
${slotEntries.join(",\n")}
    },
    loading: ${route.loadingPath ? imports.getImportVar(route.loadingPath) : "null"},
    error: ${route.errorPath ? imports.getImportVar(route.errorPath) : "null"},
    notFound: ${route.notFoundPath ? imports.getImportVar(route.notFoundPath) : "null"},
    notFounds: [${notFoundVars.join(", ")}],
    forbidden: ${route.forbiddenPath ? imports.getImportVar(route.forbiddenPath) : "null"},
    forbiddens: [${forbiddenVars.join(", ")}],
    unauthorized: ${route.unauthorizedPath ? imports.getImportVar(route.unauthorizedPath) : "null"},
    unauthorizeds: [${unauthorizedVars.join(", ")}],
  }`;
	});
}
function buildGenerateStaticParamsEntries(routes, imports) {
	const entries = [];
	for (const route of routes) {
		if (!route.isDynamic || !route.pagePath) continue;
		entries.push(`  ${JSON.stringify(route.pattern)}: ${imports.getImportVar(route.pagePath)}?.generateStaticParams ?? null,`);
	}
	return entries;
}
function buildAppRscManifestCode(options) {
	const imports = createImportAllocator();
	const metadataRoutes = options.metadataRoutes ?? [];
	registerRouteModules(options.routes, imports);
	const routeEntries = buildRouteEntries(options.routes, imports);
	const rootRoute = options.routes.find((r) => r.pattern === "/");
	const rootNotFoundVar = rootRoute?.notFoundPath ? imports.getImportVar(rootRoute.notFoundPath) : null;
	const rootForbiddenVar = rootRoute?.forbiddenPath ? imports.getImportVar(rootRoute.forbiddenPath) : null;
	const rootUnauthorizedVar = rootRoute?.unauthorizedPath ? imports.getImportVar(rootRoute.unauthorizedPath) : null;
	const rootLayoutVars = rootRoute ? rootRoute.layouts.map((l) => imports.getImportVar(l)) : [];
	const globalErrorVar = options.globalErrorPath ? imports.getImportVar(options.globalErrorPath) : null;
	const dynamicMetadataRoutes = metadataRoutes.filter((r) => r.isDynamic);
	for (const route of dynamicMetadataRoutes) imports.getImportVar(route.filePath);
	return {
		imports: imports.imports,
		routeEntries,
		metaRouteEntries: createMetadataRouteEntriesSource(metadataRoutes, imports.importMap),
		generateStaticParamsEntries: buildGenerateStaticParamsEntries(options.routes, imports),
		rootNotFoundVar,
		rootForbiddenVar,
		rootUnauthorizedVar,
		rootLayoutVars,
		globalErrorVar
	};
}
//#endregion
export { buildAppRscManifestCode };

//# sourceMappingURL=app-rsc-manifest.js.map