import { markDynamicUsage } from "../shims/headers.js";
import { APP_RSC_RENDER_MODE_NAVIGATION } from "./app-rsc-render-mode.js";
import { AppElementsWire } from "./app-elements-wire.js";
import "./app-elements.js";
import { matchRoutePattern } from "../routing/route-pattern.js";
import { makeThenableParams } from "../shims/thenable-params.js";
import { buildAppPageElements, createAppPageTreePath } from "./app-page-route-wiring.js";
import { resolveActiveParallelRouteHeadInputs, resolveAppPageHead } from "./app-page-head.js";
import { createElement } from "react";
//#region src/server/app-page-element-builder.ts
/**
* Build the App Router element tree for a matched route.
*
* This is the central element-construction path for the App Router RSC
* handler. It resolves page head metadata (including parallel route metadata),
* creates the page React element, and wires it into the nested layout +
* boundary tree via {@link buildAppPageElements}.
*
* The function is extracted from the generated RSC entry template so it can
* be unit-tested independently of the code-generation machinery.
*
* Next.js equivalent: the component tree construction in
* {@link https://github.com/vercel/next.js/blob/canary/packages/next/src/server/app-render/create-component-tree.tsx|create-component-tree.tsx}
* and the page head resolution in
* {@link https://github.com/vercel/next.js/blob/canary/packages/next/src/server/app-render/create-metadata.tsx|create-metadata.tsx}.
*/
async function buildPageElements(options) {
	const { route, params, routePath, pageRequest, globalErrorModule, rootNotFoundModule, rootForbiddenModule, rootUnauthorizedModule, metadataRoutes } = options;
	const { opts, searchParams, isRscRequest, mountedSlotsHeader, renderMode = APP_RSC_RENDER_MODE_NAVIGATION } = pageRequest;
	const pageModule = route.page;
	const PageComponent = pageModule?.default;
	if (!!pageModule && !PageComponent) {
		const interceptionContext = opts?.interceptionContext ?? null;
		const noExportRouteId = AppElementsWire.encodeRouteId(routePath, interceptionContext);
		let noExportRootLayout = null;
		const noExportLayoutIds = route.ids?.layouts ?? route.layouts.map((_, index) => AppElementsWire.encodeLayoutId(createAppPageTreePath(route.routeSegments, route.layoutTreePositions?.[index] ?? 0)));
		if (route.layouts?.length > 0) {
			const treePosition = route.layoutTreePositions?.[0] ?? 0;
			noExportRootLayout = createAppPageTreePath(route.routeSegments, treePosition);
		}
		return {
			...AppElementsWire.createMetadataEntries({
				interceptionContext,
				layoutIds: noExportLayoutIds,
				rootLayoutTreePath: noExportRootLayout,
				routeId: noExportRouteId
			}),
			[noExportRouteId]: createElement("div", null, "Page has no default export")
		};
	}
	const { hasSearchParams, metadata: resolvedMetadata, pageSearchParams, viewport: resolvedViewport } = await resolveAppPageHead({
		layoutModules: route.layouts,
		layoutTreePositions: route.layoutTreePositions,
		metadataRoutes,
		pageModule: route.page ?? null,
		parallelRoutes: resolveActiveParallelRouteHeadInputs({
			interceptLayouts: opts?.interceptLayouts ?? null,
			interceptPage: opts?.interceptPage ?? null,
			interceptParams: opts?.interceptParams ?? null,
			interceptSlotKey: opts?.interceptSlotKey ?? null,
			params,
			routeSegments: route.routeSegments ?? [],
			slots: route.slots ?? null
		}),
		params,
		routePath: route.pattern,
		routeSegments: route.routeSegments ?? null,
		searchParams
	});
	const pageProps = { params: makeThenableParams(params) };
	if (searchParams) {
		pageProps.searchParams = makeThenableParams(pageSearchParams);
		if (hasSearchParams) markDynamicUsage();
	}
	const mountedSlotIds = mountedSlotsHeader ? new Set(mountedSlotsHeader.split(" ")) : null;
	const slotOverrides = buildSlotOverrides(route, params, routePath, opts);
	return buildAppPageElements({
		element: PageComponent ? createElement(PageComponent, pageProps) : null,
		globalErrorModule: globalErrorModule ?? null,
		isRscRequest,
		mountedSlotIds,
		makeThenableParams,
		matchedParams: params,
		resolvedMetadata,
		resolvedViewport,
		interceptionContext: opts?.interceptionContext ?? null,
		routePath,
		rootNotFoundModule: rootNotFoundModule ?? null,
		rootForbiddenModule: rootForbiddenModule ?? null,
		rootUnauthorizedModule: rootUnauthorizedModule ?? null,
		route,
		slotOverrides,
		renderMode
	});
}
/**
* Build the per-request `slotOverrides` map. Combines:
*  - Interception overrides (existing behavior — swap in the intercepting page
*    and its layouts when the request is intercepted into this slot).
*  - Slot-specific param extraction for inherited slots whose URL pattern
*    has different param names than the route's. The runtime matches the
*    cleaned request path against `slot.slotPatternParts` to produce
*    slot-scoped params, which `app-page-route-wiring` then hands to the
*    slot page instead of the route's matched params.
*
* `routePath` is the already-normalized request pathname (basePath stripped,
* RSC suffix removed). Re-parsing `request.url` here would re-introduce the
* basePath and silently break the match for any app that configures one.
*/
function buildSlotOverrides(route, routeParams, routePath, opts) {
	const overrides = {};
	if (opts && opts.interceptSlotKey && opts.interceptPage) overrides[opts.interceptSlotKey] = {
		layoutModules: opts.interceptLayouts || null,
		pageModule: opts.interceptPage,
		params: opts.interceptParams || routeParams
	};
	const slots = route.slots;
	if (slots) {
		let urlParts = null;
		const routeParamSet = collectParamNameSet(route.params);
		for (const [slotKey, slot] of Object.entries(slots)) {
			const patternParts = slot.slotPatternParts;
			const paramNames = slot.slotParamNames;
			if (!patternParts || patternParts.length === 0) continue;
			if (paramNames && paramNames.every((name) => routeParamSet.has(name))) continue;
			if (urlParts === null) urlParts = routePath.split("/").filter(Boolean);
			const matched = matchRoutePattern(urlParts, patternParts);
			if (!matched) continue;
			const existing = overrides[slotKey];
			overrides[slotKey] = existing ? {
				...existing,
				params: matched
			} : { params: matched };
		}
	}
	return Object.keys(overrides).length > 0 ? overrides : null;
}
function collectParamNameSet(params) {
	const set = /* @__PURE__ */ new Set();
	if (params) for (const name of params) set.add(name);
	return set;
}
//#endregion
export { buildPageElements };

//# sourceMappingURL=app-page-element-builder.js.map