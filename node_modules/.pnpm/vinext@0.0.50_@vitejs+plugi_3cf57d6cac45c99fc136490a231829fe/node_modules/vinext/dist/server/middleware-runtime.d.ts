import { NextI18nConfig } from "../config/next-config.js";
import { ExecutionContextLike } from "../shims/request-context.js";
import { NextFetchEvent, NextRequest } from "../shims/server.js";

//#region src/server/middleware-runtime.d.ts
type MiddlewareModule = Record<string, unknown>;
type MiddlewareResult = {
  continue: boolean;
  redirectUrl?: string;
  redirectStatus?: number;
  rewriteUrl?: string;
  rewriteStatus?: number;
  status?: number;
  responseHeaders?: Headers;
  response?: Response;
  waitUntilPromises?: Promise<unknown>[];
};
type MiddlewareHandler = (request: NextRequest, event: NextFetchEvent) => Response | undefined | void | Promise<Response | undefined | void>;
type ExecuteMiddlewareOptions = {
  basePath?: string;
  filePath?: string;
  i18nConfig?: NextI18nConfig | null;
  includeErrorDetails?: boolean;
  isProxy: boolean;
  module: MiddlewareModule;
  normalizedPathname?: string;
  request: Request;
};
type RunGeneratedMiddlewareOptions = ExecuteMiddlewareOptions & {
  ctx?: ExecutionContextLike;
};
declare function resolveMiddlewareModuleHandler(mod: MiddlewareModule, options: {
  filePath?: string;
  isProxy: boolean;
}): MiddlewareHandler;
declare function executeMiddleware(options: ExecuteMiddlewareOptions): Promise<MiddlewareResult>;
declare function runGeneratedMiddleware(options: RunGeneratedMiddlewareOptions): Promise<MiddlewareResult>;
//#endregion
export { MiddlewareModule, MiddlewareResult, executeMiddleware, resolveMiddlewareModuleHandler, runGeneratedMiddleware };
//# sourceMappingURL=middleware-runtime.d.ts.map