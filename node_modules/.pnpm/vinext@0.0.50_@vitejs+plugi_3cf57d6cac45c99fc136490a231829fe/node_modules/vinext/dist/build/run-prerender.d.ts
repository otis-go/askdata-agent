import { ResolvedNextConfig } from "../config/next-config.js";
import { PrerenderResult } from "./prerender.js";

//#region src/build/run-prerender.d.ts
type RunPrerenderOptions = {
  /** Project root directory. */root: string;
  /**
   * Override next.config values. Merged on top of the config loaded from disk.
   * Intended for tests that need to exercise a specific config (e.g. output: 'export')
   * without writing a next.config file.
   */
  nextConfigOverride?: Partial<ResolvedNextConfig>;
  /**
   * Override the path to the Pages Router server bundle.
   * Defaults to `<root>/dist/server/entry.js`.
   * Intended for tests that build to a custom outDir.
   */
  pagesBundlePath?: string;
  /**
   * Override the path to the App Router RSC bundle.
   * Defaults to `<root>/dist/server/index.js`.
   * Intended for tests that build to a custom outDir.
   */
  rscBundlePath?: string;
  /**
   * Maximum number of routes rendered in parallel.
   * Defaults to prerenderApp/prerenderPages internal defaults when omitted.
   */
  concurrency?: number;
};
/**
 * Run the prerender phase using pre-built production bundles.
 *
 * Scans routes, starts a local production server, renders every static/ISR
 * route via HTTP, writes output files to `dist/server/prerendered-routes/`
 * (non-export) or `dist/client/` (export), and prints a progress bar + summary
 * to stderr/stdout. Returns the full PrerenderResult so callers can pass it to
 * printBuildReport.
 *
 * Works for both plain Node and Cloudflare Workers builds — the CF Workers
 * bundle outputs `dist/server/index.js` which is a standard Node server entry,
 * so no wrangler/miniflare is needed.
 *
 * Hybrid projects (both `app/` and `pages/` present) run both prerender
 * phases sharing a single prod server instance. The merged results are written
 * to a single `dist/server/vinext-prerender.json`.
 *
 * If a required production bundle does not exist, an error is thrown directing
 * the user to run `vinext build` first.
 */
declare function runPrerender(options: RunPrerenderOptions): Promise<PrerenderResult | null>;
//#endregion
export { runPrerender };
//# sourceMappingURL=run-prerender.d.ts.map