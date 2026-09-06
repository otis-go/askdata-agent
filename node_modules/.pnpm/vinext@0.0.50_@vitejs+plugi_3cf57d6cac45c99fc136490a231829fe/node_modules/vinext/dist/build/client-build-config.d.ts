import { UserConfig } from "vite";

//#region src/build/client-build-config.d.ts
/**
 * Create a manualChunks function for client builds.
 *
 * Splits the client bundle into:
 * - "framework" — React, ReactDOM, and scheduler (loaded on every page)
 * - "vinext"    — vinext shims (router, head, link, etc.)
 *
 * All other vendor code is left to Rollup's default chunk-splitting
 * algorithm. Rollup automatically deduplicates shared modules into
 * common chunks based on the import graph — no manual intervention
 * needed.
 *
 * Why not split every npm package into its own chunk?
 * - Per-package splitting (`vendor-X`) creates 50-200+ chunks for a
 *   typical app, far exceeding the ~25-request sweet spot for HTTP/2.
 * - gzip/brotli compress small files poorly — each file restarts with
 *   an empty dictionary, losing ~5-15% total compressed size vs fewer
 *   larger chunks (Khan Academy measured +2.5% wire size with 10x
 *   more files containing less raw code).
 * - ES module evaluation has per-module overhead that compounds on
 *   mobile devices.
 * - No major Vite-based framework (Remix, SvelteKit, Astro, TanStack)
 *   uses per-package splitting. Next.js only isolates packages >160KB.
 * - Rollup's graph-based splitting already handles the common case
 *   well: shared dependencies between routes get their own chunks,
 *   and route-specific code stays in route chunks.
 */
declare function createClientManualChunks(shimsDir: string): (id: string) => string | undefined;
/**
 * Rollup output config with manualChunks for client code-splitting.
 * Used by both CLI builds and multi-environment builds.
 *
 * experimentalMinChunkSize merges tiny shared chunks (< 10KB) back into
 * their importers. This reduces HTTP request count and improves gzip
 * compression efficiency — small files restart the compression dictionary,
 * adding ~5-15% wire overhead vs fewer larger chunks.
 */
declare function createClientOutputConfig(clientManualChunks: (id: string) => string | undefined): {
  manualChunks: (id: string) => string | undefined;
  experimentalMinChunkSize: number;
};
declare function createClientCodeSplittingConfig(clientManualChunks: (id: string) => string | undefined): {
  minSize: number;
  groups: {
    name(moduleId: string): string | null;
  }[];
};
/**
 * Rollup treeshake configuration for production client builds.
 *
 * Uses the 'recommended' preset as a safe base, then overrides
 * moduleSideEffects to strip unused re-exports from npm packages.
 *
 * The 'no-external' value for moduleSideEffects means:
 * - Local project modules: preserve side effects (CSS imports, polyfills)
 * - node_modules packages: treat as side-effect-free unless exports are used
 *
 * This is the single highest-impact optimization for large barrel-exporting
 * libraries like mermaid, @mui/material, lucide-react, etc. These libraries
 * re-export hundreds of sub-modules through barrel files. Without this,
 * Rollup preserves every sub-module even when only a few exports are consumed.
 *
 * Why 'no-external' instead of false (global side-effect-free)?
 * - User code may rely on import-time side effects (e.g., `import './global.css'`)
 * - 'no-external' is safe for app code while still enabling aggressive DCE for deps
 *
 * Why not the 'smallest' preset?
 * - 'smallest' also sets propertyReadSideEffects: false and
 *   tryCatchDeoptimization: false, which can break specific libraries
 *   that rely on property access side effects or try/catch for feature detection
 * - 'recommended' + 'no-external' gives most of the benefit with less risk
 *
 * @deprecated Use getClientTreeshakeConfigForVite(viteMajorVersion) instead
 * for Vite version compatibility. Kept for backward compatibility.
 */
declare const clientTreeshakeConfig: {
  preset: "recommended";
  moduleSideEffects: "no-external";
};
/**
 * Returns treeshake configuration appropriate for the Vite version.
 *
 * Rollup (Vite 7) supports presets like "recommended" which set multiple
 * treeshake options at once. Rolldown (Vite 8+) doesn't support presets,
 * so we only return moduleSideEffects for Vite 8+.
 *
 * The Rollup "recommended" preset sets:
 * - annotations: true (Rolldown default is also true)
 * - manualPureFunctions: [] (Rolldown default is also [])
 * - propertyReadSideEffects: true (Rolldown equivalent is 'always', the default)
 * - unknownGlobalSideEffects: false (Rolldown default is true — this is a known acceptable
 *   divergence. Slightly less aggressive DCE on unknown globals, acceptable for client bundles)
 * - correctVarValueBeforeDeclaration and tryCatchDeoptimization (Rolldown handles these differently)
 *
 * The key optimization is moduleSideEffects: "no-external", which is supported
 * by both bundlers and provides the DCE benefits for barrel-exporting libraries.
 * It treats node_modules as side-effect-free (enabling aggressive DCE) while
 * preserving side effects in local code.
 */
declare function getClientTreeshakeConfigForVite(viteMajorVersion: number): {
  moduleSideEffects: "no-external";
  preset?: undefined;
} | {
  preset: "recommended";
  moduleSideEffects: "no-external";
};
type VinextBuildConfig = NonNullable<UserConfig["build"]>;
type VinextBuildBundlerOptions = NonNullable<VinextBuildConfig["rolldownOptions"]>;
type VinextBuildConfigWithLegacy = VinextBuildConfig & {
  rollupOptions?: VinextBuildBundlerOptions;
};
declare function getBuildBundlerOptions(build: UserConfig["build"] | undefined): VinextBuildBundlerOptions | undefined;
declare function withBuildBundlerOptions(viteMajorVersion: number, bundlerOptions: VinextBuildBundlerOptions): Partial<VinextBuildConfigWithLegacy>;
//#endregion
export { clientTreeshakeConfig, createClientCodeSplittingConfig, createClientManualChunks, createClientOutputConfig, getBuildBundlerOptions, getClientTreeshakeConfigForVite, withBuildBundlerOptions };
//# sourceMappingURL=client-build-config.d.ts.map