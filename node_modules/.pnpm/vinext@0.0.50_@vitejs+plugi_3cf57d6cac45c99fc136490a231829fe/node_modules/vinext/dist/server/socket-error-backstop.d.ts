//#region src/server/socket-error-backstop.d.ts
/**
 * Pure predicate: returns the peer-disconnect code when `err` carries
 * one of `ECONNRESET` / `EPIPE` / `ECONNABORTED`, otherwise `undefined`.
 * Exported for unit testing in isolation (no process-state mutation).
 */
declare function peerDisconnectCode(err: unknown): string | undefined;
/**
 * Test-only: returns whether the backstop has been installed in this
 * process. Used by the unit test to assert idempotent install via the
 * Symbol.for guard. Not part of the public API.
 */
declare function isSocketErrorBackstopInstalled(): boolean;
declare function installSocketErrorBackstop(): void;
//#endregion
export { installSocketErrorBackstop, isSocketErrorBackstopInstalled, peerDisconnectCode };
//# sourceMappingURL=socket-error-backstop.d.ts.map