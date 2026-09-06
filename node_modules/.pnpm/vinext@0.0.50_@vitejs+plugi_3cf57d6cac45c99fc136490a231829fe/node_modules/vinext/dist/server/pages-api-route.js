import { internalServerErrorResponse } from "./http-error-responses.js";
import { mergeRouteParamsIntoQuery, parseQueryString } from "../utils/query.js";
import { PagesBodyParseError } from "./pages-media-type.js";
import { createPagesReqRes, parsePagesApiBody } from "./pages-node-compat.js";
//#region src/server/pages-api-route.ts
function buildPagesApiQuery(url, params) {
	return mergeRouteParamsIntoQuery(parseQueryString(url), params);
}
async function handlePagesApiRoute(options) {
	if (!options.match) return new Response("404 - API route not found", { status: 404 });
	const { route, params } = options.match;
	const handler = route.module.default;
	if (typeof handler !== "function") return new Response("API route does not export a default function", { status: 500 });
	try {
		const query = buildPagesApiQuery(options.url, params);
		const { req, res, responsePromise } = createPagesReqRes({
			body: await parsePagesApiBody(options.request),
			query,
			request: options.request,
			url: options.url
		});
		await handler(req, res);
		res.end();
		return await responsePromise;
	} catch (error) {
		if (error instanceof PagesBodyParseError) return new Response(error.message, {
			status: error.statusCode,
			statusText: error.message
		});
		options.reportRequestError?.(error instanceof Error ? error : new Error(String(error)), route.pattern);
		return internalServerErrorResponse();
	}
}
//#endregion
export { handlePagesApiRoute };

//# sourceMappingURL=pages-api-route.js.map