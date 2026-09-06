import { ACTION_REDIRECT_HEADER, VINEXT_MOUNTED_SLOTS_HEADER, VINEXT_PARAMS_HEADER } from "./headers.js";
import { DANGEROUS_URL_BLOCK_MESSAGE, isDangerousScheme } from "../shims/url-safety.js";
import { APP_RSC_RENDER_MODE_REFRESH_PRESERVE_UI } from "./app-rsc-render-mode.js";
import { installWindowNext } from "../client/window-next.js";
import { notifyAppRouterTransitionStart } from "../client/instrumentation-client-state.js";
import { AppElementsWire } from "./app-elements-wire.js";
import { getMountedSlotIdsHeader, resolveVisitedResponseInterceptionContext } from "./app-elements.js";
import { createRscRequestHeaders, createRscRequestUrl, stripRscCacheBustingSearchParam, stripRscSuffix } from "./app-rsc-cache-busting.js";
import { __basePath, appRouterInstance, commitClientNavigationState, consumePrefetchResponse, createClientNavigationRenderSnapshot, getClientNavigationRenderContext, getCurrentInterceptionContext, getCurrentNextUrl, getPrefetchCache, getPrefetchedUrls, pushHistoryStateWithoutNotify, replaceClientParamsWithoutNotify, replaceHistoryStateWithoutNotify, restoreRscResponse, setClientParams, setMountedSlotsHeader, setNavigationContext, setPendingPathname } from "../shims/navigation.js";
import { DevRecoveryBoundary, RedirectBoundary } from "../shims/error-boundary.js";
import { ElementsContext, Slot } from "../shims/slot.js";
import "../client/instrumentation-client.js";
import { isServerActionResult, shouldClearClientNavigationCachesForServerActionResult } from "./app-browser-action-result.js";
import { chunksToReadableStream, createProgressiveRscStream, getVinextBrowserGlobal } from "./app-browser-stream.js";
import { createHistoryStateWithPreviousNextUrl, readHistoryStatePreviousNextUrl, resolveInterceptionContextFromPreviousNextUrl, resolveServerActionRequestState } from "./app-browser-state.js";
import { clearHardNavigationLoopGuard, createAppBrowserNavigationController } from "./app-browser-navigation-controller.js";
import { consumeInitialFormState, createVinextHydrateRootOptions } from "./app-browser-hydration.js";
import { createOnUncaughtError } from "./app-browser-error.js";
import { dismissOverlay } from "./dev-error-overlay-store.js";
import { devOnCaughtError, devOnUncaughtError, installDevErrorOverlay } from "./dev-error-overlay.js";
import { getServerActionNotFoundClientMessage, isServerActionNotFoundResponse } from "./server-action-not-found.js";
import { createElement, use, useLayoutEffect, useRef, useState } from "react";
import { createFromFetch, createFromReadableStream, createTemporaryReferenceSet, encodeReply, setServerCallback } from "@vitejs/plugin-rsc/browser";
import { hydrateRoot } from "react-dom/client";
//#region src/server/app-browser-entry.ts
function toActionType(kind) {
	return kind === "traverse" ? "traverse" : "navigate";
}
function toOperationLane(kind) {
	switch (kind) {
		case "navigate": return "navigation";
		case "refresh": return "refresh";
		case "traverse": return "traverse";
		default: throw new Error("[vinext] Unknown navigation kind: " + String(kind));
	}
}
const MAX_VISITED_RESPONSE_CACHE_SIZE = 50;
const VISITED_RESPONSE_CACHE_TTL = 5 * 6e4;
const MAX_TRAVERSAL_CACHE_TTL = 30 * 6e4;
const browserNavigationController = createAppBrowserNavigationController();
const NavigationCommitSignal = browserNavigationController.NavigationCommitSignal;
function parseEncodedJsonHeader(value) {
	if (!value) return null;
	try {
		return JSON.parse(decodeURIComponent(value));
	} catch {
		return null;
	}
}
function isRouterStatePromise(value) {
	return value instanceof Promise;
}
let latestClientParams = {};
const visitedResponseCache = /* @__PURE__ */ new Map();
let browserRouterStateHasEverCommitted = false;
let pendingNavigationRecoveryHref = null;
function getBrowserRouterState() {
	return browserNavigationController.getBrowserRouterState();
}
function hasBrowserRouterState() {
	return browserNavigationController.hasBrowserRouterState();
}
function waitForBrowserRouterStateReady() {
	return browserNavigationController.waitForBrowserRouterStateReady();
}
function beginPendingBrowserRouterState() {
	return browserNavigationController.beginPendingBrowserRouterState();
}
function applyClientParams(params) {
	latestClientParams = params;
	setClientParams(params);
}
function stageClientParams(params) {
	latestClientParams = params;
	replaceClientParamsWithoutNotify(params);
}
function clearVisitedResponseCache() {
	visitedResponseCache.clear();
}
function clearPrefetchState() {
	getPrefetchCache().clear();
	getPrefetchedUrls().clear();
}
function clearClientNavigationCaches() {
	clearVisitedResponseCache();
	clearPrefetchState();
}
function createNavigationCommitEffect(options) {
	const { href, historyUpdateMode, navId, params, previousNextUrl } = options;
	return () => {
		if (!browserNavigationController.isCurrentNavigation(navId)) {
			commitClientNavigationState(void 0, { releaseSnapshot: true });
			return;
		}
		const targetHref = new URL(href, window.location.origin).href;
		stageClientParams(params);
		const historyState = createHistoryStateWithPreviousNextUrl(historyUpdateMode === "replace" ? window.history.state : null, previousNextUrl);
		if (historyUpdateMode === "replace" && window.location.href !== targetHref) replaceHistoryStateWithoutNotify(historyState, "", href);
		else if (historyUpdateMode === "push" && window.location.href !== targetHref) pushHistoryStateWithoutNotify(historyState, "", href);
		pendingNavigationRecoveryHref = null;
		commitClientNavigationState(navId);
	};
}
async function renderNavigationPayload(payload, navigationSnapshot, targetHref, navId, historyUpdateMode, params, previousNextUrl, pendingRouterState, actionType = "navigate", operationLane = "navigation") {
	try {
		return await browserNavigationController.renderNavigationPayload({
			actionType,
			createNavigationCommitEffect: (options) => {
				pendingNavigationRecoveryHref = options.href;
				return createNavigationCommitEffect(options);
			},
			historyUpdateMode,
			navigationSnapshot,
			nextElements: payload,
			operationLane,
			params,
			pendingRouterState,
			previousNextUrl,
			targetHref,
			navId
		});
	} catch (error) {
		pendingNavigationRecoveryHref = null;
		throw error;
	}
}
async function commitSameUrlNavigatePayload(nextElements, returnValue, actionInitiationState) {
	const navigationSnapshot = createClientNavigationRenderSnapshot(window.location.href, latestClientParams);
	return browserNavigationController.commitSameUrlNavigatePayload(nextElements, navigationSnapshot, returnValue, actionInitiationState);
}
function evictVisitedResponseCacheIfNeeded() {
	while (visitedResponseCache.size >= MAX_VISITED_RESPONSE_CACHE_SIZE) {
		const oldest = visitedResponseCache.keys().next().value;
		if (oldest === void 0) return;
		visitedResponseCache.delete(oldest);
	}
}
function getVisitedResponse(rscUrl, interceptionContext, mountedSlotsHeader, navigationKind) {
	const cacheKey = AppElementsWire.encodeCacheKey(rscUrl, interceptionContext);
	const cached = visitedResponseCache.get(cacheKey);
	if (!cached) return null;
	if ((cached.response.mountedSlotsHeader ?? null) !== mountedSlotsHeader) {
		visitedResponseCache.delete(cacheKey);
		return null;
	}
	if (navigationKind === "refresh") return null;
	if (navigationKind === "traverse") {
		const createdAt = cached.expiresAt - VISITED_RESPONSE_CACHE_TTL;
		if (Date.now() - createdAt >= MAX_TRAVERSAL_CACHE_TTL) {
			visitedResponseCache.delete(cacheKey);
			return null;
		}
		visitedResponseCache.delete(cacheKey);
		visitedResponseCache.set(cacheKey, cached);
		return cached;
	}
	if (cached.expiresAt > Date.now()) {
		visitedResponseCache.delete(cacheKey);
		visitedResponseCache.set(cacheKey, cached);
		return cached;
	}
	visitedResponseCache.delete(cacheKey);
	return null;
}
function storeVisitedResponseSnapshot(rscUrl, interceptionContext, snapshot, params) {
	const cacheKey = AppElementsWire.encodeCacheKey(rscUrl, interceptionContext);
	visitedResponseCache.delete(cacheKey);
	evictVisitedResponseCacheIfNeeded();
	const now = Date.now();
	visitedResponseCache.set(cacheKey, {
		params,
		expiresAt: now + VISITED_RESPONSE_CACHE_TTL,
		response: snapshot
	});
}
function getRequestState(navigationKind, previousNextUrlOverride) {
	if (previousNextUrlOverride !== void 0) return {
		interceptionContext: resolveInterceptionContextFromPreviousNextUrl(previousNextUrlOverride, __basePath),
		previousNextUrl: previousNextUrlOverride
	};
	switch (navigationKind) {
		case "navigate": return {
			interceptionContext: getCurrentInterceptionContext(),
			previousNextUrl: getCurrentNextUrl()
		};
		case "traverse": {
			const previousNextUrl = readHistoryStatePreviousNextUrl(window.history.state);
			return {
				interceptionContext: resolveInterceptionContextFromPreviousNextUrl(previousNextUrl, __basePath),
				previousNextUrl
			};
		}
		case "refresh": {
			const currentPreviousNextUrl = getBrowserRouterState().previousNextUrl;
			return {
				interceptionContext: resolveInterceptionContextFromPreviousNextUrl(currentPreviousNextUrl, __basePath),
				previousNextUrl: currentPreviousNextUrl
			};
		}
		default: throw new Error("[vinext] Unknown navigation kind: " + String(navigationKind));
	}
}
function handleDevRecoveryBoundaryCatch(resetKey) {
	browserNavigationController.drainPrePaintEffects(resetKey);
}
function decodeAppElementsPromise(payload) {
	return Promise.resolve(payload).then((elements) => AppElementsWire.decode(elements));
}
function BrowserRoot({ initialElements, initialNavigationSnapshot }) {
	const resolvedElements = use(initialElements);
	const initialMetadata = AppElementsWire.readMetadata(resolvedElements);
	const [treeStateValue, setTreeStateValue] = useState({
		activeOperation: null,
		elements: resolvedElements,
		interceptionContext: initialMetadata.interceptionContext,
		layoutIds: initialMetadata.layoutIds,
		layoutFlags: initialMetadata.layoutFlags,
		navigationSnapshot: initialNavigationSnapshot,
		previousNextUrl: null,
		renderId: 0,
		rootLayoutTreePath: initialMetadata.rootLayoutTreePath,
		routeId: initialMetadata.routeId,
		visibleCommitVersion: 0
	});
	const treeState = isRouterStatePromise(treeStateValue) ? use(treeStateValue) : treeStateValue;
	const stateRef = useRef(treeState);
	stateRef.current = treeState;
	useLayoutEffect(() => {
		const detach = browserNavigationController.attachBrowserRouterState(setTreeStateValue, stateRef);
		browserRouterStateHasEverCommitted = true;
		return () => {
			detach();
			setMountedSlotsHeader(null);
		};
	}, [setTreeStateValue]);
	useLayoutEffect(() => {
		setMountedSlotsHeader(getMountedSlotIdsHeader(stateRef.current.elements));
	}, [treeState.elements]);
	useLayoutEffect(() => {
		if (treeState.renderId !== 0) return;
		replaceHistoryStateWithoutNotify(createHistoryStateWithPreviousNextUrl(window.history.state, treeState.previousNextUrl), "", window.location.href);
	}, [treeState.previousNextUrl, treeState.renderId]);
	const innerTree = createElement(RedirectBoundary, null, createElement(NavigationCommitSignal, { renderId: treeState.renderId }, createElement(ElementsContext.Provider, { value: treeState.elements }, createElement(Slot, { id: treeState.routeId }))));
	const committedTree = import.meta.env.DEV ? createElement(DevRecoveryBoundary, {
		resetKey: treeState.renderId,
		onCatch: handleDevRecoveryBoundaryCatch
	}, innerTree) : innerTree;
	const ClientNavigationRenderContext = getClientNavigationRenderContext();
	if (!ClientNavigationRenderContext) return committedTree;
	return createElement(ClientNavigationRenderContext.Provider, { value: treeState.navigationSnapshot }, committedTree);
}
function restoreHydrationNavigationContext(pathname, searchParams, params) {
	setNavigationContext({
		pathname,
		searchParams: new URLSearchParams(searchParams),
		params
	});
}
function decodeHashFragment(fragment) {
	try {
		return decodeURIComponent(fragment);
	} catch {
		return fragment;
	}
}
function scrollToHashTarget(hash) {
	const fragment = decodeHashFragment(hash.startsWith("#") ? hash.slice(1) : hash);
	requestAnimationFrame(() => {
		if (fragment === "" || fragment === "top") {
			window.scrollTo(0, 0);
			return;
		}
		const idElement = document.getElementById(fragment);
		if (idElement) {
			idElement.scrollIntoView({ behavior: "auto" });
			return;
		}
		document.getElementsByName(fragment)[0]?.scrollIntoView({ behavior: "auto" });
	});
}
function restorePopstateScrollPosition(state) {
	if (!(state && typeof state === "object" && "__vinext_scrollY" in state)) {
		if (window.location.hash) scrollToHashTarget(window.location.hash);
		return;
	}
	const y = Number(state.__vinext_scrollY);
	const x = "__vinext_scrollX" in state ? Number(state.__vinext_scrollX) : 0;
	requestAnimationFrame(() => {
		window.scrollTo(x, y);
	});
}
let isPageUnloading = false;
const RSC_RELOAD_KEY = "__vinext_rsc_initial_reload__";
function readReloadFlag() {
	try {
		return sessionStorage.getItem(RSC_RELOAD_KEY);
	} catch {
		return null;
	}
}
function writeReloadFlag(path) {
	try {
		sessionStorage.setItem(RSC_RELOAD_KEY, path);
	} catch {}
}
function clearReloadFlag() {
	try {
		sessionStorage.removeItem(RSC_RELOAD_KEY);
	} catch {}
}
function recoverFromBadInitialRscResponse(reason) {
	const currentPath = window.location.pathname + window.location.search;
	if (readReloadFlag() === currentPath) {
		clearReloadFlag();
		console.error(`[vinext] Initial RSC fetch ${reason} after reload; aborting hydration. Server-rendered HTML remains visible; client components will not hydrate.`);
		return null;
	}
	writeReloadFlag(currentPath);
	if (readReloadFlag() !== currentPath) {
		console.error(`[vinext] Initial RSC fetch ${reason}; sessionStorage unavailable so the reload-loop guard cannot persist — aborting hydration. Server-rendered HTML remains visible; client components will not hydrate.`);
		return null;
	}
	console.warn(`[vinext] Initial RSC fetch ${reason}; reloading once to let the server render the HTML error page`);
	window.location.reload();
	return null;
}
async function readInitialRscStream() {
	const vinext = getVinextBrowserGlobal();
	if (vinext.__VINEXT_RSC__ || vinext.__VINEXT_RSC_CHUNKS__ || vinext.__VINEXT_RSC_DONE__) {
		clearReloadFlag();
		clearHardNavigationLoopGuard();
		if (vinext.__VINEXT_RSC__) {
			const embedData = vinext.__VINEXT_RSC__;
			delete vinext.__VINEXT_RSC__;
			const params = embedData.params ?? {};
			if (embedData.params) applyClientParams(embedData.params);
			if (embedData.nav) restoreHydrationNavigationContext(embedData.nav.pathname, embedData.nav.searchParams, params);
			return chunksToReadableStream(embedData.rsc);
		}
		const params = vinext.__VINEXT_RSC_PARAMS__ ?? {};
		if (vinext.__VINEXT_RSC_PARAMS__) applyClientParams(vinext.__VINEXT_RSC_PARAMS__);
		if (vinext.__VINEXT_RSC_NAV__) restoreHydrationNavigationContext(vinext.__VINEXT_RSC_NAV__.pathname, vinext.__VINEXT_RSC_NAV__.searchParams, params);
		return createProgressiveRscStream();
	}
	const rscHeaders = createRscRequestHeaders();
	const rscResponse = await fetch(await createRscRequestUrl(window.location.pathname + window.location.search, rscHeaders), {
		credentials: "include",
		headers: rscHeaders
	});
	if (!rscResponse.ok) return recoverFromBadInitialRscResponse(`returned ${rscResponse.status}`);
	const contentType = rscResponse.headers.get("content-type") ?? "";
	if (!contentType.startsWith("text/x-component")) return recoverFromBadInitialRscResponse(`returned non-RSC content-type "${contentType || "(missing)"}"`);
	if (!rscResponse.body) return recoverFromBadInitialRscResponse("returned empty body");
	clearReloadFlag();
	clearHardNavigationLoopGuard();
	const parsedParams = parseEncodedJsonHeader(rscResponse.headers.get(VINEXT_PARAMS_HEADER));
	const params = parsedParams ?? {};
	if (parsedParams) try {
		applyClientParams(parsedParams);
	} catch {}
	restoreHydrationNavigationContext(window.location.pathname, window.location.search, params);
	return rscResponse.body;
}
function registerServerActionCallback() {
	setServerCallback(async (id, args) => {
		const temporaryReferences = createTemporaryReferenceSet();
		const body = await encodeReply(args, { temporaryReferences });
		const currentState = getBrowserRouterState();
		const { headers } = resolveServerActionRequestState({
			actionId: id,
			basePath: __basePath,
			elements: currentState.elements,
			previousNextUrl: currentState.previousNextUrl
		});
		const fetchResponse = await fetch(await createRscRequestUrl(window.location.pathname + window.location.search, headers), {
			method: "POST",
			headers,
			body
		});
		if (isServerActionNotFoundResponse(fetchResponse)) throw new Error(getServerActionNotFoundClientMessage(id));
		const actionRedirect = fetchResponse.headers.get(ACTION_REDIRECT_HEADER);
		if (actionRedirect) {
			if (isDangerousScheme(actionRedirect)) {
				console.error(DANGEROUS_URL_BLOCK_MESSAGE);
				return;
			}
			try {
				if (new URL(actionRedirect, window.location.origin).origin !== window.location.origin) {
					window.location.href = actionRedirect;
					return;
				}
			} catch {}
			clearClientNavigationCaches();
			if ((fetchResponse.headers.get("x-action-redirect-type") ?? "replace") === "push") window.location.assign(actionRedirect);
			else window.location.replace(actionRedirect);
			return;
		}
		const result = await createFromFetch(Promise.resolve(fetchResponse), { temporaryReferences });
		if (shouldClearClientNavigationCachesForServerActionResult(result)) clearClientNavigationCaches();
		if (isServerActionResult(result)) {
			if (result.root !== void 0) return commitSameUrlNavigatePayload(Promise.resolve(AppElementsWire.decode(result.root)), result.returnValue, currentState);
			if (result.returnValue) {
				if (!result.returnValue.ok) throw result.returnValue.data;
				return result.returnValue.data;
			}
			return;
		}
		return commitSameUrlNavigatePayload(Promise.resolve(AppElementsWire.decode(result)), void 0, currentState);
	});
}
async function main() {
	registerServerActionCallback();
	const rscStream = await readInitialRscStream();
	if (rscStream === null) return;
	bootstrapHydration(rscStream);
}
function bootstrapHydration(rscStream) {
	if (import.meta.env.DEV) installDevErrorOverlay();
	const root = decodeAppElementsPromise(createFromReadableStream(rscStream));
	const initialNavigationSnapshot = createClientNavigationRenderSnapshot(window.location.href, latestClientParams);
	replaceHistoryStateWithoutNotify(createHistoryStateWithPreviousNextUrl(window.history.state, null), "", window.location.href);
	const onUncaughtError = import.meta.env.DEV ? devOnUncaughtError : createOnUncaughtError(() => pendingNavigationRecoveryHref);
	const formState = consumeInitialFormState(getVinextBrowserGlobal());
	const hydrateRootOptions = import.meta.env.DEV ? createVinextHydrateRootOptions({
		formState,
		onCaughtError: devOnCaughtError,
		onUncaughtError
	}) : createVinextHydrateRootOptions({
		formState,
		onUncaughtError
	});
	window.__VINEXT_RSC_ROOT__ = hydrateRoot(document, createElement(BrowserRoot, {
		initialElements: root,
		initialNavigationSnapshot
	}), hydrateRootOptions);
	window.__VINEXT_HYDRATED_AT = performance.now();
	window.__VINEXT_CLEAR_NAV_CACHES__ = clearClientNavigationCaches;
	window.__VINEXT_RSC_NAVIGATE__ = async function navigateRsc(href, redirectDepth = 0, navigationKind = "navigate", historyUpdateMode, previousNextUrlOverride, programmaticTransition = false) {
		let pendingRouterState = null;
		const navId = browserNavigationController.beginNavigation();
		let currentHref = href;
		let currentHistoryMode = historyUpdateMode;
		let currentPrevNextUrl = previousNextUrlOverride;
		let redirectCount = redirectDepth;
		try {
			const shouldUsePendingRouterState = programmaticTransition && navigationKind !== "refresh";
			if (shouldUsePendingRouterState && hasBrowserRouterState()) pendingRouterState = beginPendingBrowserRouterState();
			else {
				await waitForBrowserRouterStateReady();
				if (!browserNavigationController.isCurrentNavigation(navId)) return;
				if (shouldUsePendingRouterState) pendingRouterState = beginPendingBrowserRouterState();
			}
			while (true) {
				if (redirectCount > 10) {
					console.error("[vinext] Too many RSC redirects — aborting navigation to prevent infinite loop.");
					window.location.href = currentHref;
					return;
				}
				const url = new URL(currentHref, window.location.origin);
				const requestState = getRequestState(navigationKind, currentPrevNextUrl);
				const requestInterceptionContext = requestState.interceptionContext;
				const requestPreviousNextUrl = requestState.previousNextUrl;
				setPendingPathname(url.pathname, navId);
				const elementsAtNavStart = getBrowserRouterState().elements;
				const mountedSlotsHeader = getMountedSlotIdsHeader(elementsAtNavStart);
				const requestHeaders = createRscRequestHeaders({
					interceptionContext: requestInterceptionContext,
					renderMode: navigationKind === "refresh" ? APP_RSC_RENDER_MODE_REFRESH_PRESERVE_UI : void 0
				});
				if (mountedSlotsHeader) requestHeaders.set(VINEXT_MOUNTED_SLOTS_HEADER, mountedSlotsHeader);
				const rscUrl = await createRscRequestUrl(url.pathname + url.search, requestHeaders);
				const cachedRoute = getVisitedResponse(rscUrl, requestInterceptionContext, mountedSlotsHeader, navigationKind);
				if (cachedRoute) {
					if (!browserNavigationController.isCurrentNavigation(navId)) return;
					const cachedParams = cachedRoute.params;
					const cachedNavigationSnapshot = createClientNavigationRenderSnapshot(currentHref, cachedParams);
					const cachedPayload = decodeAppElementsPromise(createFromFetch(Promise.resolve(restoreRscResponse(cachedRoute.response))));
					if (!browserNavigationController.isCurrentNavigation(navId)) return;
					await renderNavigationPayload(cachedPayload, cachedNavigationSnapshot, currentHref, navId, currentHistoryMode, cachedParams, requestPreviousNextUrl, pendingRouterState, toActionType(navigationKind), toOperationLane(navigationKind));
					return;
				}
				let navResponse;
				let navResponseUrl = null;
				if (navigationKind !== "refresh") {
					const prefetchedResponse = consumePrefetchResponse(rscUrl, requestInterceptionContext, mountedSlotsHeader);
					if (prefetchedResponse) {
						navResponse = restoreRscResponse(prefetchedResponse, false);
						navResponseUrl = prefetchedResponse.url;
					}
				}
				if (!navResponse) navResponse = await fetch(rscUrl, {
					headers: requestHeaders,
					credentials: "include"
				});
				if (!browserNavigationController.isCurrentNavigation(navId)) return;
				const isRscResponse = (navResponse.headers.get("content-type") ?? "").startsWith("text/x-component");
				if (!navResponse.ok || !isRscResponse || !navResponse.body) {
					const responseUrl = navResponseUrl ?? navResponse.url;
					let hardNavTarget = currentHref;
					if (responseUrl) {
						const parsed = new URL(responseUrl, window.location.origin);
						stripRscCacheBustingSearchParam(parsed);
						const origUrl = new URL(currentHref, window.location.origin);
						let pathname = stripRscSuffix(parsed.pathname);
						if (origUrl.pathname.length > 1 && origUrl.pathname.endsWith("/") && !pathname.endsWith("/")) pathname += "/";
						hardNavTarget = pathname + parsed.search;
						if (origUrl.hash) hardNavTarget += origUrl.hash;
					}
					window.location.href = hardNavTarget;
					return;
				}
				const finalUrl = new URL(navResponseUrl ?? navResponse.url, window.location.origin);
				stripRscCacheBustingSearchParam(finalUrl);
				const requestedUrl = new URL(rscUrl, window.location.origin);
				if (finalUrl.pathname !== requestedUrl.pathname) {
					const destinationPath = stripRscSuffix(finalUrl.pathname) + finalUrl.search;
					replaceHistoryStateWithoutNotify(createHistoryStateWithPreviousNextUrl(null, requestPreviousNextUrl), "", destinationPath);
					currentHref = destinationPath;
					currentHistoryMode = void 0;
					currentPrevNextUrl = requestPreviousNextUrl;
					redirectCount += 1;
					continue;
				}
				const navParams = parseEncodedJsonHeader(navResponse.headers.get("X-Vinext-Params")) ?? {};
				const navigationSnapshot = createClientNavigationRenderSnapshot(currentHref, navParams);
				const navBody = navResponse.body;
				if (!navBody) return;
				const [reactBranch, cacheBranch] = navBody.tee();
				const reactResponse = new Response(reactBranch, {
					status: navResponse.status,
					headers: navResponse.headers
				});
				const cacheBufferPromise = new Response(cacheBranch).arrayBuffer();
				if (!browserNavigationController.isCurrentNavigation(navId)) return;
				const rscPayload = decodeAppElementsPromise(createFromFetch(Promise.resolve(reactResponse)));
				if (!browserNavigationController.isCurrentNavigation(navId)) return;
				if (await renderNavigationPayload(rscPayload, navigationSnapshot, currentHref, navId, currentHistoryMode, navParams, requestPreviousNextUrl, pendingRouterState, toActionType(navigationKind), toOperationLane(navigationKind)) !== "committed") return;
				if (!browserNavigationController.isCurrentNavigation(navId)) return;
				const resolvedElements = await rscPayload;
				const metadata = AppElementsWire.readMetadata(resolvedElements);
				const cacheBuffer = await cacheBufferPromise;
				storeVisitedResponseSnapshot(rscUrl, resolveVisitedResponseInterceptionContext(requestInterceptionContext, metadata.interceptionContext), {
					buffer: cacheBuffer,
					contentType: navResponse.headers.get("content-type") ?? "text/x-component",
					mountedSlotsHeader: navResponse.headers.get(VINEXT_MOUNTED_SLOTS_HEADER),
					paramsHeader: navResponse.headers.get(VINEXT_PARAMS_HEADER),
					url: navResponse.url
				}, navParams);
				return;
			}
		} catch (error) {
			if (!browserNavigationController.isCurrentNavigation(navId)) return;
			if (!isPageUnloading) console.error("[vinext] RSC navigation error:", error);
			window.location.href = currentHref;
		} finally {
			browserNavigationController.finalizeNavigation(navId, pendingRouterState);
		}
	};
	if ("scrollRestoration" in history) history.scrollRestoration = "manual";
	window.addEventListener("popstate", (event) => {
		notifyAppRouterTransitionStart(window.location.href, "traverse");
		const pendingNavigation = window.__VINEXT_RSC_NAVIGATE__?.(window.location.href, 0, "traverse") ?? Promise.resolve();
		window.__VINEXT_RSC_PENDING__ = pendingNavigation;
		pendingNavigation.finally(() => {
			restorePopstateScrollPosition(event.state);
			if (window.__VINEXT_RSC_PENDING__ === pendingNavigation) window.__VINEXT_RSC_PENDING__ = null;
		});
	});
	if (import.meta.hot) {
		const handleRscUpdate = async () => {
			try {
				if (browserRouterStateHasEverCommitted && !browserNavigationController.hasBrowserRouterState()) {
					window.location.reload();
					return;
				}
				await waitForBrowserRouterStateReady();
				if (!browserNavigationController.hasBrowserRouterState()) return;
				clearClientNavigationCaches();
				const navigationSnapshot = createClientNavigationRenderSnapshot(window.location.href, latestClientParams);
				dismissOverlay();
				const hmrHeaders = createRscRequestHeaders();
				await browserNavigationController.hmrReplaceTree(decodeAppElementsPromise(createFromFetch(fetch(await createRscRequestUrl(window.location.pathname + window.location.search, hmrHeaders), { headers: hmrHeaders }))), navigationSnapshot);
			} catch (error) {
				console.error("[vinext] RSC HMR error:", error);
			}
		};
		import.meta.hot.on("rsc:update", () => {
			handleRscUpdate();
		});
	}
}
if (typeof document !== "undefined") {
	installWindowNext({
		appDir: true,
		router: appRouterInstance
	});
	window.addEventListener("pagehide", () => {
		isPageUnloading = true;
	});
	window.addEventListener("pageshow", () => {
		isPageUnloading = false;
	});
	main();
}
//#endregion
export {};

//# sourceMappingURL=app-browser-entry.js.map