//#region src/server/http-error-responses.d.ts
/**
 * Shared HTTP error response builders.
 *
 * Centralizes the canonical `new Response("...", { status: 4xx | 5xx })` patterns
 * that previously were scattered across server modules. Each helper standardizes
 * the canonical body for its status; the optional `headers` argument lets callers
 * merge middleware/middleware-context headers without re-implementing the
 * `new Response(...)` boilerplate.
 *
 * Sites with route-specific bodies (e.g. `"404 - API route not found"`,
 * `"Image not found"`, generated worker templates) intentionally remain inline
 * because their bodies are either tested-against fixtures or run inside template
 * strings that have no access to runtime imports.
 *
 * Follow-up to #1058 / #1071 / #1078, which extracted the first batch of these
 * helpers (action/page error responses, `forbiddenResponse`, `payloadTooLargeResponse`).
 */
type ErrorResponseInit = {
  headers?: HeadersInit;
};
/**
 * Build a 400 Bad Request plain-text response.
 *
 * Used for malformed percent-encoding, invalid HTTP methods (where Next.js
 * returns 400), and other request-shape validation failures.
 */
declare function badRequestResponse(init?: ErrorResponseInit): Response;
/**
 * Build a 403 Forbidden plain-text response.
 *
 * Used by CSRF origin validation and dev-server origin checks.
 */
declare function forbiddenResponse(): Response;
/**
 * Build a 404 Not Found plain-text response.
 *
 * The `headers` option lets call sites merge middleware response headers into
 * the 404, matching the pattern used by `app-rsc-handler` after a route match
 * fails but middleware has already contributed headers.
 */
declare function notFoundResponse(init?: ErrorResponseInit): Response;
/**
 * Build a 405 Method Not Allowed plain-text response with the `Allow` header set.
 *
 * `allowedMethods` is rendered as the comma-separated `Allow` header value.
 * Existing headers (e.g. middleware response headers) can be merged via `init.headers`;
 * the `Allow` header takes precedence and overwrites any colliding entry.
 */
declare function methodNotAllowedResponse(allowedMethods: string, init?: ErrorResponseInit): Response;
/**
 * Build a 413 Payload Too Large plain-text response.
 *
 * Used by server action body-size enforcement.
 */
declare function payloadTooLargeResponse(): Response;
/**
 * Build a 500 Internal Server Error plain-text response.
 *
 * The `message` argument lets dev-mode handlers surface failure details while
 * production paths fall back to the canonical body. Pass `undefined` (or omit)
 * to use the canonical "Internal Server Error" body.
 */
declare function internalServerErrorResponse(message?: string, init?: ErrorResponseInit): Response;
//#endregion
export { badRequestResponse, forbiddenResponse, internalServerErrorResponse, methodNotAllowedResponse, notFoundResponse, payloadTooLargeResponse };
//# sourceMappingURL=http-error-responses.d.ts.map