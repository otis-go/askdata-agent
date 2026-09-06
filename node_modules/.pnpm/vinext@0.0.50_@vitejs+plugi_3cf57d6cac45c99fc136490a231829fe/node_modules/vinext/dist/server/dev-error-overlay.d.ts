import { dismissOverlay } from "./dev-error-overlay-store.js";

//#region src/server/dev-error-overlay.d.ts
declare function installDevErrorOverlay(): void;
declare function devOnCaughtError(error: unknown, errorInfo: {
  componentStack?: string;
  errorBoundary?: unknown;
}): void;
declare function devOnUncaughtError(error: unknown, errorInfo: {
  componentStack?: string;
  errorBoundary?: unknown;
}): void;
//#endregion
export { devOnCaughtError, devOnUncaughtError, dismissOverlay, installDevErrorOverlay };
//# sourceMappingURL=dev-error-overlay.d.ts.map