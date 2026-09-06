import { runWithExecutionContext } from "../shims/request-context.js";
import { badRequestResponse, notFoundResponse } from "./http-error-responses.js";
import { cloneRequestWithHeaders, filterInternalHeaders, isOpenRedirectShaped } from "./request-pipeline.js";
import { resolveStaticAssetSignal } from "./worker-utils.js";
import rscHandler from "virtual:vinext-rsc-entry";
//#region src/server/app-router-entry.ts
/**
* Default Cloudflare Worker entry point for vinext App Router.
*
* Use this directly in wrangler.jsonc:
*   "main": "vinext/server/app-router-entry"
*
* Or import and delegate to it from a custom worker:
*   import handler from "vinext/server/app-router-entry";
*   return handler.fetch(request, env, ctx);
*
* This file runs in the RSC environment. Configure the Cloudflare plugin with:
*   cloudflare({ viteEnvironment: { name: "rsc", childEnvironments: ["ssr"] } })
*/
var app_router_entry_default = { async fetch(request, env, ctx) {
	return handleRequest(request, env, ctx);
} };
async function handleRequest(request, env, ctx) {
	const url = new URL(request.url);
	if (isOpenRedirectShaped(url.pathname)) return notFoundResponse();
	try {
		decodeURIComponent(url.pathname);
	} catch {
		return badRequestResponse();
	}
	{
		const filteredHeaders = filterInternalHeaders(request.headers);
		request = cloneRequestWithHeaders(request, filteredHeaders);
	}
	const handleFn = () => rscHandler(request, ctx);
	const result = await (ctx ? runWithExecutionContext(ctx, handleFn) : handleFn());
	if (result instanceof Response) {
		if (env?.ASSETS) {
			const assetFetcher = env.ASSETS;
			const assetResponse = await resolveStaticAssetSignal(result, { fetchAsset: (path) => Promise.resolve(assetFetcher.fetch(new Request(new URL(path, request.url)))) });
			if (assetResponse) return assetResponse;
		}
		return result;
	}
	if (result === null || result === void 0) return notFoundResponse();
	return new Response(String(result), { status: 200 });
}
//#endregion
export { app_router_entry_default as default };

//# sourceMappingURL=app-router-entry.js.map