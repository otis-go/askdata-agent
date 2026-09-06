import { existsSync } from "node:fs";
import { glob } from "node:fs/promises";
//#region src/routing/file-matcher.ts
const DEFAULT_PAGE_EXTENSIONS = [
	"tsx",
	"ts",
	"jsx",
	"js"
];
function escapeRegex(value) {
	return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function normalizePageExtensions(pageExtensions) {
	if (!Array.isArray(pageExtensions) || pageExtensions.length === 0) return [...DEFAULT_PAGE_EXTENSIONS];
	const filtered = pageExtensions.filter((ext) => typeof ext === "string").map((ext) => ext.trim().replace(/^\.+/, "")).filter((ext) => ext.length > 0);
	return filtered.length > 0 ? [...filtered] : [...DEFAULT_PAGE_EXTENSIONS];
}
function buildExtensionGlob(stem, extensions) {
	if (extensions.length === 1) return `${stem}.${extensions[0]}`;
	return `${stem}.{${extensions.join(",")}}`;
}
/**
* Ported in spirit from Next.js createValidFileMatcher:
* packages/next/src/server/lib/find-page-file.ts
*/
function createValidFileMatcher(pageExtensions) {
	const extensions = normalizePageExtensions(pageExtensions);
	const dottedExtensions = extensions.map((ext) => `.${ext}`);
	const extPattern = `(?:${extensions.map((ext) => escapeRegex(ext)).join("|")})`;
	const extensionRegex = new RegExp(`\\.${extPattern}$`);
	const createLeafPattern = (fileNames) => {
		const names = fileNames.length === 1 ? fileNames[0] : `(${fileNames.join("|")})`;
		return new RegExp(`(^${names}|[\\\\/]${names})\\.${extPattern}$`);
	};
	const appRouterPageRegex = createLeafPattern(["page", "route"]);
	const appRouterRouteRegex = createLeafPattern(["route"]);
	const appLayoutRegex = createLeafPattern(["layout"]);
	const appDefaultRegex = createLeafPattern(["default"]);
	return {
		extensions,
		dottedExtensions,
		extensionRegex,
		isPageFile(filePath) {
			return extensionRegex.test(filePath);
		},
		isAppRouterPage(filePath) {
			return appRouterPageRegex.test(filePath);
		},
		isAppRouterRoute(filePath) {
			return appRouterRouteRegex.test(filePath);
		},
		isAppLayoutFile(filePath) {
			return appLayoutRegex.test(filePath);
		},
		isAppDefaultFile(filePath) {
			return appDefaultRegex.test(filePath);
		},
		stripExtension(filePath) {
			return filePath.replace(extensionRegex, "");
		}
	};
}
/** Check if a file exists with any configured page extension. */
function findFileWithExtensions(basePath, matcher) {
	return matcher.dottedExtensions.some((ext) => existsSync(basePath + ext));
}
/**
* Use function-form exclude for Node < 22.14 compatibility.
*/
async function* scanWithExtensions(stem, cwd, extensions, exclude) {
	const pattern = buildExtensionGlob(stem, extensions);
	for await (const file of glob(pattern, {
		cwd,
		...exclude ? { exclude } : {}
	})) yield file;
}
//#endregion
export { createValidFileMatcher, findFileWithExtensions, normalizePageExtensions, scanWithExtensions };

//# sourceMappingURL=file-matcher.js.map