//#region src/config/dotenv.d.ts
type VinextEnvMode = "development" | "production" | "test";
type LoadDotenvOptions = {
  root: string;
  mode: VinextEnvMode;
  processEnv?: NodeJS.ProcessEnv;
};
type LoadDotenvResult = {
  mode: VinextEnvMode;
  loadedFiles: string[];
  loadedEnv: Record<string, string>;
};
/**
 * Next.js-compatible dotenv lookup order (highest priority first).
 */
declare function getDotenvFiles(mode: VinextEnvMode): string[];
/**
 * Load .env files into processEnv with Next.js-like precedence:
 * process.env > .env.<mode>.local > .env.local > .env.<mode> > .env.
 *
 * This mutates processEnv (defaults to process.env).
 *
 * ## Interaction with Vite's own .env loading
 *
 * Vite also loads .env files internally during createServer()/build(). That's
 * fine — the two systems serve different purposes and don't conflict:
 *
 * - **vinext** populates `process.env` so that server-side code (SSR, API
 *   routes, Server Components) can read env vars at runtime, and so the Vite
 *   plugin's `config()` hook can scan `process.env` for `NEXT_PUBLIC_*` vars
 *   to inline via `define`.
 *
 * - **Vite** loads .env files to populate `import.meta.env.VITE_*` for its
 *   own client exposure mechanism (which Next.js apps don't use).
 *
 * Because we load first and neither system overwrites existing keys, Vite's
 * pass is effectively a no-op for overlapping keys. For `start` and `deploy`
 * commands (which don't go through Vite at all), this is the only loading.
 */
declare function loadDotenv({
  root,
  mode,
  processEnv
}: LoadDotenvOptions): LoadDotenvResult;
//#endregion
export { getDotenvFiles, loadDotenv };
//# sourceMappingURL=dotenv.d.ts.map