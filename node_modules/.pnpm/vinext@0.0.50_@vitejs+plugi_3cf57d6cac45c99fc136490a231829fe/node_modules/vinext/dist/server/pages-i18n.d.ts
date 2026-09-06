import { NextI18nConfig } from "../config/next-config.js";
import { DomainLocale, detectDomainLocale } from "../utils/domain-locale.js";

//#region src/server/pages-i18n.d.ts
type HeaderValue = string | string[] | undefined;
type HeaderBag = Headers | Record<string, HeaderValue> | undefined;
type LocaleRedirectOptions = {
  headers?: HeaderBag;
  nextConfig: {
    basePath?: string;
    i18n?: NextI18nConfig | null;
    trailingSlash?: boolean;
  };
  pathLocale?: string;
  urlParsed: {
    hostname?: string | null;
    pathname: string;
    search?: string;
  };
};
type PagesI18nRequestInfo = {
  locale: string;
  url: string;
  hadPrefix: boolean;
  domainLocale?: DomainLocale;
  redirectUrl?: string;
};
/**
 * Extract locale prefix from a URL path.
 * e.g. /fr/about -> { locale: "fr", url: "/about", hadPrefix: true }
 *      /about    -> { locale: defaultLocale, url: "/about", hadPrefix: false }
 */
declare function extractLocaleFromUrl(url: string, i18nConfig: NextI18nConfig, defaultLocale?: string): {
  locale: string;
  url: string;
  hadPrefix: boolean;
};
/**
 * Detect the preferred locale from the Accept-Language header.
 * Returns the best matching locale or null.
 */
declare function detectLocaleFromAcceptLanguage(acceptLang: string | null | undefined, i18nConfig: NextI18nConfig): string | null;
/**
 * Parse the NEXT_LOCALE cookie.
 * Returns the cookie value if it matches a configured locale, otherwise null.
 */
declare function parseCookieLocaleFromHeader(cookieHeader: string | null | undefined, i18nConfig: NextI18nConfig): string | null;
declare function getLocaleRedirect({
  headers,
  nextConfig,
  pathLocale,
  urlParsed
}: LocaleRedirectOptions): string | undefined;
declare function resolvePagesI18nRequest(url: string, i18nConfig: NextI18nConfig, headers?: HeaderBag, hostname?: string | null, basePath?: string, trailingSlash?: boolean): PagesI18nRequestInfo;
//#endregion
export { detectDomainLocale, detectLocaleFromAcceptLanguage, extractLocaleFromUrl, getLocaleRedirect, parseCookieLocaleFromHeader, resolvePagesI18nRequest };
//# sourceMappingURL=pages-i18n.d.ts.map