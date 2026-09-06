import { ResolvedNextConfig } from "../config/next-config.js";
import { Plugin } from "vite";

//#region src/plugins/optimize-imports.d.ts
type BarrelExportEntry = {
  source: string;
  isNamespace: boolean;
  originalName?: string;
};
type BarrelExportMap = Map<string, BarrelExportEntry>;
/**
 * Packages whose barrel imports are automatically optimized.
 * Matches Next.js's built-in optimizePackageImports defaults plus radix-ui.
 * @see https://github.com/vercel/next.js/blob/9c31bbdaa/packages/next/src/server/config.ts#L1301
 */
declare const DEFAULT_OPTIMIZE_PACKAGES: string[];
/**
 * Build a map of exported names → source sub-module for a barrel package.
 *
 * Parses the barrel entry file AST and extracts the export map.
 * Handles: `export * as X from`, `export { A } from`, `import * as X; export { X }`,
 * and `export * from "./sub"` (recursively resolves wildcard re-exports).
 *
 * Returns null if the entry cannot be resolved, the file cannot be read, or
 * the file has a parse error. Returns an empty map if the file is valid but
 * exports nothing.
 */
declare function buildBarrelExportMap(packageName: string, resolveEntry: (pkg: string) => string | null, readFile: (filepath: string) => Promise<string | null>, cache?: Map<string, BarrelExportMap>): Promise<BarrelExportMap | null>;
/**
 * Creates the vinext:optimize-imports Vite plugin.
 *
 * @param nextConfig - Resolved Next.js config (may be undefined before config hook runs).
 * @param getRoot - Returns the current project root (set by the vinext:config hook).
 */
declare function createOptimizeImportsPlugin(getNextConfig: () => ResolvedNextConfig | undefined, getRoot: () => string): Plugin;
//#endregion
export { DEFAULT_OPTIMIZE_PACKAGES, buildBarrelExportMap, createOptimizeImportsPlugin };
//# sourceMappingURL=optimize-imports.d.ts.map