//#region src/utils/lazy-chunks.d.ts
/**
 * Build-manifest chunk metadata used to compute lazy chunks.
 */
type BuildManifestChunk = {
  file: string;
  isEntry?: boolean;
  isDynamicEntry?: boolean;
  imports?: string[];
  dynamicImports?: string[];
  css?: string[];
  assets?: string[];
};
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
declare function computeLazyChunks(buildManifest: Record<string, BuildManifestChunk>): string[];
//#endregion
export { computeLazyChunks };
//# sourceMappingURL=lazy-chunks.d.ts.map