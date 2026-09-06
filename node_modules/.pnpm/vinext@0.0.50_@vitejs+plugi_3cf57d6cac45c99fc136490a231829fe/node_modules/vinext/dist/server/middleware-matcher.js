import { removeTrailingSlash } from "../utils/base-path.js";
import { checkHasConditions, requestContextFromRequest, safeRegExp } from "../config/config-matchers.js";
//#region src/server/middleware-matcher.ts
const EMPTY_MIDDLEWARE_REQUEST_CONTEXT = {
	headers: new Headers(),
	cookies: {},
	query: new URLSearchParams(),
	host: ""
};
const _mwPatternCache = /* @__PURE__ */ new Map();
function matchesMiddleware(pathname, matcher, request, i18nConfig) {
	if (!matcher) return true;
	if (typeof matcher === "string") return matchMatcherPattern(pathname, matcher, i18nConfig);
	if (!Array.isArray(matcher)) return false;
	const requestContext = request ? requestContextFromRequest(request) : EMPTY_MIDDLEWARE_REQUEST_CONTEXT;
	for (const m of matcher) {
		if (typeof m === "string") {
			if (matchMatcherPattern(pathname, m, i18nConfig)) return true;
			continue;
		}
		if (isValidMiddlewareMatcherObject(m)) {
			if (!matchObjectMatcher(pathname, m, i18nConfig)) continue;
			if (!checkHasConditions(m.has, m.missing, requestContext)) continue;
			return true;
		}
	}
	return false;
}
function isValidMiddlewareMatcherObject(value) {
	if (!value || typeof value !== "object" || Array.isArray(value)) return false;
	if (!("source" in value) || typeof value.source !== "string") return false;
	for (const key of Object.keys(value)) if (key !== "source" && key !== "locale" && key !== "has" && key !== "missing") return false;
	if ("locale" in value && value.locale !== void 0 && value.locale !== false) return false;
	if ("has" in value && value.has !== void 0 && !Array.isArray(value.has)) return false;
	if ("missing" in value && value.missing !== void 0 && !Array.isArray(value.missing)) return false;
	return true;
}
function matchMatcherPattern(pathname, pattern, i18nConfig) {
	if (!i18nConfig) return matchPattern(pathname, pattern);
	return matchPattern(stripLocalePrefix(pathname, i18nConfig) ?? pathname, pattern);
}
function matchObjectMatcher(pathname, matcher, i18nConfig) {
	return matcher.locale === false ? matchPattern(pathname, matcher.source) : matchMatcherPattern(pathname, matcher.source, i18nConfig);
}
function stripLocalePrefix(pathname, i18nConfig) {
	if (pathname === "/") return null;
	const segments = pathname.split("/");
	const firstSegment = segments[1];
	if (!firstSegment || !i18nConfig.locales.includes(firstSegment)) return null;
	return removeTrailingSlash("/" + segments.slice(2).join("/"));
}
function matchPattern(pathname, pattern) {
	let cached = _mwPatternCache.get(pattern);
	if (cached === void 0) {
		cached = compileMatcherPattern(pattern);
		_mwPatternCache.set(pattern, cached);
	}
	if (cached === null) return pathname === pattern;
	return cached.test(pathname);
}
function extractConstraint(str, re) {
	if (str[re.lastIndex] !== "(") return null;
	const start = re.lastIndex + 1;
	let depth = 1;
	let i = start;
	while (i < str.length && depth > 0) {
		if (str[i] === "(") depth++;
		else if (str[i] === ")") depth--;
		i++;
	}
	if (depth !== 0) return null;
	re.lastIndex = i;
	return str.slice(start, i - 1);
}
function compileMatcherPattern(pattern) {
	const hasConstraints = /:[\w-]+[*+]?\(/.test(pattern);
	if (!hasConstraints && (pattern.includes("(") || pattern.includes("\\"))) return safeRegExp("^" + pattern + "$");
	let regexStr = "";
	const tokenRe = /\/:([\w-]+)\*|\/:([\w-]+)\+|:([\w-]+)|[.]|[^/:.]+|./g;
	let tok;
	while ((tok = tokenRe.exec(pattern)) !== null) if (tok[1] !== void 0) {
		const constraint = hasConstraints ? extractConstraint(pattern, tokenRe) : null;
		regexStr += constraint !== null ? `(?:/(${constraint}))?` : "(?:/.*)?";
	} else if (tok[2] !== void 0) {
		const constraint = hasConstraints ? extractConstraint(pattern, tokenRe) : null;
		regexStr += constraint !== null ? `(?:/(${constraint}))` : "(?:/.+)";
	} else if (tok[3] !== void 0) {
		const constraint = hasConstraints ? extractConstraint(pattern, tokenRe) : null;
		const isOptional = pattern[tokenRe.lastIndex] === "?";
		if (isOptional) tokenRe.lastIndex += 1;
		const group = constraint !== null ? `(${constraint})` : "([^/]+)";
		if (isOptional && regexStr.endsWith("/")) regexStr = regexStr.slice(0, -1) + `(?:/${group})?`;
		else if (isOptional) regexStr += `${group}?`;
		else regexStr += group;
	} else if (tok[0] === ".") regexStr += "\\.";
	else regexStr += tok[0];
	return safeRegExp("^" + regexStr + "$");
}
//#endregion
export { matchPattern, matchesMiddleware };

//# sourceMappingURL=middleware-matcher.js.map