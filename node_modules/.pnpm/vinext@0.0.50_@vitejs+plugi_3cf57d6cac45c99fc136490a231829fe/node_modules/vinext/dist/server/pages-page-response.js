import { getRequestExecutionContext } from "../shims/request-context.js";
import { VINEXT_CACHE_HEADER } from "./headers.js";
import { reportRequestError } from "./instrumentation.js";
import { withScriptNonce } from "../shims/script-nonce-context.js";
import { createInlineScriptTag, createNonceAttribute, escapeHtmlAttr } from "./html.js";
import { readStreamAsText } from "../utils/text-stream.js";
import { buildRevalidateCacheControl } from "./cache-control.js";
import React from "react";
//#region src/server/pages-page-response.ts
function buildPagesFontHeadHtml(fontLinks, fontPreloads, fontStyles, scriptNonce) {
	let html = "";
	const nonceAttr = createNonceAttribute(scriptNonce);
	for (const link of fontLinks) html += `<link rel="stylesheet"${nonceAttr} href="${escapeHtmlAttr(link)}" />\n  `;
	for (const preload of fontPreloads) html += `<link rel="preload"${nonceAttr} href="${escapeHtmlAttr(preload.href)}" as="font" type="${escapeHtmlAttr(preload.type)}" crossorigin />\n  `;
	if (fontStyles.length > 0) html += `<style data-vinext-fonts${nonceAttr}>${fontStyles.join("\n")}</style>\n  `;
	return html;
}
function buildPagesNextDataScript(options) {
	const nextDataPayload = {
		props: { pageProps: options.pageProps },
		page: options.routePattern,
		query: options.params,
		buildId: options.buildId,
		isFallback: false
	};
	if (options.i18n.locales) {
		nextDataPayload.locale = options.i18n.locale;
		nextDataPayload.locales = options.i18n.locales;
		nextDataPayload.defaultLocale = options.i18n.defaultLocale;
		nextDataPayload.domainLocales = options.i18n.domainLocales;
	}
	const localeGlobals = options.i18n.locales ? `;window.__VINEXT_LOCALE__=${options.safeJsonStringify(options.i18n.locale)};window.__VINEXT_LOCALES__=${options.safeJsonStringify(options.i18n.locales)};window.__VINEXT_DEFAULT_LOCALE__=${options.safeJsonStringify(options.i18n.defaultLocale)}` : "";
	return createInlineScriptTag(`window.__NEXT_DATA__ = ${options.safeJsonStringify(nextDataPayload)}${localeGlobals}`, options.scriptNonce);
}
async function buildPagesShellHtml(bodyMarker, fontHeadHTML, nextDataScript, options) {
	if (options.DocumentComponent) {
		let html = await options.renderDocumentToString(React.createElement(options.DocumentComponent));
		html = html.replace("__NEXT_MAIN__", bodyMarker);
		if (options.ssrHeadHTML || options.assetTags || fontHeadHTML) html = html.replace("</head>", `  ${fontHeadHTML}${options.ssrHeadHTML}\n  ${options.assetTags}\n</head>`);
		html = html.replace("<!-- __NEXT_SCRIPTS__ -->", nextDataScript);
		if (!html.includes("__NEXT_DATA__")) html = html.replace("</body>", `  ${nextDataScript}\n</body>`);
		return html;
	}
	return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  ${fontHeadHTML}${options.ssrHeadHTML}\n  ${options.assetTags}\n</head>
<body>
  <div id="__next">${bodyMarker}</div>\n  ${nextDataScript}\n</body>
</html>`;
}
async function buildPagesCompositeStream(bodyStream, shellPrefix, shellSuffix) {
	const encoder = new TextEncoder();
	return new ReadableStream({ async start(controller) {
		controller.enqueue(encoder.encode(shellPrefix));
		const reader = bodyStream.getReader();
		try {
			for (;;) {
				const chunk = await reader.read();
				if (chunk.done) break;
				controller.enqueue(chunk.value);
			}
		} finally {
			reader.releaseLock();
		}
		controller.enqueue(encoder.encode(shellSuffix));
		controller.close();
	} });
}
async function reportPagesIsrCacheWriteError(error, cacheKey, routePattern) {
	console.error(`[vinext] Pages ISR cache write failed for ${cacheKey}:`, error);
	try {
		await reportRequestError(error instanceof Error ? error : new Error(String(error)), {
			path: cacheKey,
			method: "GET",
			headers: {}
		}, {
			routerKind: "Pages Router",
			routePath: routePattern,
			routeType: "render"
		});
	} catch {}
}
function schedulePagesIsrCacheWrite(options) {
	const cacheWritePromise = readStreamAsText(options.stream).then((bodyHtml) => options.setCache(options.cacheKey, {
		kind: "PAGES",
		html: options.shellPrefix + bodyHtml + options.shellSuffix,
		pageData: options.pageData,
		headers: void 0,
		status: void 0
	}, options.revalidateSeconds, void 0, options.expireSeconds)).catch((error) => reportPagesIsrCacheWriteError(error, options.cacheKey, options.routePattern));
	getRequestExecutionContext()?.waitUntil(cacheWritePromise);
}
function applyGsspHeaders(headers, gsspRes) {
	if (!gsspRes) return 200;
	const gsspHeaders = gsspRes.getHeaders();
	for (const key of Object.keys(gsspHeaders)) {
		const value = gsspHeaders[key];
		if (key.toLowerCase() === "set-cookie" && Array.isArray(value)) {
			for (const cookie of value) headers.append("set-cookie", String(cookie));
			continue;
		}
		if (Array.isArray(value)) {
			headers.set(key, value.join(", "));
			continue;
		}
		if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") headers.set(key, String(value));
	}
	headers.set("Content-Type", "text/html");
	return gsspRes.statusCode;
}
async function renderPagesPageResponse(options) {
	const pageElement = withScriptNonce(React.createElement(React.Fragment, null, options.createPageElement(options.pageProps)), options.scriptNonce);
	options.resetSSRHead?.();
	await options.flushPreloads?.();
	const fontHeadHTML = buildPagesFontHeadHtml(options.getFontLinks(), options.fontPreloads, options.getFontStyles(), options.scriptNonce);
	const nextDataScript = buildPagesNextDataScript({
		buildId: options.buildId,
		i18n: options.i18n,
		pageProps: options.pageProps,
		params: options.params,
		routePattern: options.routePattern,
		safeJsonStringify: options.safeJsonStringify,
		scriptNonce: options.scriptNonce
	});
	const bodyMarker = "<!--VINEXT_STREAM_BODY-->";
	const bodyStream = await options.renderToReadableStream(pageElement);
	const shellHtml = await buildPagesShellHtml(bodyMarker, fontHeadHTML, nextDataScript, {
		assetTags: options.assetTags,
		DocumentComponent: options.DocumentComponent,
		renderDocumentToString: options.renderDocumentToString,
		ssrHeadHTML: options.getSSRHeadHTML?.() ?? ""
	});
	options.clearSsrContext();
	const markerIndex = shellHtml.indexOf(bodyMarker);
	const shellPrefix = shellHtml.slice(0, markerIndex);
	const shellSuffix = shellHtml.slice(markerIndex + 25);
	let responseBodyStream = bodyStream;
	if (!options.scriptNonce && options.isrRevalidateSeconds !== null && options.isrRevalidateSeconds > 0) {
		const cacheBodyStreamPair = bodyStream.tee();
		responseBodyStream = cacheBodyStreamPair[0];
		const cacheBodyStream = cacheBodyStreamPair[1];
		const isrPathname = options.routeUrl.split("?")[0];
		schedulePagesIsrCacheWrite({
			cacheKey: options.isrCacheKey("pages", isrPathname),
			expireSeconds: options.expireSeconds,
			pageData: options.pageProps,
			revalidateSeconds: options.isrRevalidateSeconds,
			routePattern: options.routePattern,
			setCache: options.isrSet,
			shellPrefix,
			shellSuffix,
			stream: cacheBodyStream
		});
	}
	const compositeStream = await buildPagesCompositeStream(responseBodyStream, shellPrefix, shellSuffix);
	const responseHeaders = new Headers({ "Content-Type": "text/html" });
	const finalStatus = applyGsspHeaders(responseHeaders, options.gsspRes);
	if (options.scriptNonce) responseHeaders.set("Cache-Control", "no-store, must-revalidate");
	else if (options.isrRevalidateSeconds) {
		responseHeaders.set("Cache-Control", buildRevalidateCacheControl(options.isrRevalidateSeconds, options.expireSeconds));
		responseHeaders.set(VINEXT_CACHE_HEADER, "MISS");
	}
	if (options.fontLinkHeader) responseHeaders.set("Link", options.fontLinkHeader);
	return Object.assign(new Response(compositeStream, {
		status: finalStatus,
		headers: responseHeaders
	}), { __vinextStreamedHtmlResponse: true });
}
//#endregion
export { buildPagesNextDataScript, renderPagesPageResponse };

//# sourceMappingURL=pages-page-response.js.map