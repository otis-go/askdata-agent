import { Route } from "../routing/pages-router.js";
import { CachedPagesValue } from "../shims/cache.js";
import { ISRCacheEntry } from "./isr-cache.js";
import { PagesGsspResponse, PagesI18nRenderContext } from "./pages-page-response.js";
import { ReactNode } from "react";

//#region src/server/pages-page-data.d.ts
type PagesRedirectResult = {
  destination: string;
  permanent?: boolean;
  statusCode?: number;
};
type PagesStaticPathsEntry = {
  params: Record<string, unknown>;
};
type PagesStaticPathsResult = {
  fallback?: boolean | "blocking";
  paths?: PagesStaticPathsEntry[];
};
type PagesPagePropsResult = {
  props?: Record<string, unknown>;
  redirect?: PagesRedirectResult;
  notFound?: boolean;
  revalidate?: number;
};
type PagesMutableGsspResponse = {
  headersSent: boolean;
} & PagesGsspResponse;
type PagesGsspContextResponse = {
  req: unknown;
  res: PagesMutableGsspResponse;
  responsePromise: Promise<Response>;
};
type PagesPageModule = {
  default?: unknown;
  getStaticPaths?: (context: {
    locales: string[];
    defaultLocale: string;
  }) => Promise<PagesStaticPathsResult> | PagesStaticPathsResult;
  getServerSideProps?: (context: {
    params: Record<string, unknown>;
    req: unknown;
    res: PagesMutableGsspResponse;
    query: Record<string, unknown>;
    resolvedUrl: string;
    locale?: string;
    locales?: string[];
    defaultLocale?: string;
  }) => Promise<PagesPagePropsResult> | PagesPagePropsResult;
  getStaticProps?: (context: {
    params: Record<string, unknown>;
    locale?: string;
    locales?: string[];
    defaultLocale?: string;
  }) => Promise<PagesPagePropsResult> | PagesPagePropsResult;
};
type RenderPagesIsrHtmlOptions = {
  buildId: string | null;
  cachedHtml: string;
  createPageElement: (pageProps: Record<string, unknown>) => ReactNode;
  i18n: PagesI18nRenderContext;
  pageProps: Record<string, unknown>;
  params: Record<string, unknown>;
  renderIsrPassToStringAsync: (element: ReactNode) => Promise<string>;
  routePattern: string;
  safeJsonStringify: (value: unknown) => string;
};
type ResolvePagesPageDataOptions = {
  applyRequestContexts: () => void;
  buildId: string | null;
  createGsspReqRes: () => PagesGsspContextResponse;
  createPageElement: (pageProps: Record<string, unknown>) => ReactNode;
  fontLinkHeader: string;
  i18n: PagesI18nRenderContext;
  isrCacheKey: (router: string, pathname: string) => string;
  isrGet: (key: string) => Promise<ISRCacheEntry | null>;
  isrSet: (key: string, data: CachedPagesValue, revalidateSeconds: number, tags?: string[], expireSeconds?: number) => Promise<void>;
  expireSeconds?: number;
  pageModule: PagesPageModule;
  params: Record<string, unknown>;
  query: Record<string, unknown>;
  route: Pick<Route, "isDynamic">;
  routePattern: string;
  routeUrl: string;
  runInFreshUnifiedContext: <T>(callback: () => Promise<T>) => Promise<T>;
  safeJsonStringify: (value: unknown) => string;
  sanitizeDestination: (destination: string) => string;
  scriptNonce?: string;
  triggerBackgroundRegeneration: (key: string, renderFn: () => Promise<void>, errorContext?: {
    routerKind: "Pages Router";
    routePath: string;
    routeType: "render";
  }) => void;
  renderIsrPassToStringAsync: (element: ReactNode) => Promise<string>;
};
type ResolvePagesPageDataRenderResult = {
  kind: "render";
  gsspRes: PagesGsspResponse | null;
  isrRevalidateSeconds: number | null;
  pageProps: Record<string, unknown>;
};
type ResolvePagesPageDataResponseResult = {
  kind: "response";
  response: Response;
};
type ResolvePagesPageDataResult = ResolvePagesPageDataRenderResult | ResolvePagesPageDataResponseResult;
declare function renderPagesIsrHtml(options: RenderPagesIsrHtmlOptions): Promise<string>;
declare function resolvePagesPageData(options: ResolvePagesPageDataOptions): Promise<ResolvePagesPageDataResult>;
//#endregion
export { PagesGsspContextResponse, PagesMutableGsspResponse, PagesPageModule, ResolvePagesPageDataOptions, renderPagesIsrHtml, resolvePagesPageData };
//# sourceMappingURL=pages-page-data.d.ts.map