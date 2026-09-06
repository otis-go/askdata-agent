import fs from "node:fs";
import { fileURLToPath } from "node:url";
//#region src/entries/runtime-entry-module.ts
/**
* Convert Windows-style backslash path separators to forward slashes.
*
* Generated entry modules embed absolute filesystem paths inside `import`
* statements. On Windows the OS-native paths use `\` which is invalid in JS
* module specifiers, so every entry generator normalizes paths through this
* helper before stringifying them into the emitted code.
*/
function normalizePathSeparators(p) {
	return p.replace(/\\/g, "/");
}
/**
* Resolve a sibling module path relative to a caller's `import.meta.url`,
* returning a forward-slash path safe for embedding in generated code.
*
* This is the single place that owns the
* `fileURLToPath(new URL(rel, base))` + path-separator normalization idiom so
* callers don't duplicate it.
*
* @param rel  - Relative path to the target module (e.g. `"../server/foo.js"`)
* @param base - The caller's `import.meta.url`
*/
function resolveEntryPath(rel, base) {
	return normalizePathSeparators(fileURLToPath(new URL(rel, base)));
}
/**
* Resolve a real runtime module for a virtual entry generator.
*
* During local development we want to point at source files (for example `.ts`),
* while packed builds only contain emitted `.js` files in `dist/`. Probe the
* common source/build extensions and fall back to the `.js` path that exists in
* published packages.
*/
function resolveRuntimeEntryModule(name) {
	for (const ext of [
		".ts",
		".js",
		".mts",
		".mjs"
	]) {
		const filePath = resolveEntryPath(`../server/${name}${ext}`, import.meta.url);
		if (fs.existsSync(filePath)) return filePath;
	}
	return resolveEntryPath(`../server/${name}.js`, import.meta.url);
}
//#endregion
export { normalizePathSeparators, resolveEntryPath, resolveRuntimeEntryModule };

//# sourceMappingURL=runtime-entry-module.js.map