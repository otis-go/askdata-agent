import { VINEXT_CACHE_HEADER } from "./headers.js";
import { buildPagesCacheValue } from "./isr-cache.js";
import { buildCachedRevalidateCacheControl } from "./cache-control.js";
import { buildPagesNextDataScript } from "./pages-page-response.js";
//#region src/server/pages-page-data.ts
function buildPagesNotFoundResponse() {
	return new Response("<!DOCTYPE html><html><body><h1>404 - Page not found</h1></body></html>", {
		status: 404,
		headers: { "Content-Type": "text/html" }
	});
}
function buildPagesDataNotFoundResponse() {
	return new Response("404", { status: 404 });
}
function resolvePagesRedirectStatus(redirect) {
	return redirect.statusCode != null ? redirect.statusCode : redirect.permanent ? 308 : 307;
}
function matchesPagesStaticPath(pathEntry, params) {
	return Object.entries(pathEntry.params).every(([key, value]) => {
		const actual = params[key];
		if (Array.isArray(value)) return Array.isArray(actual) && value.join("/") === actual.join("/");
		return String(value) === String(actual);
	});
}
function buildPagesCacheResponse(html, cacheState, fontLinkHeader, revalidateSeconds, expireSeconds, cacheControl) {
	const effectiveRevalidateSeconds = cacheControl?.revalidate ?? revalidateSeconds ?? 60;
	const effectiveExpireSeconds = cacheControl === void 0 ? void 0 : cacheControl.expire ?? expireSeconds;
	const headers = {
		"Content-Type": "text/html",
		[VINEXT_CACHE_HEADER]: cacheState,
		"Cache-Control": buildCachedRevalidateCacheControl(cacheState, effectiveRevalidateSeconds, effectiveExpireSeconds)
	};
	if (fontLinkHeader) headers.Link = fontLinkHeader;
	return new Response(html, {
		status: 200,
		headers
	});
}
function rewritePagesCachedHtml(cachedHtml, freshBody, nextDataScript) {
	const bodyStart = cachedHtml.indexOf("<div id=\"__next\">");
	const contentStart = bodyStart >= 0 ? bodyStart + 17 : -1;
	const nextDataStart = cachedHtml.indexOf("<script>window.__NEXT_DATA__");
	if (contentStart >= 0 && nextDataStart >= 0) {
		const region = cachedHtml.slice(contentStart, nextDataStart);
		const lastCloseDiv = region.lastIndexOf("</div>");
		const gap = lastCloseDiv >= 0 ? region.slice(lastCloseDiv + 6) : "";
		const nextDataEnd = cachedHtml.indexOf("<\/script>", nextDataStart) + 9;
		const tail = cachedHtml.slice(nextDataEnd);
		return cachedHtml.slice(0, contentStart) + freshBody + "</div>" + gap + nextDataScript + tail;
	}
	return "<!DOCTYPE html>\n<html>\n<head>\n</head>\n<body>\n  <div id=\"__next\">" + freshBody + "</div>\n  " + nextDataScript + "\n</body>\n</html>";
}
async function renderPagesIsrHtml(options) {
	const freshBody = await options.renderIsrPassToStringAsync(options.createPageElement(options.pageProps));
	const nextDataScript = buildPagesNextDataScript({
		buildId: options.buildId,
		i18n: options.i18n,
		pageProps: options.pageProps,
		params: options.params,
		routePattern: options.routePattern,
		safeJsonStringify: options.safeJsonStringify
	});
	return rewritePagesCachedHtml(options.cachedHtml, freshBody, nextDataScript);
}
async function resolvePagesPageData(options) {
	if (typeof options.pageModule.getStaticPaths === "function" && options.route.isDynamic) {
		const pathsResult = await options.pageModule.getStaticPaths({
			locales: options.i18n.locales ?? [],
			defaultLocale: options.i18n.defaultLocale ?? ""
		});
		if ((pathsResult?.fallback ?? false) === false) {
			if (!(pathsResult?.paths ?? []).some((pathEntry) => matchesPagesStaticPath(pathEntry, options.params))) return {
				kind: "response",
				response: buildPagesNotFoundResponse()
			};
		}
	}
	let pageProps = {};
	let gsspRes = null;
	if (typeof options.pageModule.getServerSideProps === "function") {
		const { req, res, responsePromise } = options.createGsspReqRes();
		const result = await options.pageModule.getServerSideProps({
			params: options.params,
			req,
			res,
			query: options.query,
			resolvedUrl: options.routeUrl,
			locale: options.i18n.locale,
			locales: options.i18n.locales,
			defaultLocale: options.i18n.defaultLocale
		});
		if (res.headersSent) return {
			kind: "response",
			response: await responsePromise
		};
		if (result?.props) pageProps = result.props;
		if (result?.redirect) return {
			kind: "response",
			response: new Response(null, {
				status: resolvePagesRedirectStatus(result.redirect),
				headers: { Location: options.sanitizeDestination(result.redirect.destination) }
			})
		};
		if (result?.notFound) return {
			kind: "response",
			response: buildPagesDataNotFoundResponse()
		};
		gsspRes = res;
	}
	let isrRevalidateSeconds = null;
	if (typeof options.pageModule.getStaticProps === "function") {
		const pathname = options.routeUrl.split("?")[0];
		const cacheKey = options.isrCacheKey("pages", pathname);
		const cached = await options.isrGet(cacheKey);
		const cachedValue = cached?.value.value;
		if (cachedValue?.kind === "PAGES" && cached && !cached.isStale && !options.scriptNonce) return {
			kind: "response",
			response: buildPagesCacheResponse(cachedValue.html, "HIT", options.fontLinkHeader, void 0, options.expireSeconds, cached.value.cacheControl)
		};
		if (cachedValue?.kind === "PAGES" && cached && cached.isStale && !options.scriptNonce) {
			options.triggerBackgroundRegeneration(cacheKey, async function() {
				return options.runInFreshUnifiedContext(async () => {
					const freshResult = await options.pageModule.getStaticProps?.({
						params: options.params,
						locale: options.i18n.locale,
						locales: options.i18n.locales,
						defaultLocale: options.i18n.defaultLocale
					});
					if (freshResult?.props && typeof freshResult.revalidate === "number" && freshResult.revalidate > 0) {
						options.applyRequestContexts();
						const freshHtml = await renderPagesIsrHtml({
							buildId: options.buildId,
							cachedHtml: cachedValue.html,
							createPageElement: options.createPageElement,
							i18n: options.i18n,
							pageProps: freshResult.props,
							params: options.params,
							renderIsrPassToStringAsync: options.renderIsrPassToStringAsync,
							routePattern: options.routePattern,
							safeJsonStringify: options.safeJsonStringify
						});
						await options.isrSet(cacheKey, buildPagesCacheValue(freshHtml, freshResult.props), freshResult.revalidate, void 0, options.expireSeconds);
					}
				});
			}, {
				routerKind: "Pages Router",
				routePath: options.routePattern,
				routeType: "render"
			});
			return {
				kind: "response",
				response: buildPagesCacheResponse(cachedValue.html, "STALE", options.fontLinkHeader, void 0, options.expireSeconds, cached.value.cacheControl)
			};
		}
		const result = await options.pageModule.getStaticProps({
			params: options.params,
			locale: options.i18n.locale,
			locales: options.i18n.locales,
			defaultLocale: options.i18n.defaultLocale
		});
		if (result?.props) pageProps = result.props;
		if (result?.redirect) return {
			kind: "response",
			response: new Response(null, {
				status: resolvePagesRedirectStatus(result.redirect),
				headers: { Location: options.sanitizeDestination(result.redirect.destination) }
			})
		};
		if (result?.notFound) return {
			kind: "response",
			response: buildPagesDataNotFoundResponse()
		};
		if (typeof result?.revalidate === "number" && result.revalidate > 0) isrRevalidateSeconds = result.revalidate;
	}
	return {
		kind: "render",
		gsspRes,
		isrRevalidateSeconds,
		pageProps
	};
}
//#endregion
export { renderPagesIsrHtml, resolvePagesPageData };

//# sourceMappingURL=pages-page-data.js.map