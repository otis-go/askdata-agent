import { matchPattern, matchesMiddleware } from "./middleware-matcher.js";
import { resolveMiddlewareModuleHandler, runGeneratedMiddleware } from "./middleware-runtime.js";
import fs from "node:fs";
import path from "node:path";
//#region src/server/middleware.ts
/**
* Determine whether a middleware/proxy file path refers to a proxy file.
* proxy.ts files accept `proxy` or `default` exports.
* middleware.ts files accept `middleware` or `default` exports.
*
* Matches Next.js behavior where each file type only accepts its own
* named export or a default export:
* https://github.com/vercel/next.js/blob/canary/packages/next/src/build/templates/middleware.ts
*/
function isProxyFile(filePath) {
	return path.basename(filePath).replace(/\.\w+$/, "") === "proxy";
}
/**
* Resolve the middleware/proxy handler function from a module's exports.
* Matches Next.js behavior: for proxy files, check `proxy` then `default`;
* for middleware files, check `middleware` then `default`.
*
* Throws if the file exists but doesn't export a valid function, matching
* Next.js's ProxyMissingExportError behavior.
*
* @see https://github.com/vercel/next.js/blob/canary/packages/next/src/build/templates/middleware.ts
* @see https://github.com/vercel/next.js/blob/canary/test/e2e/app-dir/proxy-missing-export/proxy-missing-export.test.ts
*/
function resolveMiddlewareHandler(mod, filePath) {
	return resolveMiddlewareModuleHandler(mod, {
		filePath,
		isProxy: isProxyFile(filePath)
	});
}
const MIDDLEWARE_LOCATIONS = ["", "src/"];
/**
* Find the proxy or middleware file in the project root.
* Checks for proxy.ts (Next.js 16) first, then falls back to middleware.ts.
* If middleware.ts is found, logs a deprecation warning.
*/
function findMiddlewareFile(root, fileMatcher) {
	for (const dir of MIDDLEWARE_LOCATIONS) for (const ext of fileMatcher.dottedExtensions) {
		const fullPath = path.join(root, dir, `proxy${ext}`);
		if (fs.existsSync(fullPath)) return fullPath;
	}
	for (const dir of MIDDLEWARE_LOCATIONS) for (const ext of fileMatcher.dottedExtensions) {
		const fullPath = path.join(root, dir, `middleware${ext}`);
		if (fs.existsSync(fullPath)) {
			console.warn("[vinext] middleware.ts is deprecated in Next.js 16. Rename to proxy.ts and export a default or named proxy function.");
			return fullPath;
		}
	}
	return null;
}
function isMiddlewareModule(value) {
	return !!value && typeof value === "object";
}
/**
* Load and execute middleware for a given request.
*
* @param runner - A ModuleRunner used to load the middleware module.
*   Must be a long-lived instance created once (e.g. in configureServer) via
*   createDirectRunner() — NOT recreated per request. Using server.ssrLoadModule
*   directly crashes with `outsideEmitter` when @cloudflare/vite-plugin is
*   present because SSRCompatModuleRunner reads environment.hot.api synchronously.
* @param middlewarePath - Absolute path to the middleware file
* @param request - The incoming Request object
* @returns Middleware result describing what action to take
*/
async function runMiddleware(runner, middlewarePath, request, i18nConfig, basePath) {
	const mod = await runner.import(middlewarePath);
	if (!isMiddlewareModule(mod)) throw new Error(`Middleware module "${middlewarePath}" did not evaluate to an object.`);
	return runGeneratedMiddleware({
		basePath,
		filePath: middlewarePath,
		i18nConfig,
		includeErrorDetails: process.env.NODE_ENV !== "production",
		isProxy: isProxyFile(middlewarePath),
		module: mod,
		request
	});
}
//#endregion
export { findMiddlewareFile, isProxyFile, matchPattern, matchesMiddleware, resolveMiddlewareHandler, runMiddleware };

//# sourceMappingURL=middleware.js.map