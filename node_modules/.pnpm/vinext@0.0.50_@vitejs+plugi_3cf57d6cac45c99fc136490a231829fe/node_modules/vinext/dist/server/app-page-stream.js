import { VINEXT_RSC_VARY_HEADER } from "./app-rsc-cache-busting.js";
import { mergeMiddlewareResponseHeaders } from "./middleware-response-headers.js";
//#region src/server/app-page-stream.ts
function createAppPageFontData(options) {
	return {
		links: options.getLinks(),
		preloads: options.getPreloads(),
		styles: options.getStyles()
	};
}
async function renderAppPageHtmlStream(options) {
	const ssrOptions = {
		formState: options.formState ?? null,
		scriptNonce: options.scriptNonce,
		sideStream: options.sideStream,
		capturedRscDataRef: options.capturedRscDataRef,
		waitForAllReady: options.waitForAllReady
	};
	return options.ssrHandler.handleSsr(options.rscStream, options.navigationContext, options.fontData, ssrOptions);
}
/**
* Wraps a stream so that `onFlush` is called when the last byte has been read
* by the downstream consumer (i.e. when the HTTP layer finishes draining the
* response body). This is the correct place to clear per-request context,
* because the RSC/SSR pipeline is lazy — components execute while the stream
* is being consumed, not when the stream handle is first obtained.
*/
function deferUntilStreamConsumed(stream, onFlush) {
	let called = false;
	const once = () => {
		if (!called) {
			called = true;
			onFlush();
		}
	};
	const cleanup = new TransformStream({ flush() {
		once();
	} });
	const reader = stream.pipeThrough(cleanup).getReader();
	return new ReadableStream({
		pull(controller) {
			return reader.read().then(({ done, value }) => {
				if (done) controller.close();
				else controller.enqueue(value);
			}, (error) => {
				once();
				controller.error(error);
			});
		},
		cancel(reason) {
			once();
			return reader.cancel(reason);
		}
	});
}
async function renderAppPageHtmlResponse(options) {
	const safeStream = deferUntilStreamConsumed(await renderAppPageHtmlStream(options), () => {
		options.clearRequestContext();
	});
	const headers = new Headers({
		"Content-Type": "text/html; charset=utf-8",
		Vary: VINEXT_RSC_VARY_HEADER
	});
	if (options.fontLinkHeader) headers.set("Link", options.fontLinkHeader);
	mergeMiddlewareResponseHeaders(headers, options.middlewareHeaders ?? null);
	return new Response(safeStream, {
		status: options.status,
		headers
	});
}
async function renderAppPageHtmlStreamWithRecovery(options) {
	try {
		const htmlStream = await options.renderHtmlStream();
		options.onShellRendered?.();
		return {
			htmlStream,
			response: null
		};
	} catch (error) {
		const specialError = options.resolveSpecialError(error);
		if (specialError) return {
			htmlStream: null,
			response: await options.renderSpecialErrorResponse(specialError)
		};
		const boundaryResponse = await options.renderErrorBoundaryResponse(error);
		if (boundaryResponse) return {
			htmlStream: null,
			response: boundaryResponse
		};
		throw error;
	}
}
function createAppPageRscErrorTracker(baseOnError) {
	let capturedError = null;
	let capturedSpecialError = null;
	return {
		getCapturedError() {
			return capturedError;
		},
		getCapturedSpecialError() {
			return capturedSpecialError;
		},
		onRenderError(error, requestInfo, errorContext) {
			if (error && typeof error === "object" && "digest" in error) {
				if (capturedSpecialError === null) capturedSpecialError = error;
			} else capturedError = error;
			return baseOnError(error, requestInfo, errorContext);
		}
	};
}
function shouldRerenderAppPageWithGlobalError(options) {
	return Boolean(options.capturedError) && !options.hasLocalBoundary;
}
//#endregion
export { createAppPageFontData, createAppPageRscErrorTracker, deferUntilStreamConsumed, renderAppPageHtmlResponse, renderAppPageHtmlStream, renderAppPageHtmlStreamWithRecovery, shouldRerenderAppPageWithGlobalError };

//# sourceMappingURL=app-page-stream.js.map