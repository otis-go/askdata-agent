//#region src/shims/url-safety.d.ts
/**
 * Shared URL safety utilities for Link, Form, and navigation shims.
 *
 * Centralizes dangerous URI scheme detection so all components and
 * navigation functions use the same validation logic.
 */
declare const DANGEROUS_URL_BLOCK_MESSAGE = "Next.js has blocked a javascript: URL as a security precaution.";
declare function isDangerousScheme(url: string): boolean;
declare function assertSafeNavigationUrl(url: string): void;
//#endregion
export { DANGEROUS_URL_BLOCK_MESSAGE, assertSafeNavigationUrl, isDangerousScheme };
//# sourceMappingURL=url-safety.d.ts.map