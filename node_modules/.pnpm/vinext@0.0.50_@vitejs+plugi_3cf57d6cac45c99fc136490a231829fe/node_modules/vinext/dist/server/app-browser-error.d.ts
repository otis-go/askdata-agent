//#region src/server/app-browser-error.d.ts
declare function createOnUncaughtError(getRecoveryHref: () => string | null): (error: unknown, errorInfo: {
  componentStack?: string;
}) => void;
//#endregion
export { createOnUncaughtError };
//# sourceMappingURL=app-browser-error.d.ts.map