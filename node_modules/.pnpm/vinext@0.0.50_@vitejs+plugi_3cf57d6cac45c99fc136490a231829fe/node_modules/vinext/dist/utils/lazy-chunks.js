//#region src/utils/lazy-chunks.ts
/**
* Compute the set of chunk filenames that are ONLY reachable through dynamic
* imports (i.e. behind React.lazy(), next/dynamic, or manual import()).
*
* These chunks should NOT be modulepreloaded in the HTML — they will be
* fetched on demand when the dynamic import executes.
*
* Algorithm: Starting from all entry chunks in the build manifest, walk the
* static `imports` tree (breadth-first). Any chunk file NOT reached by this
* walk is only reachable through `dynamicImports` and is therefore "lazy".
*
* @param buildManifest - Vite's build manifest (manifest.json), which is a
*   Record<string, ManifestChunk> where each chunk has `file`, `imports`,
*   `dynamicImports`, `isEntry`, and `isDynamicEntry` fields.
* @returns Array of chunk filenames (e.g. "assets/mermaid-NOHMQCX5.js") that
*   should be excluded from modulepreload hints.
*/
function computeLazyChunks(buildManifest) {
	const eagerFiles = /* @__PURE__ */ new Set();
	const visited = /* @__PURE__ */ new Set();
	const queue = [];
	for (const key of Object.keys(buildManifest)) if (buildManifest[key].isEntry) queue.push(key);
	while (queue.length > 0) {
		const key = queue.shift();
		if (!key || visited.has(key)) continue;
		visited.add(key);
		const chunk = buildManifest[key];
		if (!chunk) continue;
		eagerFiles.add(chunk.file);
		if (chunk.css) for (const cssFile of chunk.css) eagerFiles.add(cssFile);
		if (chunk.imports) {
			for (const imp of chunk.imports) if (!visited.has(imp)) queue.push(imp);
		}
	}
	const lazyChunks = [];
	const allFiles = /* @__PURE__ */ new Set();
	for (const key of Object.keys(buildManifest)) {
		const chunk = buildManifest[key];
		if (chunk.file && !allFiles.has(chunk.file)) {
			allFiles.add(chunk.file);
			if (!eagerFiles.has(chunk.file) && chunk.file.endsWith(".js")) lazyChunks.push(chunk.file);
		}
	}
	return lazyChunks;
}
//#endregion
export { computeLazyChunks };

//# sourceMappingURL=lazy-chunks.js.map