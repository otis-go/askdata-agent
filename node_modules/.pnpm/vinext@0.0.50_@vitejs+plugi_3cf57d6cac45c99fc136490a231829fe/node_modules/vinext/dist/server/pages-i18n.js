import { detectDomainLocale, normalizeDomainHostname } from "../utils/domain-locale.js";
//#region src/server/pages-i18n.ts
function readHeader(headers, name) {
	if (!headers) return void 0;
	if (headers instanceof Headers) return headers.get(name) ?? void 0;
	const direct = headers[name];
	if (Array.isArray(direct)) return direct.join(", ");
	return direct;
}
const normalizeHostname = normalizeDomainHostname;
/**
* Extract locale prefix from a URL path.
* e.g. /fr/about -> { locale: "fr", url: "/about", hadPrefix: true }
*      /about    -> { locale: defaultLocale, url: "/about", hadPrefix: false }
*/
function extractLocaleFromUrl(url, i18nConfig, defaultLocale = i18nConfig.defaultLocale) {
	const parts = url.split("?")[0].split("/").filter(Boolean);
	const query = url.includes("?") ? url.slice(url.indexOf("?")) : "";
	if (parts.length > 0 && i18nConfig.locales.includes(parts[0])) return {
		locale: parts[0],
		url: ("/" + parts.slice(1).join("/") || "/") + query,
		hadPrefix: true
	};
	return {
		locale: defaultLocale,
		url,
		hadPrefix: false
	};
}
/**
* Detect the preferred locale from the Accept-Language header.
* Returns the best matching locale or null.
*/
function detectLocaleFromAcceptLanguage(acceptLang, i18nConfig) {
	if (!acceptLang) return null;
	const langs = acceptLang.split(",").map((part) => {
		const [lang, qPart] = part.trim().split(";");
		const q = qPart ? parseFloat(qPart.replace("q=", "")) : 1;
		return {
			lang: lang.trim().toLowerCase(),
			q
		};
	}).sort((a, b) => b.q - a.q);
	for (const { lang } of langs) {
		const exactMatch = i18nConfig.locales.find((locale) => locale.toLowerCase() === lang);
		if (exactMatch) return exactMatch;
		const prefix = lang.split("-")[0];
		const prefixMatch = i18nConfig.locales.find((locale) => {
			const lowered = locale.toLowerCase();
			return lowered === prefix || lowered.startsWith(prefix + "-");
		});
		if (prefixMatch) return prefixMatch;
	}
	return null;
}
/**
* Parse the NEXT_LOCALE cookie.
* Returns the cookie value if it matches a configured locale, otherwise null.
*/
function parseCookieLocaleFromHeader(cookieHeader, i18nConfig) {
	if (!cookieHeader) return null;
	const match = cookieHeader.match(/(?:^|;\s*)NEXT_LOCALE=([^;]*)/);
	if (!match) return null;
	let value;
	try {
		value = decodeURIComponent(match[1].trim());
	} catch {
		return null;
	}
	if (i18nConfig.locales.includes(value)) return value;
	return null;
}
function formatLocalizedRootPath(locale, defaultLocale, basePath = "", trailingSlash = false, search = "") {
	if (locale.toLowerCase() === defaultLocale.toLowerCase()) return void 0;
	return `${`${basePath}/${locale}${trailingSlash ? "/" : ""}`.replace(/\/{2,}/g, "/")}${search}`;
}
function getLocaleRedirect({ headers, nextConfig, pathLocale, urlParsed }) {
	const i18n = nextConfig.i18n;
	if (!i18n || i18n.localeDetection === false || urlParsed.pathname !== "/") return void 0;
	const domainLocale = detectDomainLocale(i18n.domains, urlParsed.hostname ?? void 0);
	const defaultLocale = domainLocale?.defaultLocale || i18n.defaultLocale;
	const preferredLocale = detectLocaleFromAcceptLanguage(readHeader(headers, "accept-language"), i18n) ?? void 0;
	const detectedLocale = pathLocale || domainLocale?.defaultLocale || (parseCookieLocaleFromHeader(readHeader(headers, "cookie"), i18n) ?? void 0) || preferredLocale || i18n.defaultLocale;
	const search = urlParsed.search ?? "";
	const preferredDomain = detectDomainLocale(i18n.domains, void 0, preferredLocale);
	if (domainLocale && preferredDomain) {
		const sameDomain = normalizeHostname(domainLocale.domain) === normalizeHostname(preferredDomain.domain);
		const sameLocale = preferredLocale !== void 0 && preferredDomain.defaultLocale.toLowerCase() === preferredLocale.toLowerCase();
		if (!sameDomain || !sameLocale) {
			const scheme = `http${preferredDomain.http ? "" : "s"}`;
			const localePath = sameLocale || preferredLocale === void 0 ? "" : `/${preferredLocale}`;
			const rootPath = `${nextConfig.basePath ?? ""}${localePath}${nextConfig.trailingSlash ? "/" : ""}` || "/";
			const normalizedPath = rootPath.startsWith("/") ? rootPath : `/${rootPath}`;
			return `${scheme}://${preferredDomain.domain}${normalizedPath}${search}`;
		}
	}
	return formatLocalizedRootPath(detectedLocale, defaultLocale, nextConfig.basePath, nextConfig.trailingSlash, search);
}
function resolvePagesI18nRequest(url, i18nConfig, headers, hostname, basePath = "", trailingSlash = false) {
	const domainLocale = detectDomainLocale(i18nConfig.domains, hostname ?? void 0);
	const localeInfo = extractLocaleFromUrl(url, i18nConfig, domainLocale?.defaultLocale || i18nConfig.defaultLocale);
	let redirectUrl;
	if (!localeInfo.hadPrefix) redirectUrl = getLocaleRedirect({
		headers,
		nextConfig: {
			basePath,
			i18n: i18nConfig,
			trailingSlash
		},
		urlParsed: {
			hostname,
			pathname: localeInfo.url.split("?")[0] || "/",
			search: localeInfo.url.includes("?") ? localeInfo.url.slice(localeInfo.url.indexOf("?")) : ""
		}
	});
	return {
		...localeInfo,
		domainLocale,
		redirectUrl
	};
}
//#endregion
export { detectDomainLocale, detectLocaleFromAcceptLanguage, extractLocaleFromUrl, getLocaleRedirect, parseCookieLocaleFromHeader, resolvePagesI18nRequest };

//# sourceMappingURL=pages-i18n.js.map