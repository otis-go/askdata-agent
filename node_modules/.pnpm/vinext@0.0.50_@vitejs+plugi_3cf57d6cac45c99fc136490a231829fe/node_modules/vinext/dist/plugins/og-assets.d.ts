import { Plugin } from "vite";

//#region src/plugins/og-assets.d.ts
/**
 * Create the `vinext:og-inline-fetch-assets` Vite plugin.
 *
 * Inlines binary assets that are runtime-fetched via
 * `fetch(new URL("./asset", import.meta.url))` or read via
 * `readFileSync(fileURLToPath(new URL("./asset", import.meta.url)))`.
 * Both patterns are rewritten to inline base64 literals so the code works
 * correctly inside Cloudflare Workers where `import.meta.url` is not a
 * valid file URL.
 */
declare function createOgInlineFetchAssetsPlugin(): Plugin;
/**
 * The `vinext:og-assets` Vite plugin.
 *
 * Copies @vercel/og binary assets (e.g. resvg.wasm) to the RSC output
 * directory for production builds. The edge build inlines fonts as base64 via
 * `vinext:og-inline-fetch-assets`; this plugin is a safety net to ensure
 * resvg.wasm exists in the output directory for the Node.js disk-read fallback.
 */
declare const ogAssetsPlugin: Plugin;
//#endregion
export { createOgInlineFetchAssetsPlugin, ogAssetsPlugin };
//# sourceMappingURL=og-assets.d.ts.map