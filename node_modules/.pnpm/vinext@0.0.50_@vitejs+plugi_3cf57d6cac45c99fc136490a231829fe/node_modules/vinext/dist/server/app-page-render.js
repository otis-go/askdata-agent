import { runWithFetchDedupe } from "../shims/fetch-cache.js";
import { createArtifactCompatibilityEnvelope, createArtifactCompatibilityGraphVersion } from "./artifact-compatibility.js";
import { AppElementsWire, isAppElementsRecord } from "./app-elements-wire.js";
import "./app-elements.js";
import { createAppPageFontData, createAppPageRscErrorTracker, deferUntilStreamConsumed, renderAppPageHtmlStream, renderAppPageHtmlStreamWithRecovery, shouldRerenderAppPageWithGlobalError } from "./app-page-stream.js";
import { finalizeAppPageHtmlCacheResponse, finalizeAppPageRscCacheResponse } from "./app-page-cache.js";
import { buildAppPageFontLinkHeader, readAppPageBinaryStream, resolveAppPageSpecialError, teeAppPageRscStreamForCapture } from "./app-page-execution.js";
import { probeAppPageBeforeRender } from "./app-page-probe.js";
import { buildAppPageHtmlResponse, buildAppPageRscResponse, resolveAppPageHtmlResponsePolicy, resolveAppPageRscResponsePolicy } from "./app-page-response.js";
//#region src/server/app-page-render.ts
function buildResponseTiming(options) {
	if (options.isProduction) return;
	return {
		compileEnd: options.compileEnd,
		handlerStart: options.handlerStart,
		renderEnd: options.renderEnd,
		responseKind: options.responseKind
	};
}
function readRequestCacheLifeForPrerender(options) {
	return options.peekRequestCacheLife?.() ?? options.getRequestCacheLife();
}
function applyRequestCacheLife(options) {
	let revalidateSeconds = options.revalidateSeconds;
	let expireSeconds = options.expireSeconds;
	const requestCacheLife = options.requestCacheLife;
	if (requestCacheLife?.revalidate !== void 0) revalidateSeconds = revalidateSeconds === null ? requestCacheLife.revalidate : Math.min(revalidateSeconds, requestCacheLife.revalidate);
	if (requestCacheLife?.expire !== void 0) expireSeconds = requestCacheLife.expire;
	return {
		expireSeconds,
		revalidateSeconds
	};
}
function readRootBoundaryId(element) {
	const rootLayoutTreePath = element[AppElementsWire.keys.rootLayout];
	return typeof rootLayoutTreePath === "string" ? rootLayoutTreePath : null;
}
function createAppPageArtifactCompatibility(element, routePattern) {
	if (!isAppElementsRecord(element)) return;
	const rootBoundaryId = readRootBoundaryId(element);
	return createArtifactCompatibilityEnvelope({
		graphVersion: createArtifactCompatibilityGraphVersion({
			routePattern,
			rootBoundaryId
		}),
		deploymentVersion: process.env.__VINEXT_BUILD_ID ?? null,
		rootBoundaryId
	});
}
/**
* Wraps an RSC response body to report invalid dynamic usage errors after the
* stream is fully consumed. In dev mode, errors from cookies()/headers() inside
* "use cache" may be caught by user try/catch and silently swallowed — this
* wrapper waits for the stream to drain and surfaces any recorded error to the
* terminal (and, via HMR, the browser dev overlay).
* Ported from Next.js: https://github.com/vercel/next.js/commit/f5e54c06726b571a042fce67417e40a29f6b8689
*/
function wrapRscResponseForDevErrorReporting(response, consumeInvalidDynamicUsageError) {
	const originalBody = response.body;
	if (!originalBody) return response;
	let consumed = false;
	const onConsumed = () => {
		if (consumed) return;
		consumed = true;
		const error = consumeInvalidDynamicUsageError();
		if (error) console.error("[vinext] Invalid dynamic usage:", error);
	};
	const cleanup = new TransformStream({ flush() {
		onConsumed();
	} });
	const reader = originalBody.pipeThrough(cleanup).getReader();
	const wrappedStream = new ReadableStream({
		pull(controller) {
			return reader.read().then(({ done, value }) => {
				if (done) controller.close();
				else controller.enqueue(value);
			}, (streamError) => {
				onConsumed();
				controller.error(streamError);
			});
		},
		cancel(reason) {
			onConsumed();
			return reader.cancel(reason);
		}
	});
	return new Response(wrappedStream, {
		status: response.status,
		statusText: response.statusText,
		headers: response.headers
	});
}
async function renderAppPageLifecycle(options) {
	const preRenderResult = await probeAppPageBeforeRender({
		hasLoadingBoundary: options.hasLoadingBoundary,
		layoutCount: options.layoutCount,
		probeLayoutAt(layoutIndex) {
			return options.probeLayoutAt(layoutIndex);
		},
		probePage() {
			return options.probePage();
		},
		renderLayoutSpecialError(specialError, layoutIndex) {
			return options.renderLayoutSpecialError(specialError, layoutIndex);
		},
		renderPageSpecialError(specialError) {
			return options.renderPageSpecialError(specialError);
		},
		resolveSpecialError: resolveAppPageSpecialError,
		runWithSuppressedHookWarning(probe) {
			return options.runWithSuppressedHookWarning(probe);
		},
		classification: options.classification
	});
	if (preRenderResult.response) return preRenderResult.response;
	const layoutFlags = preRenderResult.layoutFlags;
	const artifactCompatibility = createAppPageArtifactCompatibility(options.element, options.routePattern);
	const outgoingElement = AppElementsWire.encodeOutgoingPayload({
		element: options.element,
		layoutFlags,
		...artifactCompatibility ? { artifactCompatibility } : {}
	});
	const compileEnd = options.isProduction ? void 0 : performance.now();
	const rscErrorTracker = createAppPageRscErrorTracker(options.createRscOnErrorHandler(options.cleanPathname, options.routePattern));
	const rscStream = runWithFetchDedupe(() => options.renderToReadableStream(outgoingElement, { onError: rscErrorTracker.onRenderError }));
	let revalidateSeconds = options.revalidateSeconds;
	let expireSeconds = options.expireSeconds;
	const shouldCaptureRscForCacheMetadata = options.isProgressiveActionRender !== true && (options.isProduction || options.isPrerender === true) && (revalidateSeconds === null || revalidateSeconds > 0 && revalidateSeconds !== Infinity) && !options.isDraftMode && !options.isForceDynamic;
	const rscCapture = teeAppPageRscStreamForCapture(rscStream, shouldCaptureRscForCacheMetadata);
	const rscForResponse = rscCapture.ssrStream;
	const capturedRscDataRef = { value: null };
	if (rscCapture.sideStream && options.isRscRequest) capturedRscDataRef.value = readAppPageBinaryStream(rscCapture.sideStream);
	if (options.isRscRequest) {
		if (options.isPrerender === true) {
			await settleCapturedRscRenderForCacheMetadata(capturedRscDataRef.value);
			({expireSeconds, revalidateSeconds} = applyRequestCacheLife({
				expireSeconds,
				requestCacheLife: readRequestCacheLifeForPrerender(options),
				revalidateSeconds
			}));
		}
		const dynamicUsedDuringBuild = options.consumeDynamicUsage();
		const rscResponsePolicy = resolveAppPageRscResponsePolicy({
			dynamicUsedDuringBuild,
			isDraftMode: options.isDraftMode,
			isDynamicError: options.isDynamicError,
			isForceDynamic: options.isForceDynamic,
			isForceStatic: options.isForceStatic,
			isProduction: options.isProduction,
			expireSeconds,
			revalidateSeconds
		});
		const rscResponse = buildAppPageRscResponse(rscForResponse, {
			middlewareContext: options.middlewareContext,
			mountedSlotsHeader: options.mountedSlotsHeader,
			params: options.params,
			policy: rscResponsePolicy,
			timing: buildResponseTiming({
				compileEnd,
				handlerStart: options.handlerStart,
				isProduction: options.isProduction,
				responseKind: "rsc"
			})
		});
		return finalizeAppPageRscCacheResponse(!options.isProduction && rscResponse.body && options.consumeInvalidDynamicUsageError ? wrapRscResponseForDevErrorReporting(rscResponse, options.consumeInvalidDynamicUsageError) : rscResponse, {
			capturedRscDataPromise: options.isProduction && shouldCaptureRscForCacheMetadata ? capturedRscDataRef.value : null,
			cleanPathname: options.cleanPathname,
			consumeDynamicUsage: options.consumeDynamicUsage,
			dynamicUsedDuringBuild,
			getPageTags() {
				return options.getPageTags();
			},
			getRequestCacheLife() {
				return options.getRequestCacheLife();
			},
			isrDebug: options.isrDebug,
			isrRscKey: options.isrRscKey,
			isrSet: options.isrSet,
			mountedSlotsHeader: options.mountedSlotsHeader,
			renderMode: options.renderMode,
			preserveClientResponseHeaders: rscResponsePolicy.cacheState !== "MISS",
			expireSeconds,
			revalidateSeconds,
			waitUntil(promise) {
				options.waitUntil?.(promise);
			}
		});
	}
	const fontData = createAppPageFontData({
		getLinks: options.getFontLinks,
		getPreloads: options.getFontPreloads,
		getStyles: options.getFontStyles
	});
	const fontLinkHeader = buildAppPageFontLinkHeader(fontData.preloads);
	let renderEnd;
	const htmlRender = await renderAppPageHtmlStreamWithRecovery({
		onShellRendered() {
			if (!options.isProduction) renderEnd = performance.now();
		},
		renderErrorBoundaryResponse(error) {
			return options.renderErrorBoundaryResponse(error);
		},
		async renderHtmlStream() {
			const ssrHandler = await options.loadSsrHandler();
			return renderAppPageHtmlStream({
				capturedRscDataRef,
				fontData,
				navigationContext: options.getNavigationContext(),
				formState: options.formState ?? null,
				rscStream: rscForResponse,
				scriptNonce: options.scriptNonce,
				sideStream: rscCapture.sideStream,
				ssrHandler,
				waitForAllReady: options.isPrerender
			});
		},
		renderSpecialErrorResponse(specialError) {
			return options.renderPageSpecialError(specialError);
		},
		resolveSpecialError: resolveAppPageSpecialError
	});
	if (htmlRender.response) return htmlRender.response;
	const htmlStream = htmlRender.htmlStream;
	if (!htmlStream) throw new Error("[vinext] Expected an HTML stream when no fallback response was returned");
	if (options.hasLoadingBoundary) {
		const captured = rscErrorTracker.getCapturedSpecialError();
		if (captured) {
			const specialError = resolveAppPageSpecialError(captured);
			if (specialError) {
				htmlStream.cancel().catch(() => {});
				return options.renderPageSpecialError(specialError);
			}
		}
	}
	if (shouldRerenderAppPageWithGlobalError({
		capturedError: rscErrorTracker.getCapturedError(),
		hasLocalBoundary: options.routeHasLocalBoundary
	})) {
		const cleanResponse = await options.renderErrorBoundaryResponse(rscErrorTracker.getCapturedError());
		if (cleanResponse) return cleanResponse;
	}
	if (options.isPrerender === true) {
		await settleCapturedRscRenderForCacheMetadata(capturedRscDataRef.value);
		({expireSeconds, revalidateSeconds} = applyRequestCacheLife({
			expireSeconds,
			requestCacheLife: readRequestCacheLifeForPrerender(options),
			revalidateSeconds
		}));
	}
	const draftCookie = options.getDraftModeCookieHeader();
	const dynamicUsedDuringRender = options.consumeDynamicUsage();
	let dynamicUsedBeforeContextCleanup = dynamicUsedDuringRender;
	const safeHtmlStream = deferUntilStreamConsumed(htmlStream, () => {
		dynamicUsedBeforeContextCleanup = dynamicUsedBeforeContextCleanup || options.consumeDynamicUsage();
		options.clearRequestContext();
	});
	const htmlResponsePolicy = resolveAppPageHtmlResponsePolicy({
		dynamicUsedDuringRender,
		isProgressiveActionRender: options.isProgressiveActionRender === true,
		hasScriptNonce: Boolean(options.scriptNonce),
		isDraftMode: options.isDraftMode,
		isDynamicError: options.isDynamicError,
		isForceDynamic: options.isForceDynamic,
		isForceStatic: options.isForceStatic,
		isProduction: options.isProduction,
		expireSeconds,
		revalidateSeconds
	});
	const htmlResponseTiming = buildResponseTiming({
		compileEnd,
		handlerStart: options.handlerStart,
		isProduction: options.isProduction,
		renderEnd,
		responseKind: "html"
	});
	const shouldSpeculativelyWriteCache = options.isProduction && shouldCaptureRscForCacheMetadata && revalidateSeconds === null && !options.isDynamicError && !options.isForceStatic && !options.scriptNonce && options.isProgressiveActionRender !== true && !dynamicUsedDuringRender;
	if (htmlResponsePolicy.shouldWriteToCache || shouldSpeculativelyWriteCache) {
		const isrResponse = buildAppPageHtmlResponse(safeHtmlStream, {
			draftCookie,
			fontLinkHeader,
			middlewareContext: options.middlewareContext,
			policy: htmlResponsePolicy,
			timing: htmlResponseTiming
		});
		if (options.isPrerender === true) return isrResponse;
		return finalizeAppPageHtmlCacheResponse(isrResponse, {
			capturedDynamicUsageBeforeContextCleanup() {
				return dynamicUsedBeforeContextCleanup;
			},
			capturedRscDataPromise: capturedRscDataRef.value,
			cleanPathname: options.cleanPathname,
			consumeDynamicUsage: options.consumeDynamicUsage,
			getPageTags() {
				return options.getPageTags();
			},
			getRequestCacheLife() {
				return options.getRequestCacheLife();
			},
			isrDebug: options.isrDebug,
			isrHtmlKey: options.isrHtmlKey,
			isrRscKey: options.isrRscKey,
			isrSet: options.isrSet,
			preserveClientResponseHeaders: !htmlResponsePolicy.shouldWriteToCache,
			expireSeconds,
			revalidateSeconds,
			waitUntil(cachePromise) {
				options.waitUntil?.(cachePromise);
			}
		});
	}
	return buildAppPageHtmlResponse(safeHtmlStream, {
		draftCookie,
		fontLinkHeader,
		middlewareContext: options.middlewareContext,
		policy: htmlResponsePolicy,
		timing: htmlResponseTiming
	});
}
async function settleCapturedRscRenderForCacheMetadata(capturedRscDataPromise) {
	if (!capturedRscDataPromise) return;
	try {
		await capturedRscDataPromise;
	} catch {}
}
//#endregion
export { renderAppPageLifecycle };

//# sourceMappingURL=app-page-render.js.map