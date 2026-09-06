import { AppRoute } from "../routing/app-route-graph.js";
import { NextHeader, NextI18nConfig, NextRedirect, NextRewrite } from "../config/next-config.js";
import { MetadataFileRoute } from "../server/metadata-routes.js";

//#region src/entries/app-rsc-entry.d.ts
/**
 * Resolved config options relevant to App Router request handling.
 * Passed from the Vite plugin where the full next.config.js is loaded.
 */
type AppRouterConfig = {
  redirects?: NextRedirect[];
  rewrites?: {
    beforeFiles: NextRewrite[];
    afterFiles: NextRewrite[];
    fallback: NextRewrite[];
  };
  headers?: NextHeader[]; /** Extra origins allowed for server action CSRF checks (from experimental.serverActions.allowedOrigins). */
  allowedOrigins?: string[]; /** Extra origins allowed for dev server access (from allowedDevOrigins). */
  allowedDevOrigins?: string[]; /** Body size limit for server actions in bytes (from experimental.serverActions.bodySizeLimit). */
  bodySizeLimit?: number; /** Route-level expire fallback in seconds for ISR entries with numeric revalidate. */
  expireTime?: number; /** Internationalization routing config for middleware matcher locale handling. */
  i18n?: NextI18nConfig | null;
  /**
   * When true, the project has a `pages/` directory alongside the App Router.
   * The generated RSC entry exposes `/__vinext/prerender/pages-static-paths`
   * so `prerenderPages` can call `getStaticPaths` via `wrangler unstable_startWorker`
   * in CF Workers builds. `pageRoutes` is loaded from the SSR environment via
   * `import("./ssr/index.js")`, which re-exports it from
   * `virtual:vinext-server-entry` when this flag is set.
   */
  hasPagesDir?: boolean; /** Exact public/ file routes, using normalized leading-slash pathnames. */
  publicFiles?: string[];
};
/**
 * Generate the virtual RSC entry module.
 *
 * This runs in the `rsc` Vite environment (react-server condition).
 * It matches the incoming request URL to an app route, builds the
 * nested layout + page tree, and renders it to an RSC stream.
 */
declare function generateRscEntry(appDir: string, routes: AppRoute[], middlewarePath?: string | null, metadataRoutes?: MetadataFileRoute[], globalErrorPath?: string | null, basePath?: string, trailingSlash?: boolean, config?: AppRouterConfig, instrumentationPath?: string | null): string;
//#endregion
export { generateRscEntry };
//# sourceMappingURL=app-rsc-entry.d.ts.map