import { createRequestContext, runWithRequestContext } from "../shims/unified-request-context.js";
import { getRequestExecutionContext } from "../shims/request-context.js";
import { consumeDynamicUsage, consumeInvalidDynamicUsageError, getAndClearPendingCookies, getDraftModeCookieHeader, isDraftModeRequest, markDynamicUsage, setHeadersContext } from "../shims/headers.js";
import { _consumeRequestScopedCacheLife, _peekRequestScopedCacheLife } from "../shims/cache.js";
import { shouldSuppressLoadingBoundaries } from "./app-rsc-render-mode.js";
import { ensureFetchPatch, getCollectedFetchTags, runWithFetchDedupe, setCurrentFetchCacheMode, setCurrentFetchSoftTags } from "../shims/fetch-cache.js";
import { AppElementsWire } from "./app-elements-wire.js";
import "./app-elements.js";
import { VINEXT_RSC_VARY_HEADER } from "./app-rsc-cache-busting.js";
import { createAppPageTreePath } from "./app-page-route-wiring.js";
import { readStreamAsText } from "../utils/text-stream.js";
import { mergeMiddlewareResponseHeaders } from "./middleware-response-headers.js";
import { resolveAppPageParentHttpAccessBoundaryModule } from "./app-page-boundary.js";
import { readAppPageCacheResponse } from "./app-page-cache.js";
import { buildAppPageSpecialErrorResponse, resolveAppPageSpecialError, teeAppPageRscStreamForCapture } from "./app-page-execution.js";
import { resolveAppPageMethodResponse } from "./app-page-method.js";
import { buildAppPageElement, resolveAppPageIntercept, validateAppPageDynamicParams } from "./app-page-request.js";
import "./app-page-response.js";
import { renderAppPageLifecycle } from "./app-page-render.js";
import { createStaticGenerationHeadersContext } from "./app-static-generation.js";
import { buildPageCacheTags } from "./implicit-tags.js";
//#region src/server/app-page-dispatch.ts
function shouldReadAppPageCache(options) {
	return options.isProduction && !options.isProgressiveActionRender && !options.isDraftMode && !options.isForceDynamic && (options.isRscRequest || !options.scriptNonce) && (options.revalidateSeconds === null || options.revalidateSeconds > 0);
}
function buildAppPageTags(cleanPathname, extraTags, routeSegments) {
	return buildPageCacheTags(cleanPathname, extraTags, [...routeSegments], "page");
}
async function runAppPageRevalidationContext(options, renderFn) {
	return runWithRequestContext(createRequestContext({
		headersContext: createStaticGenerationHeadersContext({
			dynamicConfig: options.dynamicConfig,
			routeKind: "page",
			routePattern: options.routePattern
		}),
		currentFetchCacheMode: options.currentFetchCacheMode ?? null,
		executionContext: getRequestExecutionContext(),
		unstableCacheRevalidation: "foreground"
	}), async () => {
		ensureFetchPatch();
		setCurrentFetchSoftTags(buildAppPageTags(options.cleanPathname, [], options.routeSegments));
		options.setNavigationContext({
			pathname: options.cleanPathname,
			searchParams: new URLSearchParams(),
			params: options.params
		});
		return await runWithFetchDedupe(renderFn);
	});
}
function getCapturedRscDataPromise(capturedRscDataPromise) {
	if (!capturedRscDataPromise) throw new Error("[vinext] Expected captured RSC data while regenerating an app page cache entry");
	return capturedRscDataPromise;
}
function toInterceptOptions(interceptionContext, intercept) {
	return {
		interceptionContext,
		interceptLayouts: intercept.interceptLayouts,
		interceptPage: intercept.page,
		interceptParams: intercept.matchedParams,
		interceptSlotKey: intercept.slotKey
	};
}
async function dispatchAppPage(options) {
	return await runWithFetchDedupe(() => dispatchAppPageInner(options));
}
async function dispatchAppPageInner(options) {
	const route = options.route;
	const dynamicConfig = options.dynamicConfig;
	const currentRevalidateSeconds = options.revalidateSeconds;
	const isForceStatic = dynamicConfig === "force-static";
	const isDynamicError = dynamicConfig === "error";
	const isForceDynamic = dynamicConfig === "force-dynamic";
	const isDraftMode = isDraftModeRequest(options.request);
	setCurrentFetchSoftTags(buildAppPageTags(options.cleanPathname, [], route.routeSegments));
	setCurrentFetchCacheMode(options.fetchCache ?? null);
	if (options.hasPageModule && !options.hasPageDefaultExport) {
		options.clearRequestContext();
		return new Response("Page has no default export", { status: 500 });
	}
	const methodResponse = resolveAppPageMethodResponse({
		dynamicConfig,
		hasGenerateStaticParams: options.hasGenerateStaticParams,
		isDynamicRoute: route.isDynamic,
		middlewareHeaders: options.middlewareContext.headers,
		request: options.request,
		revalidateSeconds: currentRevalidateSeconds
	});
	if (methodResponse) {
		options.clearRequestContext();
		return methodResponse;
	}
	if ((isForceStatic || isDynamicError) && !isDraftMode) {
		setHeadersContext(createStaticGenerationHeadersContext({
			dynamicConfig,
			routeKind: "page",
			routePattern: route.pattern
		}));
		options.setNavigationContext({
			pathname: options.cleanPathname,
			searchParams: new URLSearchParams(),
			params: options.params
		});
	}
	if (shouldReadAppPageCache({
		isDraftMode,
		isForceDynamic,
		isProgressiveActionRender: options.isProgressiveActionRender === true,
		isProduction: options.isProduction,
		isRscRequest: options.isRscRequest,
		revalidateSeconds: currentRevalidateSeconds,
		scriptNonce: options.scriptNonce
	})) {
		const cachedPageResponse = await readAppPageCacheResponse({
			cleanPathname: options.cleanPathname,
			clearRequestContext: options.clearRequestContext,
			isRscRequest: options.isRscRequest,
			isrDebug: options.isrDebug,
			isrGet: options.isrGet,
			isrHtmlKey: options.isrHtmlKey,
			isrRscKey: options.isrRscKey,
			isrSet: options.isrSet,
			middlewareHeaders: options.middlewareContext.headers,
			middlewareStatus: options.middlewareContext.status,
			mountedSlotsHeader: options.mountedSlotsHeader,
			renderMode: options.renderMode,
			expireSeconds: options.expireSeconds,
			revalidateSeconds: currentRevalidateSeconds ?? 0,
			renderFreshPageForCache: async () => runAppPageRevalidationContext({
				cleanPathname: options.cleanPathname,
				currentFetchCacheMode: options.fetchCache ?? null,
				dynamicConfig,
				params: options.params,
				routePattern: route.pattern,
				routeSegments: route.routeSegments,
				setNavigationContext: options.setNavigationContext
			}, async () => {
				const revalidatedElement = await options.buildPageElement(route, options.params, void 0, new URLSearchParams());
				const revalidatedOnError = options.createRscOnErrorHandler(options.cleanPathname, route.pattern);
				const revalidatedRscCapture = teeAppPageRscStreamForCapture(options.renderToReadableStream(revalidatedElement, { onError: revalidatedOnError }), true);
				const revalidatedSsrEntry = await options.loadSsrHandler();
				const revalidatedCapturedRscRef = { value: null };
				const html = await readStreamAsText(await revalidatedSsrEntry.handleSsr(revalidatedRscCapture.ssrStream, options.getNavigationContext(), {
					links: options.getFontLinks(),
					styles: options.getFontStyles(),
					preloads: options.getFontPreloads()
				}, revalidatedRscCapture.sideStream ? {
					sideStream: revalidatedRscCapture.sideStream,
					capturedRscDataRef: revalidatedCapturedRscRef
				} : void 0));
				const rscData = await getCapturedRscDataPromise(revalidatedCapturedRscRef.value);
				const cacheLife = _consumeRequestScopedCacheLife();
				options.clearRequestContext();
				return {
					html,
					rscData,
					tags: buildAppPageTags(options.cleanPathname, getCollectedFetchTags(), route.routeSegments),
					cacheControl: typeof cacheLife?.revalidate === "number" ? {
						revalidate: cacheLife.revalidate,
						expire: cacheLife.expire
					} : void 0
				};
			}),
			scheduleBackgroundRegeneration(key, renderFn) {
				options.scheduleBackgroundRegeneration(key, renderFn, {
					routerKind: "App Router",
					routePath: route.pattern,
					routeType: "render"
				});
			}
		});
		if (cachedPageResponse) return cachedPageResponse;
	}
	const dynamicParamsResponse = await validateAppPageDynamicParams({
		clearRequestContext: options.clearRequestContext,
		enforceStaticParamsOnly: options.dynamicParamsConfig === false,
		generateStaticParams: options.generateStaticParams,
		isDynamicRoute: route.isDynamic,
		params: options.params
	});
	if (dynamicParamsResponse) return dynamicParamsResponse;
	const interceptResult = await resolveAppPageIntercept({
		buildPageElement(interceptRoute, interceptParams, interceptOpts, interceptSearchParams) {
			setCurrentFetchCacheMode(options.resolveRouteFetchCacheMode?.(interceptRoute) ?? null);
			return options.buildPageElement(interceptRoute, interceptParams, interceptOpts, interceptSearchParams);
		},
		cleanPathname: options.cleanPathname,
		currentRoute: route,
		findIntercept(pathname) {
			return options.findIntercept(pathname);
		},
		getRouteParamNames(sourceRoute) {
			return sourceRoute.params;
		},
		getSourceRoute(sourceRouteIndex) {
			return options.getSourceRoute(sourceRouteIndex);
		},
		isRscRequest: options.isRscRequest,
		renderInterceptResponse(sourceRoute, interceptElement) {
			const interceptOnError = options.createRscOnErrorHandler(options.cleanPathname, sourceRoute.pattern);
			const interceptStream = options.renderToReadableStream(interceptElement, { onError: interceptOnError });
			const interceptHeaders = new Headers({
				"Content-Type": "text/x-component; charset=utf-8",
				Vary: VINEXT_RSC_VARY_HEADER
			});
			mergeMiddlewareResponseHeaders(interceptHeaders, options.middlewareContext.headers);
			return new Response(interceptStream, {
				status: options.middlewareContext.status ?? 200,
				headers: interceptHeaders
			});
		},
		searchParams: options.searchParams,
		setNavigationContext: options.setNavigationContext,
		toInterceptOpts(intercept) {
			return toInterceptOptions(options.interceptionContext, intercept);
		}
	});
	if (interceptResult.response) return interceptResult.response;
	const pageBuildResult = await buildAppPageElement({
		buildPageElement() {
			return options.buildPageElement(route, options.params, interceptResult.interceptOpts, options.searchParams);
		},
		renderErrorBoundaryPage(buildError) {
			return options.renderErrorBoundaryPage(buildError);
		},
		renderSpecialError(specialError) {
			return renderPageSpecialError(options, specialError);
		},
		resolveSpecialError: resolveAppPageSpecialError
	});
	if (pageBuildResult.response) return pageBuildResult.response;
	return renderAppPageLifecycle({
		cleanPathname: options.cleanPathname,
		clearRequestContext: options.clearRequestContext,
		consumeDynamicUsage,
		consumeInvalidDynamicUsageError,
		createRscOnErrorHandler(pathname, routePath) {
			return options.createRscOnErrorHandler(pathname, routePath);
		},
		element: pageBuildResult.element,
		getDraftModeCookieHeader,
		getFontLinks: options.getFontLinks,
		getFontPreloads: options.getFontPreloads,
		getFontStyles: options.getFontStyles,
		getNavigationContext: options.getNavigationContext,
		getPageTags() {
			return buildAppPageTags(options.cleanPathname, getCollectedFetchTags(), route.routeSegments);
		},
		getRequestCacheLife() {
			return _consumeRequestScopedCacheLife();
		},
		peekRequestCacheLife() {
			return _peekRequestScopedCacheLife();
		},
		handlerStart: options.handlerStart,
		hasLoadingBoundary: shouldSuppressLoadingBoundaries(options.renderMode ?? "navigation") ? false : Boolean(route.loading?.default),
		formState: options.formState ?? null,
		isProgressiveActionRender: options.isProgressiveActionRender === true,
		isDynamicError,
		isDraftMode,
		isForceDynamic,
		isForceStatic,
		isPrerender: process.env.VINEXT_PRERENDER === "1",
		isProduction: options.isProduction,
		isRscRequest: options.isRscRequest,
		isrDebug: options.isrDebug,
		isrHtmlKey: options.isrHtmlKey,
		isrRscKey: options.isrRscKey,
		isrSet: options.isrSet,
		expireSeconds: options.expireSeconds,
		layoutCount: route.layouts.length,
		loadSsrHandler: options.loadSsrHandler,
		middlewareContext: options.middlewareContext,
		params: options.params,
		probeLayoutAt(layoutIndex) {
			return options.probeLayoutAt(layoutIndex);
		},
		probePage() {
			return options.probePage();
		},
		classification: {
			getLayoutId(index) {
				const treePosition = route.layoutTreePositions?.[index] ?? 0;
				return AppElementsWire.encodeLayoutId(createAppPageTreePath([...route.routeSegments], treePosition));
			},
			buildTimeClassifications: route.__buildTimeClassifications,
			buildTimeReasons: route.__buildTimeReasons,
			debugClassification: options.debugClassification,
			async runWithIsolatedDynamicScope(fn) {
				const priorDynamic = consumeDynamicUsage();
				try {
					return {
						result: await fn(),
						dynamicDetected: consumeDynamicUsage()
					};
				} finally {
					consumeDynamicUsage();
					if (priorDynamic) markDynamicUsage();
				}
			}
		},
		revalidateSeconds: currentRevalidateSeconds,
		mountedSlotsHeader: options.mountedSlotsHeader,
		renderMode: options.renderMode ?? "navigation",
		renderErrorBoundaryResponse(renderError) {
			return options.renderErrorBoundaryPage(renderError);
		},
		renderLayoutSpecialError(specialError, layoutIndex) {
			return renderLayoutSpecialError(options, specialError, layoutIndex);
		},
		renderPageSpecialError(specialError) {
			return renderPageSpecialError(options, specialError);
		},
		renderToReadableStream: options.renderToReadableStream,
		routeHasLocalBoundary: Boolean(route.error?.default || route.errors?.some((errorModule) => errorModule?.default)),
		routePattern: route.pattern,
		runWithSuppressedHookWarning(probe) {
			return options.runWithSuppressedHookWarning(probe);
		},
		scriptNonce: options.scriptNonce,
		waitUntil(cachePromise) {
			getRequestExecutionContext()?.waitUntil(cachePromise);
		}
	});
}
async function renderLayoutSpecialError(options, specialError, layoutIndex) {
	return buildAppPageSpecialErrorResponse({
		basePath: options.basePath,
		clearRequestContext: options.clearRequestContext,
		getAndClearPendingCookies,
		isRscRequest: options.isRscRequest,
		middlewareContext: options.middlewareContext,
		renderFallbackPage(statusCode) {
			const parentBoundary = resolveAppPageParentHttpAccessBoundaryModule({
				layoutIndex,
				rootForbiddenModule: options.rootForbiddenModule,
				rootNotFoundModule: options.rootNotFoundModule,
				rootUnauthorizedModule: options.rootUnauthorizedModule,
				routeForbiddenModules: options.route.forbiddens,
				routeNotFoundModules: options.route.notFounds,
				routeUnauthorizedModules: options.route.unauthorizeds,
				statusCode
			})?.default;
			return options.renderHttpAccessFallbackPage(statusCode, {
				boundaryComponent: parentBoundary,
				layouts: options.route.layouts.slice(0, layoutIndex),
				matchedParams: options.params
			}, null);
		},
		request: options.request,
		specialError
	});
}
async function renderPageSpecialError(options, specialError) {
	return buildAppPageSpecialErrorResponse({
		basePath: options.basePath,
		clearRequestContext: options.clearRequestContext,
		getAndClearPendingCookies,
		isRscRequest: options.isRscRequest,
		middlewareContext: options.middlewareContext,
		renderFallbackPage(statusCode) {
			return options.renderHttpAccessFallbackPage(statusCode, { matchedParams: options.params }, null);
		},
		request: options.request,
		specialError
	});
}
//#endregion
export { dispatchAppPage };

//# sourceMappingURL=app-page-dispatch.js.map