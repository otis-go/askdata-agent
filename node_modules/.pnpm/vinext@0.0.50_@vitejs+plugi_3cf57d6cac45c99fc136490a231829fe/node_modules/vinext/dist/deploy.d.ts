import { ensureESModule as ensureESModule$1, renameCJSConfigs as renameCJSConfigs$1 } from "./utils/project.js";

//#region src/deploy.d.ts
type DeployOptions = {
  /** Project root directory */root: string; /** Deploy to preview environment (default: production) */
  preview?: boolean; /** Wrangler environment name from wrangler.jsonc env.<name> */
  env?: string; /** Custom project name for the Worker */
  name?: string; /** Skip the build step (assume already built) */
  skipBuild?: boolean; /** Dry run — generate config files but don't build or deploy */
  dryRun?: boolean; /** Pre-render all discovered routes into the dist output after building */
  prerenderAll?: boolean; /** Maximum number of routes to prerender in parallel */
  prerenderConcurrency?: number; /** Enable experimental TPR (Traffic-aware Pre-Rendering) */
  experimentalTPR?: boolean; /** TPR: traffic coverage percentage target (0–100, default: 90) */
  tprCoverage?: number; /** TPR: hard cap on number of pages to pre-render (default: 1000) */
  tprLimit?: number; /** TPR: analytics lookback window in hours (default: 24) */
  tprWindow?: number;
};
declare function parseDeployArgs(args: string[]): {
  help: boolean;
  preview: boolean;
  env: string | undefined;
  name: string | undefined;
  skipBuild: boolean;
  dryRun: boolean;
  prerenderAll: boolean;
  prerenderConcurrency: number | undefined;
  experimentalTPR: boolean;
  tprCoverage: number | undefined;
  tprLimit: number | undefined;
  tprWindow: number | undefined;
};
type ProjectInfo = {
  root: string;
  isAppRouter: boolean;
  isPagesRouter: boolean;
  hasViteConfig: boolean;
  hasWranglerConfig: boolean;
  hasWorkerEntry: boolean;
  hasCloudflarePlugin: boolean;
  hasRscPlugin: boolean;
  hasWrangler: boolean;
  projectName: string; /** Pages that use `revalidate` (ISR) */
  hasISR: boolean; /** package.json has "type": "module" */
  hasTypeModule: boolean; /** .mdx files detected in app/ or pages/ */
  hasMDX: boolean; /** CodeHike is a dependency */
  hasCodeHike: boolean; /** Native Node modules that need stubbing for Workers */
  nativeModulesToStub: string[];
};
/** Check whether a wrangler config file exists in the given directory. */
declare function hasWranglerConfig(root: string): boolean;
/**
 * Build the error message thrown when cloudflare() is missing from the Vite config.
 * Shared between the build-time guard (index.ts configResolved) and the
 * deploy-time guard (deploy.ts deploy()).
 */
declare function formatMissingCloudflarePluginError(options: {
  isAppRouter: boolean;
  configFile?: string;
}): string;
declare function detectProject(root: string): ProjectInfo;
/** @see {@link _ensureESModule} */
declare const ensureESModule: typeof ensureESModule$1;
/** @see {@link _renameCJSConfigs} */
declare const renameCJSConfigs: typeof renameCJSConfigs$1;
/** Generate wrangler.jsonc content */
declare function generateWranglerConfig(info: ProjectInfo): string;
/** Generate worker/index.ts for App Router */
declare function generateAppRouterWorkerEntry(hasISR?: boolean): string;
/** Generate worker/index.ts for Pages Router */
declare function generatePagesRouterWorkerEntry(): string;
/** Generate vite.config.ts for App Router */
declare function generateAppRouterViteConfig(info?: ProjectInfo): string;
/** Generate vite.config.ts for Pages Router */
declare function generatePagesRouterViteConfig(info?: ProjectInfo): string;
type MissingDep = {
  name: string;
  version: string;
};
/**
 * Check if a package is resolvable from a given root directory using
 * Node's module resolution (createRequire). Handles hoisting, pnpm
 * symlinks, monorepos, and Yarn PnP correctly.
 */
declare function isPackageResolvable(root: string, packageName: string): boolean;
declare function getMissingDeps(info: ProjectInfo, /** Override for testing — defaults to `isPackageResolvable` */

_isResolvable?: (root: string, pkg: string) => boolean): MissingDep[];
type GeneratedFile = {
  path: string;
  content: string;
  description: string;
};
/**
 * Check whether an existing vite.config file already imports and uses the
 * Cloudflare Vite plugin. This is a heuristic text scan — it doesn't execute
 * the config — so it may produce false negatives for unusual configurations.
 *
 * Returns true if `@cloudflare/vite-plugin` appears to be configured, false
 * if it is missing (meaning the build will fail with "could not resolve
 * virtual:vinext-rsc-entry").
 */
declare function viteConfigHasCloudflarePlugin(root: string): boolean;
declare function getFilesToGenerate(info: ProjectInfo): GeneratedFile[];
type WranglerDeployArgs = {
  args: string[];
  env: string | undefined;
};
declare function buildWranglerDeployArgs(options: Pick<DeployOptions, "preview" | "env">): WranglerDeployArgs;
/**
 * Resolve the wrangler executable in node_modules.
 *
 * Walks up ancestor directories so the binary is found even when node_modules
 * is hoisted to the workspace root in a monorepo.
 *
 * On Windows, `node_modules/.bin/` contains both a Unix shebang script (no
 * extension) and a `.CMD` shim. Node's `execFileSync` uses CreateProcess(),
 * which only resolves PATHEXT extensions (`.cmd`, `.exe`, ...) — spawning the
 * bare-name shebang file fails with ENOENT even though the file exists. So on
 * Windows we prefer the `.CMD` shim and only fall back to the bare name for a
 * clearer error message if neither is present.
 */
declare function resolveWranglerBin(root: string, platform?: NodeJS.Platform): string;
declare function deploy(options: DeployOptions): Promise<void>;
//#endregion
export { buildWranglerDeployArgs, deploy, detectProject, ensureESModule, formatMissingCloudflarePluginError, generateAppRouterViteConfig, generateAppRouterWorkerEntry, generatePagesRouterViteConfig, generatePagesRouterWorkerEntry, generateWranglerConfig, getFilesToGenerate, getMissingDeps, hasWranglerConfig, isPackageResolvable, parseDeployArgs, renameCJSConfigs, resolveWranglerBin, viteConfigHasCloudflarePlugin };
//# sourceMappingURL=deploy.d.ts.map