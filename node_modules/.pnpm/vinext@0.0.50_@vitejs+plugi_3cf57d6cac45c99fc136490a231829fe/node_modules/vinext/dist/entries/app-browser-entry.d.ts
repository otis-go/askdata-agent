import { AppRoute } from "../routing/app-route-graph.js";

//#region src/entries/app-browser-entry.d.ts
/**
 * Generate the virtual browser entry module.
 *
 * This runs in the client (browser). It hydrates the page from the
 * embedded RSC payload and handles client-side navigation by re-fetching
 * RSC streams.
 */
declare function generateBrowserEntry(routes?: readonly AppRoute[]): string;
//#endregion
export { generateBrowserEntry };
//# sourceMappingURL=app-browser-entry.d.ts.map