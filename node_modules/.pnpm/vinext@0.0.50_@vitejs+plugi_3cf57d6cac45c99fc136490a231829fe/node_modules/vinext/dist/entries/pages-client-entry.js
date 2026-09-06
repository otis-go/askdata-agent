import { patternToNextFormat } from "../routing/route-validation.js";
import { pagesRouter } from "../routing/pages-router.js";
import { normalizePathSeparators } from "./runtime-entry-module.js";
import { findFileWithExts } from "./pages-entry-helpers.js";
//#region src/entries/pages-client-entry.ts
/**
* Pages Router client hydration entry generator.
*
* Generates the virtual client entry module (`virtual:vinext-client-entry`).
* This is the entry point for `vite build` (client bundle). It maps route
* patterns to dynamic imports of page modules so Vite code-splits each page
* into its own chunk. At runtime it reads __NEXT_DATA__ to determine which
* page to hydrate.
*
* Extracted from index.ts.
*/
async function generateClientEntry(pagesDir, nextConfig, fileMatcher) {
	const pageRoutes = await pagesRouter(pagesDir, nextConfig?.pageExtensions, fileMatcher);
	const appFilePath = findFileWithExts(pagesDir, "_app", fileMatcher);
	const hasApp = appFilePath !== null;
	const loaderEntries = pageRoutes.map((r) => {
		const absPath = normalizePathSeparators(r.filePath);
		const nextFormatPattern = patternToNextFormat(r.pattern);
		return `  ${JSON.stringify(nextFormatPattern)}: () => import(${JSON.stringify(absPath)})`;
	});
	const appFileBase = appFilePath ? normalizePathSeparators(appFilePath) : void 0;
	return `
import "vinext/instrumentation-client";
import React from "react";
import { hydrateRoot } from "react-dom/client";
// Eagerly import the router shim so its module-level popstate listener is
// registered.  Without this, browser back/forward buttons do nothing because
// navigateClient() is never invoked on history changes.
import "next/router";

const pageLoaders = {
${loaderEntries.join(",\n")}
};

async function hydrate() {
  const nextData = window.__NEXT_DATA__;
  if (!nextData) {
    console.error("[vinext] No __NEXT_DATA__ found");
    return;
  }

  const { pageProps } = nextData.props;
  const loader = pageLoaders[nextData.page];
  if (!loader) {
    console.error("[vinext] No page loader for route:", nextData.page);
    return;
  }

  const pageModule = await loader();
  const PageComponent = pageModule.default;
  if (!PageComponent) {
    console.error("[vinext] Page module has no default export");
    return;
  }

  let element;
  ${hasApp ? `
  try {
    const appModule = await import(${JSON.stringify(appFileBase)});
    const AppComponent = appModule.default;
    window.__VINEXT_APP__ = AppComponent;
    element = React.createElement(AppComponent, { Component: PageComponent, pageProps });
  } catch {
    element = React.createElement(PageComponent, pageProps);
  }
  ` : `
  element = React.createElement(PageComponent, pageProps);
  `}

  // Wrap with RouterContext.Provider so next/compat/router works during hydration
  const { wrapWithRouterContext } = await import("next/router");
  element = wrapWithRouterContext(element);

  const container = document.getElementById("__next");
  if (!container) {
    console.error("[vinext] No #__next element found");
    return;
  }

  const root = hydrateRoot(container, element);
  window.__VINEXT_ROOT__ = root;
  window.__VINEXT_HYDRATED_AT = performance.now();
}

hydrate();
`;
}
//#endregion
export { generateClientEntry };

//# sourceMappingURL=pages-client-entry.js.map