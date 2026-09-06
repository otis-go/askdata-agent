//#region src/build/ssr-manifest.d.ts
type BundleBackfillChunk = {
  type: "chunk";
  fileName: string;
  imports?: string[];
  modules?: Record<string, unknown>;
  viteMetadata?: {
    importedCss?: Set<string>;
    importedAssets?: Set<string>;
  };
};
declare function tryRealpathSync(candidate: string): string | null;
declare function relativeWithinRoot(root: string, moduleId: string): string | null;
declare function augmentSsrManifestFromBundle(ssrManifest: Record<string, string[]>, bundle: Record<string, BundleBackfillChunk | {
  type: string;
}>, root: string, base?: string): Record<string, string[]>;
//#endregion
export { BundleBackfillChunk, augmentSsrManifestFromBundle, relativeWithinRoot, tryRealpathSync };
//# sourceMappingURL=ssr-manifest.d.ts.map