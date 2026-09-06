import { ValidFileMatcher } from "../routing/file-matcher.js";
import { Route } from "../routing/pages-router.js";
import { NextI18nConfig } from "../config/next-config.js";
import { ModuleImporter } from "./instrumentation.js";
import { ViteDevServer } from "vite";
import { IncomingMessage, ServerResponse } from "node:http";

//#region src/server/dev-server.d.ts
/**
 * Extract locale prefix from a URL path.
 * e.g. /fr/about -> { locale: "fr", url: "/about", hadPrefix: true }
 *      /about    -> { locale: "en", url: "/about", hadPrefix: false } (defaultLocale)
 */
declare function extractLocaleFromUrl(url: string, i18nConfig: NextI18nConfig): {
  locale: string;
  url: string;
  hadPrefix: boolean;
};
/**
 * Detect the preferred locale from the Accept-Language header.
 * Returns the best matching locale or null.
 */
declare function detectLocaleFromHeaders(req: IncomingMessage, i18nConfig: NextI18nConfig): string | null;
/**
 * Parse the NEXT_LOCALE cookie from a request.
 * Returns the cookie value if it matches a configured locale, otherwise null.
 */
declare function parseCookieLocale(req: IncomingMessage, i18nConfig: NextI18nConfig): string | null;
/**
 * Create an SSR request handler for the Pages Router.
 *
 * For each request:
 * 1. Match the URL against discovered routes
 * 2. Load the page module via the ModuleRunner
 * 3. Call getServerSideProps/getStaticProps if present
 * 4. Render the component to HTML
 * 5. Wrap in _document shell and send response
 */
declare function createSSRHandler(server: ViteDevServer, runner: ModuleImporter, routes: Route[], pagesDir: string, i18nConfig?: NextI18nConfig | null, fileMatcher?: ValidFileMatcher, basePath?: string, trailingSlash?: boolean): (req: IncomingMessage, res: ServerResponse, url: string, /** Status code override — propagated from middleware rewrite status. */

statusCode?: number) => Promise<void>;
//#endregion
export { createSSRHandler, detectLocaleFromHeaders, extractLocaleFromUrl, parseCookieLocale };
//# sourceMappingURL=dev-server.d.ts.map