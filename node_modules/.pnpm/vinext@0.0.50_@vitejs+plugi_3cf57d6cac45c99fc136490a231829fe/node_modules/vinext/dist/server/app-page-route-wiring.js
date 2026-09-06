import { shouldSuppressLoadingBoundaries } from "./app-rsc-render-mode.js";
import { AppElementsWire } from "./app-elements-wire.js";
import "./app-elements.js";
import { ErrorBoundary, ForbiddenBoundary, NotFoundBoundary, RedirectBoundary, UnauthorizedBoundary } from "../shims/error-boundary.js";
import { LayoutSegmentProvider } from "../shims/layout-segment-context.js";
import { MetadataHead, ViewportHead } from "../shims/metadata.js";
import { Children as Children$1, ParallelSlot, Slot } from "../shims/slot.js";
import { createAppRenderDependency, renderAfterAppDependencies, renderWithAppDependencyBarrier } from "./app-render-dependency.js";
import { resolveAppPageSegmentParams } from "./app-page-params.js";
import { resolveAppPageChildSegments, resolveAppPageRouteStateKey, resolveAppPageSegmentStateKey } from "./app-page-segment-state.js";
import { Suspense } from "react";
import { Fragment as Fragment$1, jsx, jsxs } from "react/jsx-runtime";
//#region src/server/app-page-route-wiring.tsx
function getDefaultExport(module) {
	return module?.default ?? null;
}
function getErrorBoundaryExport(module) {
	return module?.default ?? null;
}
function createAppPageTreePath(routeSegments, treePosition) {
	const treePathSegments = routeSegments?.slice(0, treePosition) ?? [];
	if (treePathSegments.length === 0) return "/";
	return `/${treePathSegments.join("/")}`;
}
function createAppPageLayoutEntries(route) {
	return route.layouts.map((layoutModule, index) => {
		const treePosition = route.layoutTreePositions?.[index] ?? 0;
		const treePath = createAppPageTreePath(route.routeSegments, treePosition);
		return {
			errorModule: route.errorTreePositions ? null : route.errors?.[index] ?? null,
			forbiddenModule: route.forbiddens?.[index] ?? null,
			id: AppElementsWire.encodeLayoutId(treePath),
			layoutModule,
			notFoundModule: route.notFounds?.[index] ?? null,
			unauthorizedModule: route.unauthorizeds?.[index] ?? null,
			treePath,
			treePosition
		};
	});
}
function createAppPageTemplateEntries(route) {
	return (route.templates ?? []).map((templateModule, index) => {
		const treePosition = route.templateTreePositions?.[index] ?? 0;
		const treePath = createAppPageTreePath(route.routeSegments, treePosition);
		return {
			id: AppElementsWire.encodeTemplateId(treePath),
			templateModule,
			treePath,
			treePosition
		};
	});
}
function createAppPageErrorEntries(route) {
	return (route.errorPaths ?? route.errors ?? []).flatMap((errorModule, index) => {
		if (!errorModule) return [];
		const treePosition = route.errorTreePositions?.[index];
		if (treePosition === void 0) return [];
		return [{
			errorModule,
			treePosition
		}];
	});
}
function createAppPageParallelSlotEntries(layoutIndex, layoutEntries, route, getEffectiveSlotParams) {
	const parallelSlots = {};
	for (const [slotKey, slot] of Object.entries(route.slots ?? {})) {
		const slotName = slot.name;
		const targetIndex = slot.layoutIndex >= 0 ? slot.layoutIndex : layoutEntries.length - 1;
		if (targetIndex !== layoutIndex) continue;
		const treePath = layoutEntries[targetIndex]?.treePath ?? "/";
		const slotParams = getEffectiveSlotParams(slotKey, slotName);
		parallelSlots[slotName] = /* @__PURE__ */ jsx(LayoutSegmentProvider, {
			segmentMap: { children: slot.routeSegments ? resolveAppPageChildSegments(slot.routeSegments, 0, slotParams) : [] },
			children: /* @__PURE__ */ jsx(Slot, { id: AppElementsWire.encodeSlotId(slotName, treePath) })
		});
	}
	return Object.keys(parallelSlots).length > 0 ? parallelSlots : void 0;
}
function createAppPageRouteHead(metadata, viewport) {
	return /* @__PURE__ */ jsxs(Fragment$1, { children: [
		/* @__PURE__ */ jsx("meta", { charSet: "utf-8" }),
		metadata ? /* @__PURE__ */ jsx(MetadataHead, { metadata }) : null,
		/* @__PURE__ */ jsx(ViewportHead, { viewport })
	] });
}
function buildAppPageElements(options) {
	const interceptionContext = options.interceptionContext ?? null;
	const routeSegments = options.route.routeSegments ?? [];
	const routeResetKey = resolveAppPageRouteStateKey(routeSegments, options.matchedParams);
	const routeId = AppElementsWire.encodeRouteId(options.routePath, interceptionContext);
	const pageId = AppElementsWire.encodePageId(options.routePath, interceptionContext);
	const layoutEntries = createAppPageLayoutEntries(options.route);
	const templateEntries = createAppPageTemplateEntries(options.route);
	const errorEntries = createAppPageErrorEntries(options.route);
	const layoutEntriesByTreePosition = /* @__PURE__ */ new Map();
	const templateEntriesByTreePosition = /* @__PURE__ */ new Map();
	const errorEntriesByTreePosition = /* @__PURE__ */ new Map();
	for (const layoutEntry of layoutEntries) layoutEntriesByTreePosition.set(layoutEntry.treePosition, layoutEntry);
	for (const templateEntry of templateEntries) templateEntriesByTreePosition.set(templateEntry.treePosition, templateEntry);
	for (const errorEntry of errorEntries) errorEntriesByTreePosition.set(errorEntry.treePosition, errorEntry);
	const layoutIndicesByTreePosition = /* @__PURE__ */ new Map();
	for (let index = 0; index < layoutEntries.length; index++) layoutIndicesByTreePosition.set(layoutEntries[index].treePosition, index);
	const layoutDependenciesByIndex = /* @__PURE__ */ new Map();
	const layoutDependenciesBefore = [];
	const slotDependenciesByLayoutIndex = [];
	const templateDependenciesById = /* @__PURE__ */ new Map();
	const templateDependenciesBeforeById = /* @__PURE__ */ new Map();
	const pageDependencies = [];
	const rootLayoutTreePath = layoutEntries[0]?.treePath ?? null;
	const elements = { ...AppElementsWire.createMetadataEntries({
		interceptionContext,
		layoutIds: options.route.ids?.layouts ?? layoutEntries.map((entry) => entry.id),
		rootLayoutTreePath,
		routeId
	}) };
	const slotNameCounts = /* @__PURE__ */ new Map();
	for (const slot of Object.values(options.route.slots ?? {})) {
		const slotName = slot.name;
		slotNameCounts.set(slotName, (slotNameCounts.get(slotName) ?? 0) + 1);
	}
	const orderedTreePositions = Array.from(new Set([
		...layoutEntries.map((entry) => entry.treePosition),
		...templateEntries.map((entry) => entry.treePosition),
		...errorEntries.map((entry) => entry.treePosition)
	])).sort((left, right) => left - right);
	const resolveSlotOverride = (slotKey, slotName) => {
		const overrideByKey = options.slotOverrides?.[slotKey];
		if (overrideByKey) return overrideByKey;
		if (slotKey === slotName || (slotNameCounts.get(slotName) ?? 0) === 1) return options.slotOverrides?.[slotName];
	};
	const getEffectiveSlotParams = (slotKey, slotName) => resolveSlotOverride(slotKey, slotName)?.params ?? options.matchedParams;
	for (const treePosition of orderedTreePositions) {
		const layoutIndex = layoutIndicesByTreePosition.get(treePosition);
		if (layoutIndex !== void 0) {
			const layoutEntry = layoutEntries[layoutIndex];
			layoutDependenciesBefore[layoutIndex] = [...pageDependencies];
			if (getDefaultExport(layoutEntry.layoutModule)) {
				const layoutDependency = createAppRenderDependency();
				layoutDependenciesByIndex.set(layoutIndex, layoutDependency);
				pageDependencies.push(layoutDependency);
			}
			slotDependenciesByLayoutIndex[layoutIndex] = [...pageDependencies];
		}
		const templateEntry = templateEntriesByTreePosition.get(treePosition);
		if (!templateEntry || !getDefaultExport(templateEntry.templateModule)) continue;
		const templateDependency = createAppRenderDependency();
		templateDependenciesById.set(templateEntry.id, templateDependency);
		templateDependenciesBeforeById.set(templateEntry.id, [...pageDependencies]);
		pageDependencies.push(templateDependency);
	}
	elements[pageId] = renderAfterAppDependencies(options.element, pageDependencies);
	for (const templateEntry of templateEntries) {
		const templateComponent = getDefaultExport(templateEntry.templateModule);
		if (!templateComponent) continue;
		const TemplateComponent = templateComponent;
		const templateDependency = templateDependenciesById.get(templateEntry.id);
		const templateElement = templateDependency ? renderWithAppDependencyBarrier(/* @__PURE__ */ jsx(TemplateComponent, {
			params: options.matchedParams,
			children: /* @__PURE__ */ jsx(Children$1, {})
		}), templateDependency) : /* @__PURE__ */ jsx(TemplateComponent, {
			params: options.matchedParams,
			children: /* @__PURE__ */ jsx(Children$1, {})
		});
		elements[templateEntry.id] = renderAfterAppDependencies(templateElement, templateDependenciesBeforeById.get(templateEntry.id) ?? []);
	}
	for (let index = 0; index < layoutEntries.length; index++) {
		const layoutEntry = layoutEntries[index];
		const layoutComponent = getDefaultExport(layoutEntry.layoutModule);
		if (!layoutComponent) continue;
		const layoutProps = { params: options.makeThenableParams(resolveAppPageSegmentParams(options.route.routeSegments, layoutEntry.treePosition, options.matchedParams)) };
		for (const slot of Object.values(options.route.slots ?? {})) {
			const slotName = slot.name;
			if ((slot.layoutIndex >= 0 ? slot.layoutIndex : layoutEntries.length - 1) !== index) continue;
			layoutProps[slotName] = /* @__PURE__ */ jsx(ParallelSlot, { name: slotName });
		}
		const LayoutComponent = layoutComponent;
		const layoutDependency = layoutDependenciesByIndex.get(index);
		const layoutElement = layoutDependency ? renderWithAppDependencyBarrier(/* @__PURE__ */ jsx(LayoutComponent, {
			...layoutProps,
			children: /* @__PURE__ */ jsx(Children$1, {})
		}), layoutDependency) : /* @__PURE__ */ jsx(LayoutComponent, {
			...layoutProps,
			children: /* @__PURE__ */ jsx(Children$1, {})
		});
		elements[layoutEntry.id] = renderAfterAppDependencies(layoutElement, layoutDependenciesBefore[index] ?? []);
	}
	for (const [slotKey, slot] of Object.entries(options.route.slots ?? {})) {
		const slotName = slot.name;
		const targetIndex = slot.layoutIndex >= 0 ? slot.layoutIndex : layoutEntries.length - 1;
		const treePath = layoutEntries[targetIndex]?.treePath ?? "/";
		const slotId = AppElementsWire.encodeSlotId(slotName, treePath);
		const slotOverride = resolveSlotOverride(slotKey, slotName);
		const slotParams = getEffectiveSlotParams(slotKey, slotName);
		const slotResetKey = resolveAppPageRouteStateKey(slot.routeSegments ?? [], slotParams);
		const overrideOrPageComponent = getDefaultExport(slotOverride?.pageModule) ?? getDefaultExport(slot.page);
		const defaultComponent = getDefaultExport(slot.default);
		if (!overrideOrPageComponent && defaultComponent && options.isRscRequest && options.mountedSlotIds?.has(slotId)) continue;
		const slotComponent = overrideOrPageComponent ?? defaultComponent;
		if (!slotComponent) {
			elements[slotId] = AppElementsWire.unmatchedSlotValue;
			continue;
		}
		const slotThenableParams = options.makeThenableParams(slotParams);
		const slotProps = { params: slotThenableParams };
		if (slotOverride?.props) Object.assign(slotProps, slotOverride.props);
		let slotElement = /* @__PURE__ */ jsx(slotComponent, { ...slotProps });
		const interceptLayouts = slotOverride?.layoutModules ?? [];
		for (let layoutIndex = interceptLayouts.length - 1; layoutIndex >= 0; layoutIndex--) {
			const interceptLayoutComponent = getDefaultExport(interceptLayouts[layoutIndex]);
			if (!interceptLayoutComponent) continue;
			slotElement = /* @__PURE__ */ jsx(interceptLayoutComponent, {
				params: slotThenableParams,
				children: slotElement
			});
		}
		const slotLayoutComponent = getDefaultExport(slot.layout);
		if (slotLayoutComponent) slotElement = /* @__PURE__ */ jsx(slotLayoutComponent, {
			params: slotThenableParams,
			children: slotElement
		});
		const slotLoadingComponent = getDefaultExport(slot.loading);
		if (slotLoadingComponent && !shouldSuppressLoadingBoundaries(options.renderMode ?? "navigation")) slotElement = /* @__PURE__ */ jsx(Suspense, {
			fallback: /* @__PURE__ */ jsx(slotLoadingComponent, {}),
			children: slotElement
		}, slotResetKey);
		const slotErrorComponent = getErrorBoundaryExport(slot.error);
		if (slotErrorComponent) slotElement = /* @__PURE__ */ jsx(ErrorBoundary, {
			resetKey: slotResetKey,
			fallback: slotErrorComponent,
			children: slotElement
		});
		elements[slotId] = renderAfterAppDependencies(slotElement, targetIndex >= 0 ? slotDependenciesByLayoutIndex[targetIndex] ?? [] : []);
	}
	let routeChildren = /* @__PURE__ */ jsx(LayoutSegmentProvider, {
		segmentMap: { children: [] },
		children: /* @__PURE__ */ jsx(Slot, { id: pageId })
	});
	routeChildren = /* @__PURE__ */ jsx(RedirectBoundary, { children: routeChildren });
	const routeLoadingComponent = getDefaultExport(options.route.loading);
	if (routeLoadingComponent && !shouldSuppressLoadingBoundaries(options.renderMode ?? "navigation")) routeChildren = /* @__PURE__ */ jsx(Suspense, {
		fallback: /* @__PURE__ */ jsx(routeLoadingComponent, {}),
		children: routeChildren
	}, routeResetKey);
	const lastLayoutErrorModule = errorEntries.length > 0 ? errorEntries[errorEntries.length - 1].errorModule : null;
	const notFoundComponent = getDefaultExport(options.route.notFound) ?? getDefaultExport(options.rootNotFoundModule);
	if (notFoundComponent) routeChildren = /* @__PURE__ */ jsx(NotFoundBoundary, {
		resetKey: routeResetKey,
		fallback: /* @__PURE__ */ jsx(notFoundComponent, {}),
		children: routeChildren
	});
	const forbiddenComponent = getDefaultExport(options.route.forbidden) ?? getDefaultExport(options.rootForbiddenModule);
	if (forbiddenComponent) routeChildren = /* @__PURE__ */ jsx(ForbiddenBoundary, {
		resetKey: routeResetKey,
		fallback: /* @__PURE__ */ jsx(forbiddenComponent, {}),
		children: routeChildren
	});
	const unauthorizedComponent = getDefaultExport(options.route.unauthorized) ?? getDefaultExport(options.rootUnauthorizedModule);
	if (unauthorizedComponent) routeChildren = /* @__PURE__ */ jsx(UnauthorizedBoundary, {
		resetKey: routeResetKey,
		fallback: /* @__PURE__ */ jsx(unauthorizedComponent, {}),
		children: routeChildren
	});
	const pageErrorComponent = getErrorBoundaryExport(options.route.error);
	if (pageErrorComponent && options.route.error !== lastLayoutErrorModule) routeChildren = /* @__PURE__ */ jsx(ErrorBoundary, {
		resetKey: routeResetKey,
		fallback: pageErrorComponent,
		children: routeChildren
	});
	for (let index = orderedTreePositions.length - 1; index >= 0; index--) {
		const treePosition = orderedTreePositions[index];
		const segmentResetKey = resolveAppPageSegmentStateKey(routeSegments, treePosition, options.matchedParams);
		let segmentChildren = routeChildren;
		const layoutEntry = layoutEntriesByTreePosition.get(treePosition);
		const templateEntry = templateEntriesByTreePosition.get(treePosition);
		const errorEntry = errorEntriesByTreePosition.get(treePosition);
		if (layoutEntry) {
			const layoutNotFoundComponent = getDefaultExport(layoutEntry.notFoundModule);
			if (layoutNotFoundComponent) segmentChildren = /* @__PURE__ */ jsx(NotFoundBoundary, {
				resetKey: segmentResetKey,
				fallback: /* @__PURE__ */ jsx(layoutNotFoundComponent, {}),
				children: segmentChildren
			});
			const layoutForbiddenComponent = getDefaultExport(layoutEntry.forbiddenModule);
			if (layoutForbiddenComponent) segmentChildren = /* @__PURE__ */ jsx(ForbiddenBoundary, {
				resetKey: segmentResetKey,
				fallback: /* @__PURE__ */ jsx(layoutForbiddenComponent, {}),
				children: segmentChildren
			});
			const layoutUnauthorizedComponent = getDefaultExport(layoutEntry.unauthorizedModule);
			if (layoutUnauthorizedComponent) segmentChildren = /* @__PURE__ */ jsx(UnauthorizedBoundary, {
				resetKey: segmentResetKey,
				fallback: /* @__PURE__ */ jsx(layoutUnauthorizedComponent, {}),
				children: segmentChildren
			});
		}
		const segmentErrorComponent = getErrorBoundaryExport(errorEntry?.errorModule ?? layoutEntry?.errorModule);
		if (segmentErrorComponent) segmentChildren = /* @__PURE__ */ jsx(ErrorBoundary, {
			resetKey: segmentResetKey,
			fallback: segmentErrorComponent,
			children: segmentChildren
		});
		if (templateEntry && getDefaultExport(templateEntry.templateModule)) segmentChildren = /* @__PURE__ */ jsx(Slot, {
			id: templateEntry.id,
			children: segmentChildren
		}, segmentResetKey);
		if (!layoutEntry) {
			routeChildren = segmentChildren;
			continue;
		}
		const layoutHasElement = getDefaultExport(layoutEntry.layoutModule) !== null;
		const layoutIndex = layoutIndicesByTreePosition.get(treePosition) ?? -1;
		const segmentMap = { children: resolveAppPageChildSegments(routeSegments, layoutEntry.treePosition, options.matchedParams) };
		for (const [slotKey, slot] of Object.entries(options.route.slots ?? {})) {
			const slotName = slot.name;
			if ((slot.layoutIndex >= 0 ? slot.layoutIndex : layoutEntries.length - 1) !== layoutIndex) continue;
			const slotParams = getEffectiveSlotParams(slotKey, slotName);
			segmentMap[slotName] = slot.routeSegments ? resolveAppPageChildSegments(slot.routeSegments, 0, slotParams) : [];
		}
		routeChildren = /* @__PURE__ */ jsx(LayoutSegmentProvider, {
			segmentMap,
			children: layoutHasElement ? /* @__PURE__ */ jsx(Slot, {
				id: layoutEntry.id,
				parallelSlots: createAppPageParallelSlotEntries(layoutIndex, layoutEntries, options.route, getEffectiveSlotParams),
				children: segmentChildren
			}) : segmentChildren
		});
	}
	const globalErrorComponent = getErrorBoundaryExport(options.globalErrorModule);
	if (globalErrorComponent) routeChildren = /* @__PURE__ */ jsx(ErrorBoundary, {
		fallback: globalErrorComponent,
		children: routeChildren
	});
	elements[routeId] = /* @__PURE__ */ jsxs(Fragment$1, { children: [createAppPageRouteHead(options.resolvedMetadata, options.resolvedViewport), routeChildren] });
	return elements;
}
//#endregion
export { buildAppPageElements, createAppPageLayoutEntries, createAppPageTreePath, resolveAppPageChildSegments };

//# sourceMappingURL=app-page-route-wiring.js.map