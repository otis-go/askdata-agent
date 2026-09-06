import { HasCondition, NextI18nConfig } from "../config/next-config.js";

//#region src/server/middleware-matcher.d.ts
type MiddlewareMatcherObject = {
  source: string;
  locale?: false;
  has?: HasCondition[];
  missing?: HasCondition[];
};
type MatcherConfig = string | Array<string | MiddlewareMatcherObject>;
declare function matchesMiddleware(pathname: string, matcher: MatcherConfig | undefined, request?: Request, i18nConfig?: NextI18nConfig | null): boolean;
declare function matchPattern(pathname: string, pattern: string): boolean;
//#endregion
export { MatcherConfig, MiddlewareMatcherObject, matchPattern, matchesMiddleware };
//# sourceMappingURL=middleware-matcher.d.ts.map