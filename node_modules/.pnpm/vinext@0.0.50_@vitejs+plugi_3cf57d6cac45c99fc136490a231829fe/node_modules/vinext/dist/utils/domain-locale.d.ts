import { NextI18nConfig } from "../config/next-config.js";

//#region src/utils/domain-locale.d.ts
type DomainLocale = NonNullable<NextI18nConfig["domains"]>[number];
declare function normalizeDomainHostname(hostname: string | null | undefined): string | undefined;
/**
 * Match a configured domain either by hostname or locale.
 * When both are provided, the checks intentionally use OR semantics so the
 * same helper can cover Next.js's hostname lookup and preferred-locale lookup.
 * If both are passed, the first domain matching either input wins, so callers
 * should pass hostname or detectedLocale, not both.
 */
declare function detectDomainLocale(domainItems?: readonly DomainLocale[], hostname?: string, detectedLocale?: string): DomainLocale | undefined;
declare function addLocalePrefix(path: string, locale: string, localeDefault: string): string;
declare function getDomainLocaleUrl(url: string, locale: string, {
  basePath,
  currentHostname,
  domainItems
}: {
  basePath?: string;
  currentHostname?: string | null;
  domainItems?: readonly DomainLocale[];
}): string | undefined;
//#endregion
export { DomainLocale, addLocalePrefix, detectDomainLocale, getDomainLocaleUrl, normalizeDomainHostname };
//# sourceMappingURL=domain-locale.d.ts.map