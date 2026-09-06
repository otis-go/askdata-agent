//#region src/server/app-rsc-errors.d.ts
type RscRequestInfo = {
  path: string;
  method: string;
  headers: Record<string, string>;
};
type RscErrorContext = {
  routerKind: "App Router";
  routePath: string;
  routeType: "render";
};
type RscErrorReporter = (error: Error, requestInfo: RscRequestInfo, errorContext: RscErrorContext) => void;
type CreateRscOnErrorHandlerOptions = {
  errorContext: RscErrorContext | null;
  nodeEnv?: string;
  reportRequestError: RscErrorReporter;
  requestInfo: RscRequestInfo | null;
};
/**
 * djb2 hash matching Next.js's string-hash package for RSC error digests.
 */
declare function errorDigest(input: string): string;
declare function sanitizeErrorForClient(error: unknown, nodeEnv?: string | undefined): unknown;
declare function createRscOnErrorHandler(options: CreateRscOnErrorHandlerOptions): (error: unknown) => string | undefined;
//#endregion
export { createRscOnErrorHandler, errorDigest, sanitizeErrorForClient };
//# sourceMappingURL=app-rsc-errors.d.ts.map