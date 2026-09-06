import { hasBasePath } from "../utils/base-path.js";
import { createRscRedirectLocation } from "./app-rsc-cache-busting.js";
import { mergeMiddlewareResponseHeaders } from "./middleware-response-headers.js";
import { parseNextHttpErrorDigest, parseNextRedirectDigest } from "./next-error-digest.js";
//#region src/server/app-page-execution.ts
function isPromiseLike(value) {
	return Boolean(value && (typeof value === "object" || typeof value === "function") && "then" in value && typeof value.then === "function");
}
function getAppPageStatusText(statusCode) {
	return statusCode === 403 ? "Forbidden" : statusCode === 401 ? "Unauthorized" : "Not Found";
}
function mergeAppPageSpecialErrorHeaders(response, middlewareContext) {
	const headers = new Headers(response.headers);
	mergeMiddlewareResponseHeaders(headers, middlewareContext?.headers ?? null);
	return new Response(response.body, {
		headers,
		status: response.status,
		statusText: response.statusText
	});
}
function resolveAppPageSpecialError(error) {
	if (!(error && typeof error === "object" && "digest" in error)) return null;
	const digest = String(error.digest);
	const redirect = parseNextRedirectDigest(digest);
	if (redirect) return {
		kind: "redirect",
		location: redirect.url,
		statusCode: redirect.status
	};
	const httpError = parseNextHttpErrorDigest(digest);
	if (httpError) return {
		kind: "http-access-fallback",
		statusCode: httpError.status
	};
	return null;
}
/**
* Resolves a redirect() target against the request URL and prepends the
* configured basePath when the target is an app-internal absolute path.
*
* Mirrors Next.js's `addPathPrefix(getURLFromRedirectError(err), basePath)`
* in `app-render.tsx`: a `redirect("/about")` call from a page mounted at
* `/blog` (basePath) produces `Location: /blog/about`.
*
* Skips prefixing when:
*  - basePath is unset / empty
*  - the target is a full URL pointing at a different origin (external redirect)
*  - the target already starts with the basePath (caller did the work themselves)
*/
function applyAppPageRedirectBasePath(location, requestUrl, basePath) {
	const resolved = new URL(location, requestUrl);
	const requestOrigin = new URL(requestUrl).origin;
	if (!basePath || resolved.origin !== requestOrigin) return resolved.toString();
	if (hasBasePath(resolved.pathname, basePath)) return resolved.toString();
	resolved.pathname = resolved.pathname === "/" ? basePath : `${basePath}${resolved.pathname}`;
	return resolved.toString();
}
async function buildAppPageSpecialErrorResponse(options) {
	if (options.specialError.kind === "redirect") {
		options.clearRequestContext();
		const prefixedLocation = applyAppPageRedirectBasePath(options.specialError.location, options.request.url, options.basePath);
		const location = options.isRscRequest ? await createRscRedirectLocation(prefixedLocation, options.request) : prefixedLocation;
		const headers = new Headers({ Location: location });
		mergeMiddlewareResponseHeaders(headers, options.middlewareContext?.headers ?? null);
		const pendingCookies = options.getAndClearPendingCookies?.() ?? [];
		for (const cookie of pendingCookies) headers.append("Set-Cookie", cookie);
		return new Response(null, {
			headers,
			status: options.specialError.statusCode
		});
	}
	if (options.renderFallbackPage) {
		const fallbackResponse = await options.renderFallbackPage(options.specialError.statusCode);
		if (fallbackResponse) return mergeAppPageSpecialErrorHeaders(fallbackResponse, options.middlewareContext);
	}
	options.clearRequestContext();
	return mergeAppPageSpecialErrorHeaders(new Response(getAppPageStatusText(options.specialError.statusCode), { status: options.specialError.statusCode }), options.middlewareContext);
}
/** See `LayoutFlags` type docblock in app-elements.ts for lifecycle. */
async function probeAppPageLayouts(options) {
	const layoutFlags = {};
	const cls = options.classification ?? null;
	return {
		response: await options.runWithSuppressedHookWarning(async () => {
			for (let layoutIndex = options.layoutCount - 1; layoutIndex >= 0; layoutIndex--) {
				const buildTimeResult = cls?.buildTimeClassifications?.get(layoutIndex);
				if (cls && buildTimeResult) {
					layoutFlags[cls.getLayoutId(layoutIndex)] = buildTimeResult === "static" ? "s" : "d";
					if (cls.debugClassification) cls.debugClassification(cls.getLayoutId(layoutIndex), cls.buildTimeReasons?.get(layoutIndex) ?? { layer: "no-classifier" });
					const errorResponse = await probeLayoutForErrors(options, layoutIndex);
					if (errorResponse) return errorResponse;
					continue;
				}
				if (cls) {
					try {
						const { dynamicDetected } = await cls.runWithIsolatedDynamicScope(() => options.probeLayoutAt(layoutIndex));
						layoutFlags[cls.getLayoutId(layoutIndex)] = dynamicDetected ? "d" : "s";
						if (cls.debugClassification) cls.debugClassification(cls.getLayoutId(layoutIndex), {
							layer: "runtime-probe",
							outcome: dynamicDetected ? "dynamic" : "static"
						});
					} catch (error) {
						layoutFlags[cls.getLayoutId(layoutIndex)] = "d";
						if (cls.debugClassification) cls.debugClassification(cls.getLayoutId(layoutIndex), {
							layer: "runtime-probe",
							outcome: "dynamic",
							error: error instanceof Error ? error.message : String(error)
						});
						const errorResponse = await options.onLayoutError(error, layoutIndex);
						if (errorResponse) return errorResponse;
					}
					continue;
				}
				const errorResponse = await probeLayoutForErrors(options, layoutIndex);
				if (errorResponse) return errorResponse;
			}
			return null;
		}),
		layoutFlags
	};
}
async function probeLayoutForErrors(options, layoutIndex) {
	try {
		const layoutResult = options.probeLayoutAt(layoutIndex);
		if (isPromiseLike(layoutResult)) await layoutResult;
	} catch (error) {
		return options.onLayoutError(error, layoutIndex);
	}
	return null;
}
async function probeAppPageComponent(options) {
	return options.runWithSuppressedHookWarning(async () => {
		try {
			const pageResult = options.probePage();
			if (isPromiseLike(pageResult)) if (options.awaitAsyncResult) await pageResult;
			else Promise.resolve(pageResult).catch(() => {});
		} catch (error) {
			return options.onError(error);
		}
		return null;
	});
}
async function readAppPageBinaryStream(stream) {
	const reader = stream.getReader();
	const chunks = [];
	let totalLength = 0;
	for (;;) {
		const { done, value } = await reader.read();
		if (done) break;
		chunks.push(value);
		totalLength += value.byteLength;
	}
	const buffer = new Uint8Array(totalLength);
	let offset = 0;
	for (const chunk of chunks) {
		buffer.set(chunk, offset);
		offset += chunk.byteLength;
	}
	return buffer.buffer;
}
function teeAppPageRscStreamForCapture(stream, shouldCapture) {
	if (!shouldCapture) return { ssrStream: stream };
	const [ssrStream, sideStream] = stream.tee();
	return {
		ssrStream,
		sideStream
	};
}
function buildAppPageFontLinkHeader(preloads) {
	if (!preloads || preloads.length === 0) return "";
	return preloads.map((preload) => `<${preload.href}>; rel=preload; as=font; type=${preload.type}; crossorigin`).join(", ");
}
//#endregion
export { buildAppPageFontLinkHeader, buildAppPageSpecialErrorResponse, probeAppPageComponent, probeAppPageLayouts, readAppPageBinaryStream, resolveAppPageSpecialError, teeAppPageRscStreamForCapture };

//# sourceMappingURL=app-page-execution.js.map