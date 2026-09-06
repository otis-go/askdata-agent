import { NextConfig, NextConfigInput } from "./config/next-config.js";
import { AppStaticExportOptions, StaticExportOptions, StaticExportResult, staticExportApp, staticExportPages } from "./build/static-export.js";
import { PluginOption } from "vite";
import { Options } from "@vitejs/plugin-react";

//#region src/index.d.ts
type VinextOptions = {
  /**
   * Base directory containing the app/ and pages/ directories.
   * Can be an absolute path or a path relative to the Vite root.
   *
   * By default, vinext auto-detects: checks for app/ and pages/ at the
   * project root first, then falls back to src/app/ and src/pages/.
   */
  appDir?: string;
  /**
   * Force-disable App Router detection even when an app/ directory exists.
   * Only the Pages Router pipeline will be active.
   * Intended for testing and tools that need to build only the Pages Router
   * bundle from a hybrid (app + pages) project.
   * @default false
   */
  disableAppRouter?: boolean;
  /**
   * Override the output directory for the RSC server bundle.
   * Absolute paths are used as-is; relative paths are resolved from the
   * Vite root. Defaults to "dist/server".
   * Intended for tests that need to build multiple fixtures in parallel
   * without clobbering each other's output.
   */
  rscOutDir?: string;
  /**
   * Override the output directory for the SSR bundle.
   * Defaults to "dist/server/ssr".
   */
  ssrOutDir?: string;
  /**
   * Override the output directory for the client bundle.
   * Defaults to Vite's default (dist/client or dist).
   */
  clientOutDir?: string;
  /**
   * Inline Next.js config for projects that want to configure vinext from
   * vite.config without a separate next.config file.
   *
   * When provided, vinext skips loading next.config.* from disk and uses this
   * value instead. Supports both object-form and function-form config.
   */
  nextConfig?: NextConfigInput;
  /**
   * Auto-register @vitejs/plugin-rsc when an app/ directory is detected.
   * Set to `false` to disable auto-registration (e.g. if you configure
   * @vitejs/plugin-rsc manually with custom options).
   * @default true
   */
  rsc?: boolean;
  /**
   * Options passed to @vitejs/plugin-react (React Fast Refresh + JSX transform).
   * Enabled by default. Set to `false` to disable (e.g. if you configure
   * @vitejs/plugin-react manually in your vite.config.ts), or pass an options
   * object to customize the Babel transform.
   * @default true
   */
  react?: Options | boolean;
  /**
   * Enable build-time precompression of static assets (.br, .gz, .zst).
   *
   * When enabled, hashed assets in the client build are precompressed at
   * build time so the production server can serve them without on-the-fly
   * compression overhead.
   *
   * Disabled by default. Not useful when deploying to edge platforms
   * (Cloudflare Workers, Nitro) that handle compression at the CDN layer.
   *
   * Can also be enabled via the `--precompress` CLI flag or by setting the
   * `VINEXT_PRECOMPRESS=1` environment variable (useful for CI pipelines
   * that need to enable precompression without modifying vite.config.ts).
   * @default false
   */
  precompress?: boolean;
  /**
   * Experimental vinext-only feature flags.
   */
  experimental?: {
    /**
     * Dedup client references emitted from RSC proxy modules in dev.
     * Disabled by default until the behavior is better proven across
     * ecosystem apps.
     * @default false
     */
    clientReferenceDedup?: boolean;
  };
};
declare function vinext(options?: VinextOptions): PluginOption[];
//#endregion
export { type AppStaticExportOptions, type NextConfig, type StaticExportOptions, type StaticExportResult, VinextOptions, vinext as default, staticExportApp, staticExportPages };
//# sourceMappingURL=index.d.ts.map