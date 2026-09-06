import { normalizePathnameForRouteMatch } from "../routing/utils.js";
import { stripBasePath } from "../utils/base-path.js";
import "./headers.js";
import { normalizePath } from "./normalize-path.js";
import { applyConfigHeadersToResponse } from "./request-pipeline.js";
import { VINEXT_RSC_VARY_HEADER } from "./app-rsc-cache-busting.js";
import { mergeVaryHeader } from "./middleware-response-headers.js";
//#region src/server/app-rsc-response-finalizer.ts
/**
* Apply App Router response finalization that must happen outside individual
* route dispatchers.
*
* Called once per request in the outer handler() wrapper, after all route
* handling, so that every response path (page, route handler, server action,
* metadata, not-found) gets headers applied consistently.
*
* Skips 3xx redirect responses. Response.redirect() creates immutable
* headers that throw on mutation, and Next.js does not apply config headers
* to redirects regardless.
*/
function finalizeAppRscResponse(response, request, options) {
	if (response.status >= 300 && response.status < 400) return response;
	if (!response.headers.has("x-vinext-static-file")) mergeVaryHeader(response.headers, VINEXT_RSC_VARY_HEADER);
	if (!options.configHeaders.length) return response;
	const url = new URL(request.url);
	let pathname;
	try {
		pathname = normalizePath(normalizePathnameForRouteMatch(url.pathname));
	} catch {
		pathname = url.pathname;
	}
	pathname = stripBasePath(pathname, options.basePath);
	applyConfigHeadersToResponse(response.headers, {
		configHeaders: options.configHeaders,
		pathname,
		requestContext: options.requestContext
	});
	return response;
}
//#endregion
export { finalizeAppRscResponse };

//# sourceMappingURL=app-rsc-response-finalizer.js.map