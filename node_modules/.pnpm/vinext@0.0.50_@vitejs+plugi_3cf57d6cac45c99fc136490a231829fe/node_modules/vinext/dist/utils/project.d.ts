//#region src/utils/project.d.ts
/**
 * Shared project utilities — used by both `vinext init` and `vinext deploy`.
 *
 * These functions detect and modify project configuration without touching
 * any Next.js source files, config files, or tsconfig.json.
 */
/**
 * Ensure package.json has "type": "module".
 * Returns true if it was added (i.e. it wasn't already there).
 */
declare function ensureESModule(root: string): boolean;
/**
 * Rename CJS config files (that use `module.exports`) to .cjs
 * to avoid breakage when "type": "module" is added.
 * Returns array of [oldName, newName] pairs that were renamed.
 */
declare function renameCJSConfigs(root: string): Array<[string, string]>;
/**
 * Ensure the project is configured for ESM before Vite loads vite.config.ts.
 *
 * This mirrors what `vinext init` does, but is applied lazily at dev/build
 * time for projects that were set up before `vinext init` added the step.
 *
 * Side effects: may rename `.js` CJS config files to `.cjs` and add
 * `"type": "module"` to package.json.
 *
 * @returns Object describing what was changed, or null if nothing was done.
 */
declare function ensureViteConfigCompatibility(root: string): {
  renamed: Array<[string, string]>;
  addedTypeModule: boolean;
} | null;
type PackageManagerName = "pnpm" | "yarn" | "bun" | "npm";
/**
 * Detect which package manager name is used.
 * Priority:
 * 1) lock files (walks up parent directories for monorepo support)
 * 2) package.json#packageManager
 * 3) invoking CLI user agent (npm_config_user_agent)
 * 4) npm fallback
 */
declare function detectPackageManagerName(root: string, env?: Record<string, string | undefined>): PackageManagerName;
/**
 * Detect which package manager install command to use.
 * Returns the dev-install command string (e.g. "pnpm add -D").
 */
declare function detectPackageManager(root: string): string;
/**
 * Walk from `start` up to the filesystem root looking for a path inside
 * node_modules. Returns the first absolute path found, or null.
 *
 * Handles monorepos where packages are hoisted to the workspace root's
 * node_modules rather than installed in each app's own node_modules.
 *
 * @param start   - Directory to begin the search (usually the project root)
 * @param subPath - Path relative to a node_modules dir, e.g. ".bin/wrangler"
 *                  or "@cloudflare/vite-plugin"
 */
declare function findInNodeModules(start: string, subPath: string): string | null;
/**
 * Check if a vite.config file exists in the project root.
 */
declare function hasViteConfig(root: string): boolean;
/**
 * Check if the project uses App Router (has an app/ directory).
 */
declare function hasAppDir(root: string): boolean;
//#endregion
export { detectPackageManager, detectPackageManagerName, ensureESModule, ensureViteConfigCompatibility, findInNodeModules, hasAppDir, hasViteConfig, renameCJSConfigs };
//# sourceMappingURL=project.d.ts.map