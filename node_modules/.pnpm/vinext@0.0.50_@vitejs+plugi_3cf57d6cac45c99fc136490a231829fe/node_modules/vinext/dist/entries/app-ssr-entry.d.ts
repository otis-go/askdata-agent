//#region src/entries/app-ssr-entry.d.ts
/**
 * Generate the virtual SSR entry module.
 *
 * This runs in the `ssr` Vite environment. It receives an RSC stream,
 * deserializes it to a React tree, and renders to HTML.
 *
 * When `hasPagesDir` is true (hybrid App + Pages Router project), the SSR
 * entry also re-exports `pageRoutes` from `virtual:vinext-server-entry` so
 * that the Cloudflare Workers RSC bundle can access Pages Router route
 * metadata (including `getStaticPaths`) via `import("./ssr/index.js")`.
 */
declare function generateSsrEntry(hasPagesDir?: boolean): string;
//#endregion
export { generateSsrEntry };
//# sourceMappingURL=app-ssr-entry.d.ts.map