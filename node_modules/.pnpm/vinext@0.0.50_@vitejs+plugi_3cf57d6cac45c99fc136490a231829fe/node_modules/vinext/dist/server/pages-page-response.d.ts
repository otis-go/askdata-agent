import { CachedPagesValue } from "../shims/cache.js";
import { ComponentType, ReactNode } from "react";

//#region src/server/pages-page-response.d.ts
type PagesFontPreload = {
  href: string;
  type: string;
};
type PagesI18nRenderContext = {
  locale?: string;
  locales?: string[];
  defaultLocale?: string;
  domainLocales?: unknown;
};
type PagesGsspResponse = {
  statusCode: number;
  getHeaders(): Record<string, string | number | boolean | string[]>;
};
type RenderPagesPageResponseOptions = {
  assetTags: string;
  buildId: string | null;
  clearSsrContext: () => void;
  createPageElement: (pageProps: Record<string, unknown>) => ReactNode;
  DocumentComponent: ComponentType | null;
  flushPreloads?: (() => Promise<void> | void) | undefined;
  fontLinkHeader: string;
  fontPreloads: PagesFontPreload[];
  getFontLinks: () => string[];
  getFontStyles: () => string[];
  getSSRHeadHTML?: (() => string) | undefined;
  gsspRes: PagesGsspResponse | null;
  isrCacheKey: (router: string, pathname: string) => string;
  expireSeconds?: number;
  isrRevalidateSeconds: number | null;
  isrSet: (key: string, data: CachedPagesValue, revalidateSeconds: number, tags?: string[], expireSeconds?: number) => Promise<void>;
  i18n: PagesI18nRenderContext;
  pageProps: Record<string, unknown>;
  params: Record<string, unknown>;
  renderDocumentToString: (element: ReactNode) => Promise<string>;
  renderToReadableStream: (element: ReactNode) => Promise<ReadableStream<Uint8Array>>;
  resetSSRHead?: (() => void) | undefined;
  routePattern: string;
  routeUrl: string;
  safeJsonStringify: (value: unknown) => string;
  scriptNonce?: string;
};
declare function buildPagesNextDataScript(options: Pick<RenderPagesPageResponseOptions, "buildId" | "i18n" | "pageProps" | "params" | "routePattern" | "safeJsonStringify" | "scriptNonce">): string;
declare function renderPagesPageResponse(options: RenderPagesPageResponseOptions): Promise<Response>;
//#endregion
export { PagesGsspResponse, PagesI18nRenderContext, buildPagesNextDataScript, renderPagesPageResponse };
//# sourceMappingURL=pages-page-response.d.ts.map