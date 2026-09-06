import { NextI18nConfig } from "../config/next-config.js";
import { MiddlewareModule } from "./middleware-runtime.js";
import { FLIGHT_HEADERS } from "./headers.js";

//#region src/server/app-middleware.d.ts
type AppMiddlewareContext = {
  headers: Headers | null;
  requestHeaders: Headers | null;
  status: number | null;
};
type ApplyAppMiddlewareOptions = {
  basePath?: string;
  cleanPathname: string;
  context: AppMiddlewareContext;
  i18nConfig?: NextI18nConfig | null;
  isProxy: boolean;
  module: MiddlewareModule;
  request: Request;
};
type ApplyAppMiddlewareResult = {
  kind: "continue";
  cleanPathname: string;
  search: string | null;
} | {
  kind: "response";
  response: Response;
};
declare function isExternalMiddlewareRewrite(rewriteUrl: string, request: Request): boolean;
declare function proxyExternalMiddlewareRewrite(request: Request, rewriteUrl: string, context: AppMiddlewareContext): Promise<Response>;
declare function applyAppMiddleware(options: ApplyAppMiddlewareOptions): Promise<ApplyAppMiddlewareResult>;
//#endregion
export { AppMiddlewareContext, ApplyAppMiddlewareOptions, ApplyAppMiddlewareResult, FLIGHT_HEADERS, applyAppMiddleware, isExternalMiddlewareRewrite, proxyExternalMiddlewareRewrite };
//# sourceMappingURL=app-middleware.d.ts.map